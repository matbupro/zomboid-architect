"""
main.py — Point d'entrée du bot Discord Zomboid Knowledge Engine.

Le bot expose :
- Des slash commands (/help, /stats, /survie, /recipe, /moddoc, /search)
- Un mode DM automatique (capture de messages → pipeline complet)
- Des réponses embed formatées avec contexte et réponse LLM

Usage :
    python -m bot.main          # lancement direct
    docker compose up bot       # lancement via Docker
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

# Logging centralisé via src.governance.logger
from src.governance.logger import get_logger

logger = get_logger("bot")

# ---------------------------------------------------------------------------
# Initialisation du bot
# ---------------------------------------------------------------------------

from .config import load_settings  # noqa: E402
from .engine_client import KnowledgeEngineClient  # noqa: E402
from .llm_adapter import create_providers, LLMProvider  # noqa: E402
from .pipeline import process_message  # noqa: E402

# Game version auto-resolve (B41/B42) — héritée de src/governance/game_version.py
from src.governance.game_version import get_current_game_version  # noqa: E402

settings = load_settings()

# Résoudre la version du jeu cible (B41/B42) au démarrage
_current_game_version: str | None = None
try:
    gv = get_current_game_version()
    _current_game_version = gv.value  # "b41" ou "b42"
except ValueError:
    logger.warning("Impossible de résoudre PZ_GAME_VERSION — aucun filtrage de version")
    _current_game_version = None

if not settings.DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN est vide. Remplir .env.unified a la racine du projet.")
    sys.exit(1)

# Intents nécessaires
intents = discord.Intents.default()
intents.message_content = True  # Nécessaire pour lire les DMs
intents.messages = True
intents.guilds = True
intents.members = True

# command_prefix="" → on n'utilise QUE les slash commands (pas de prefix)
bot = commands.Bot(command_prefix="", intents=intents)

# Client knowledge engine + LLM provider
engine = KnowledgeEngineClient()  # SQLite/PostgreSQL via StorageBackend
ollama, claude = create_providers(
    ollama_url=settings.OLLAMA_BASE_URL,
    ollama_model=settings.OLLAMA_MODEL,
    claude_key=settings.CLAUDE_API_KEY,
    claude_model=settings.CLAUDE_MODEL,
)
llm: LLMProvider = ollama  # préférence locale

# Timeout par défaut pour les appels LLM (secondes)
LLM_TIMEOUT = 180.0  # 3 min — qwen3.6 est gros


def _wrap_llm(coro):
    """Enveloppe un coroutine LLM avec timeout."""
    return asyncio.wait_for(coro, timeout=LLM_TIMEOUT)


# ---------------------------------------------------------------------------
# Canal workspace (résolu dynamiquement au démarrage)
# ---------------------------------------------------------------------------

_workspace_channel: discord.TextChannel | None = None  # canalisé en on_ready
# Racine du repo : d'abord /app/ (COPY Docker), puis /app/zomboid_repo/ (volume mount)
_PROJECT_ROOT = Path(__file__).parent.parent              # racine du repo Zomboid_Architect
if not _PROJECT_ROOT.joinpath("agent", "todo.md").exists():
    _PROJECT_ROOT = _PROJECT_ROOT / "zomboid_repo"       # fallback volume mount


# ---------------------------------------------------------------------------
# Helpers de réponse Discord (embed formatés)
# ---------------------------------------------------------------------------


def _format_response(result: Any) -> discord.Embed:
    """Convertit un PromptResult en Embed Discord."""
    ctx_lines = []
    for item in result.raw_context[:3]:  # Max 3 résultats
        meta_str = json.dumps(item.metadata_, ensure_ascii=False, indent=2) if hasattr(item, 'metadata_') else str(getattr(item, 'metadata_', {}))
        ctx_lines.append(f"**{item.id}**\n```json\n{meta_str[:300]}\n```\n")

    title = f"Zomboid — Réponse"
    description = result.llm_response[:3800]  # Limite Discord embed ~4000 chars

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.dark_green(),
    )

    if ctx_lines:
        embed.add_field(name="Contexte (JSON brut)", value="\n".join(ctx_lines), inline=False)

    return embed


def _trunc_string(text: str, limit: int = 1950) -> list[str]:
    """Coupe une longue chaîne en messages Discord successifs."""
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        chunk = text[:limit]
        # Chercher un break naturel (espace ou saut de ligne)
        last_break = chunk.rfind("\n", max(0, limit - 200)) or chunk.rfind(" ", max(0, limit - 200))
        if last_break > 100:
            chunk = chunk[:last_break]
            text = text[last_break:].lstrip()
        else:
            text = text[len(chunk):]
        parts.append(chunk)
    return parts


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="help", description="Affiche les commandes disponibles du bot Zomboid")
async def cmd_help(interaction: discord.Interaction):
    """Commande /help — affichage des commandes."""
    help_text = (
        "**Zomboid Knowledge Engine**\n\n"
        "**Slash commands :**\n"
        "/stats <item> — Stats exactes d'un objet (Base.Axe, etc.)\n"
        "/survie <scenario> — Conseil de survie hardcore\n"
        "/recipe <ingredient> — Recettes d'artisanat\n"
        "/moddoc <api> — Documentation modding Lua/Java\n"
        "/search <query> — Recherche sémantique libre\n"
        "/modgen <desc> — Genere un mod Project Zomboid a partir d'une description\n"
        "/modpublish <nom_du_mod> — Publie un mod genere vers le Steam Workshop\n\n"
        "**DM** — Envoie-moi un message en DM, je réponds automatiquement !"
    )

    embed = discord.Embed(
        title="Zomboid Knowledge Engine",
        description=help_text,
        color=discord.Color.dark_green(),
    )
    embed.set_footer(text="Propulsé par Ollama local + SQLite")
    await interaction.response.send_message(embed=embed)


async def _run_llm_command(interaction: discord.Interaction, cmd_type: str, query_text: str):
    """Execute un command with LLM and timeout handling."""
    await interaction.response.defer()

    try:
        result = await _wrap_llm(
            process_message(
                f"/{cmd_type} {query_text}",
                engine=engine, llm=llm,
                system_prompt=settings.DEFAULT_SYSTEM_PROMPT,
                game_version=_current_game_version,
            )
        )
    except asyncio.TimeoutError:
        logger.exception("cmd_%s(%q) timeout après %.0fs", cmd_type, query_text[:50], LLM_TIMEOUT)
        await interaction.followup.send(
            "[TIMEOUT] Le modèle met du temps à répondre (premier chargement de ~24 GB). Réessaie dans 30 secondes."
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("cmd_%s(%q) échoué", cmd_type, query_text[:50])
        await interaction.followup.send(f"[WARN] Erreur : {exc}")
        return

    response_parts = _trunc_string(result.llm_response, settings.MAX_RESPONSE_LENGTH)
    for i, part in enumerate(response_parts):
        if i == 0:
            embed = _format_response(result)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(part)


@bot.tree.command(name="stats", description="Affiche les stats exactes d'un objet Zomboid")
@discord.app_commands.describe(item="Identifiant de l'objet (ex: Base.Axe, Item.WoodenCane)")
async def cmd_stats(interaction: discord.Interaction, item: str):
    """Commande /stats — lookup déterministe par ID."""
    await _run_llm_command(interaction, "stats", item)


@bot.tree.command(name="survie", description="Conseil de survie hardcore basé sur les données du jeu")
@discord.app_commands.describe(scenario="Scénario de survie")
async def cmd_survie(interaction: discord.Interaction, scenario: str):
    """Commande /survie — analyse de survie hardcore."""
    await _run_llm_command(interaction, "survie", scenario)


@bot.tree.command(name="recipe", description="Recherche de recettes d'artisanat")
@discord.app_commands.describe(ingredient="L'objet ou ingrédient recherché")
async def cmd_recipe(interaction: discord.Interaction, ingredient: str):
    """Commande /recipe — recherche de recettes."""
    await _run_llm_command(interaction, "recipe", ingredient)


@bot.tree.command(name="moddoc", description="Documentation technique modding Lua/Java")
@discord.app_commands.describe(api="L'API ou fonction recherchée (ex: IsoPlayer, crafting)")
async def cmd_moddoc(interaction: discord.Interaction, api: str):
    """Commande /moddoc — documentation modding."""
    await _run_llm_command(interaction, "moddoc", api)


@bot.tree.command(name="search", description="Recherche sémantique libre sur le knowledge engine")
async def cmd_search(interaction: discord.Interaction, query: str):
    """Commande /search — recherche libre."""
    await _run_llm_command(interaction, "search", query)


# ---------------------------------------------------------------------------
# Commande /modgen — generation de mods Project Zomboid
# ---------------------------------------------------------------------------

async def _handle_modgen_command(interaction: discord.Interaction, description: str):
    """Genere un mod a partir d'une description utilisateur."""
    await interaction.response.defer()

    try:
        from pathlib import Path as P
        from src.modgen import (
            ModGenerator,
            ModSpec,
            ModType,
            generate_mod_from_description,
        )

        # Parse la description en un type de mod + features structurees
        manifest = await asyncio.wait_for(
            generate_mod_from_description(
                description=description,
                mod_type="item",  # Defaut: on peut ameliorer avec LLM
                name=None,  # Auto-extrait depuis la description
                author=settings.DEFAULT_SYSTEM_PROMPT.split("Zomboid Knowledge Engine")[0].strip() if "Zomboid Knowledge Engine" in settings.DEFAULT_SYSTEM_PROMPT else "Zomboid Architect",
                output_dir=P(settings.MOD_OUTPUT_PATH) if hasattr(settings, "MOD_OUTPUT_PATH") and settings.MOD_OUTPUT_PATH else None,
            ),
            timeout=120.0,  # Peut prendre ~60s pour LLM + generation
        )

        # Retourne les infos du mod genere
        files_list = []
        for f in sorted(manifest.mod_root.rglob("*")):
            if f.is_file():
                rel = f.relative_to(manifest.output_path)
                files_list.append(f"  - {rel}")

        response_parts = _trunc_string(
            (f"**Mod genere avec succes !**\n\n"
             f"- **Nom** : `{manifest.name}`\n"
             f"- **ID** : `{manifest.id}`\n"
             f"- **Chemin** : `{manifest.output_path}`\n"
             f"- **Fichiers ecrits** : {manifest.file_count}\n\n"
             "**Fichiers du mod :**\n```" + "\n".join(files_list) + "```"),
            settings.MAX_RESPONSE_LENGTH,
        )
        for i, part in enumerate(response_parts):
            if i == 0:
                embed = discord.Embed(
                    title="Zomboid Architect — Mod genere",
                    description=part[:3800],
                    color=discord.Color.dark_green(),
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(part)

    except asyncio.TimeoutError:
        logger.exception("cmd_modgen(%q) timeout", description[:50])
        await interaction.followup.send(
            "⏳ Le generateur met du temps. Verifie les logs si le mod n'apparait pas dans `mods/`."
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cmd_modgen(%q) echoue", description[:50])
        await interaction.followup.send(f"[WARN] Erreur lors de la generation du mod : {exc}")


@bot.tree.command(name="modgen", description="Genere un mod Project Zomboid a partir d'une description")
@discord.app_commands.describe(
    description="Description haute-niveau du mod (ex: 'Ajouter une epée avec 45 degats')",
)
async def cmd_modgen(interaction: discord.Interaction, description: str):
    """Commande /modgen — generation d'un mod Zomboid via LLM + engine."""
    await _handle_modgen_command(interaction, description)


# ---------------------------------------------------------------------------
# Commande /modpublish — publication Steam Workshop
# ---------------------------------------------------------------------------

def _find_mod_dir(mod_name: str) -> Path | None:
    """Recherche un dossier de mod genere dans `mods/` par nom ou ID partiel.

    Parcourt tous les sous-dossiers de `mods/` et cherche une correspondance
    partielle (case-insensitive) sur le nom du mod ou son ID canonique.

    Args:
        mod_name: Nom ou partie de l'ID du mod a trouver.

    Returns:
        Path vers le dossier du mod, ou None si pas trouve.
    """
    mods_dir = _PROJECT_ROOT / "mods"
    if not mods_dir.is_dir():
        return None

    needle = mod_name.strip().lower()
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Correspondance sur le nom du dossier (ignore prefic "modgen_*_" de l'ID)
        folder_name = entry.name.lower()
        # Extraire le nom reel : enleve "modgen_<slug>_<uuid>" pour comparer le slug
        if folder_name.startswith("modgen_"):
            parts = folder_name.split("_", 2)
            if len(parts) >= 3:
                real_name = parts[1]
                if needle in real_name or needle in entry.name.lower():
                    logger.info("Mod trouve : %s", entry)
                    return entry.resolve()
        else:
            if needle in folder_name:
                logger.info("Mod trouve (par dossier brut) : %s", entry)
                return entry.resolve()

    # Fallback : chercher dans mod.info JSON (champ "name")
    for entry in sorted(mods_dir.iterdir()):
        if not entry.is_dir():
            continue
        mod_info = entry / "mod.info"
        if not mod_info.is_file():
            continue
        try:
            import json
            data = json.loads(mod_info.read_text(encoding="utf-8"))
            name_field = (data.get("name", "") or data.get("Title", "") or "").lower()
            if needle in name_field:
                logger.info("Mod trouve via mod.info : %s", entry)
                return entry.resolve()
        except Exception:
            continue

    logger.warning("Mod introuvable pour '%s' dans %s", mod_name, mods_dir)
    return None


def _extract_mod_metadata(mod_dir: Path) -> tuple[str, str, list[str]]:
    """Extrait title/description/tags depuis le dossier du mod.

    Args:
        mod_dir: Chemin vers le dossier du mod genere.

    Returns:
        Tuple (title, description, tags). Si impossible, retourne des valeurs par defaut.
    """
    # Essayer de lire mod.info (JSON)
    mod_info = mod_dir / "mod.info"
    if mod_info.is_file():
        try:
            import json
            data = json.loads(mod_info.read_text(encoding="utf-8"))
            title = data.get("name", data.get("Title", "")) or ""
            desc = data.get("description", "") or ""
            tags = [t for t in (data.get("tags", []) or []) if isinstance(t, str)]
            return title, desc, tags
        except Exception:
            pass

    # Fallback : lire ZomboidModDescriptor.txt
    descriptor = mod_dir / "ZomboidModDescriptor.txt"
    if descriptor.is_file():
        lines = descriptor.read_text(encoding="utf-8", errors="replace").splitlines()
        title = desc = ""
        tags: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("name="):
                title = stripped[5:].strip() or ""
            elif stripped.startswith("description="):
                desc = stripped[12:].strip() or ""
            elif stripped.startswith("tags="):
                tags = [t.strip() for t in stripped[5:].split(",") if t.strip()]
        if title:
            return title, desc, tags

    # Dernier fallback : utiliser le nom du dossier (sans prefic modgen)
    folder_name = mod_dir.name
    if folder_name.startswith("modgen_"):
        parts = folder_name.split("_", 2)
        folder_name = parts[1] if len(parts) >= 3 else folder_name
    return folder_name, "", []


async def _handle_modpublish_command(interaction: discord.Interaction, mod_name: str | None, folder_path: str | None):
    """Publie un mod vers le Steam Workshop via SteamCMD."""
    await interaction.response.defer()

    # 1. Resoudre le dossier du mod
    if folder_path:
        mod_dir = Path(folder_path)
    else:
        name_to_use = mod_name or ""
        mod_dir = _find_mod_dir(name_to_use)
        if not mod_dir:
            await interaction.followup.send(
                f"[WARN] Mod introuvable. Verifie que le mod a ete genere par `/modgen`.\n\n"
                f"Hint : utiliser `/modpublish <nom_du_mod>` ou `/modpublish folder_path:C:\\path\\to\\mod`"
            )
            return

    if not mod_dir.is_dir():
        await interaction.followup.send(f"[WARN] Dossier inexistant : `{mod_dir}`")
        return

    # 2. Valider que c'est un mod valide (contient mod.info)
    mod_info = mod_dir / "mod.info"
    if not mod_info.is_file():
        await interaction.followup.send(
            f"[WARN] `{mod_dir}` ne semble pas etre un mod valide (manque `mod.info`).\n"
            f"Genere d'abord le mod avec `/modgen`."
        )
        return

    # 3. Extraire metadata
    title, description, _tags = _extract_mod_metadata(mod_dir)

    # 4. Importer SteamCMDClient (lazy pour eviter dependance au demarrage)
    try:
        from ingestor.steam.steamcmd_client import SteamCMDClient
    except ImportError as exc:
        logger.exception("Import SteamCMDClient echoue")
        await interaction.followup.send(f"[WARN] Impossible de charger le client SteamCMD : {exc}")
        return

    client = SteamCMDClient()
    if not client.steamcmd_exe:
        await interaction.followup.send(
            "[WARN] steamcmd.exe introuvable.\n\n"
            "Installe-le dans `tools/steamcmd/` ou sur ton PATH.\n"
            "Telechargement : https://store.steampowered.com/About"
        )
        return

    # 5. Executer l'upload
    logger.info("Upload Workshop du mod : %s", mod_dir)
    result = await client.upload_workshop_item(
        folder_path=mod_dir,
        title=title or f"Zomboid Mod: {mod_dir.name}",
        description=description or f"Mod genere par Zomboid Architect.",
    )

    if result.success:
        # Essayer d'extraire le workshop item ID du resultat
        workshop_id = None
        for line in result.lines:
            if "workshop_item_id" in line.lower() or "Workshop Item ID" in line:
                import re
                match = re.search(r"(\d+)", line)
                if match:
                    workshop_id = match.group(1)
                    break

        url = f"https://steamcommunity.com/workshop/filedetails/?id={workshop_id}" if workshop_id else None
        emoji_ok = "[OK]" if result.success else "[WARN]"
        status = "Succes !" if result.success else "Termine (verifie l'output)"
        message = f"{emoji_ok} **{status}**\n\nDossier : `{mod_dir}`\n"
        if url:
            message += f"[Lien Workshop]({url})"
        await interaction.followup.send(message)
    else:
        error_msg = result.error or "Erreur inconnue"
        logger.warning("Upload Workshop echoue : %s", error_msg)
        # Montrer l'output steamcmd pour debugging (tronque si trop long)
        output_preview = result.output[:1500] if result.output else "(vide)"
        await interaction.followup.send(
            f"[FAIL] Upload Workshop echoue.\n\n"
            f"**Erreur** : {error_msg}\n\n"
            f"**Output SteamCMD** :\n```\n{output_preview}\n```"
        )


@bot.tree.command(name="modpublish", description="Publie un mod genere vers le Steam Workshop")
@discord.app_commands.describe(
    mod_name="Nom du mod a publier (ou partie de l'ID, recherché dans mods/)",
    folder_path="Chemin manuel au dossier du mod (optionnel — remplace mod_name)",
)
async def cmd_modpublish(interaction: discord.Interaction, mod_name: str | None = None, folder_path: str | None = None):
    """Commande /modpublish — publication d'un mod Zomboid vers le Steam Workshop."""
    # Au moins un argument doit etre fourni
    if not mod_name and not folder_path:
        await interaction.response.send_message(
            "[WARN] Fournis soit `mod_name` soit `folder_path`.\n\n"
            "Exemple : `/modpublish MonEpée` ou `/modpublish folder_path:C:\\path\\to\\mod`",
            ephemeral=True,
        )
        return

    await _handle_modpublish_command(interaction, mod_name, folder_path)


# ---------------------------------------------------------------------------
# Rapport workspace — génération du contenu
# ---------------------------------------------------------------------------

def _read_file_safe(path: Path) -> str | None:
    """Lit un fichier si existant, retourne None sinon."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _get_git_log(max_lines: int = 15) -> str:
    """Retourne les derniers commits (si accessible depuis le conteneur)."""
    try:
        # Docker compose peut avoir mounted le repo en volume
        result = subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), "log", "--oneline", "-n", str(max_lines)],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "[WARN] Git non accessible dans le conteneur (mount -v ?)"
    except FileNotFoundError:
        return "[WARN] Git non disponible — installe-le dans l'image Docker ou monte le volume"
    except subprocess.TimeoutExpired:
        return "[WARN] Timeout git log"
    except Exception as exc:  # noqa: BLE001
        return f"[WARN] Erreur git : {exc}"


def _parse_phase_progress(todo_path: Path) -> tuple[str, int, int]:
    """Parse todo.md et retourne (titre_phases, total_cases, cases_faites)."""
    content = _read_file_safe(todo_path)
    if not content:
        return "[WARN] TODO introuvable", 0, 0

    total = content.count("- [x]") + content.count("- [ ]") + content.count("[-]")
    done = content.count("- [x]")
    phases_text = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            phases_text.append(f"**{stripped[3:].strip()}**")
        elif stripped == "- [ ] Lancer le bot et tester dans Discord":
            # Décocher car on est en train de le faire
            continue

    return " | ".join(phases_text) if phases_text else "Aucune phase trouvée", done, total


def _generate_workspace_report() -> str:
    """Génère le rapport complet du workspace."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Version
    version_path = _PROJECT_ROOT / "VERSION"
    version_alt = _PROJECT_ROOT / ".." / "VERSION"
    version_text = _read_file_safe(version_path) or _read_file_safe(version_alt)
    version = version_text.strip() if version_text else "0.1.0-alpha (dev)"

    # TODO progress
    todo_path = _PROJECT_ROOT / "agent" / "todo.md"
    phases, done, total = _parse_phase_progress(todo_path)

    # Git log
    git_log = _get_git_log(12)

    # Ollama health
    ollama_status = "[WARN] Non teste"
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status == 200:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            ollama_status = f"[OK] En ligne — modeles : {', '.join(models[:5])}"
    except Exception:
        ollama_status = "[FAIL] Hors ligne ou injoignable"

    # Health du storage vectoriel (SQLite/PostgreSQL)
    storage_status = "[WARN] Non teste"
    try:
        from src.storage import StorageBackend
        health = StorageBackend().health()
        if health["available"]:
            storage_status = f"[OK] En ligne ({health['mode']}) — {health.get('db_path', '')}"
        else:
            storage_status = f"[FAIL] Indisponible ({health.get('error', 'inconnu')})"
    except Exception as exc:
        storage_status = f"[FAIL] Erreur : {exc}"

    # LLM provider
    llm_info = f"{llm.name} (local={llm.is_local})"

    report = f"""**[REPORT] Zomboid_Architect — Rapport Workspace**
*{now}*

━━━━━━━━━━━━━━━━━━━━━━

**[BUILD] Version** : `{version}`
**[LLM] LLM** : {llm_info}

**[STATS] Progression des phases** :
`{phases}`

**[OK] Termine** : {done}/{total} taches

**[TODO] Derniers commits** :
```
{git_log or "Aucun commit (dépôt vierge ou pas de git)"}
```

**[CONN] Services :**
- Ollama : {ollama_status}
- Storage (SQLite/PostgreSQL) : {storage_status}

**[CHANNEL] Canaux actifs :**
- Discord : `{bot.user.name}` en ligne [OK]
- Canal workspace : `{getattr(_workspace_target or _workspace_channel, 'name', '?')}` (ID: {getattr(_workspace_target or _workspace_channel, 'id', '?')})
"""
    return report


# ---------------------------------------------------------------------------
# Commande /workspace — envoi du rapport dans le canal workspace
# ---------------------------------------------------------------------------

@bot.tree.command(name="workspace", description="Envoie un rapport d'état du projet dans le canal workspace")
async def cmd_workspace(interaction: discord.Interaction):
    """Commande /workspace — envoie un rapport dans le canal workspace."""
    await interaction.response.defer()

    # Trouver le channel cible (workspace ou fallback)
    target_ch = globals().get("_workspace_target") or _workspace_channel
    if not target_ch:
        g = _find_guild()
        ch_names = [f"#{ch.name}" for ch in (g.text_channels if g else [])]
        await interaction.followup.send(
            "[WARN] Aucun canal workspace trouve. Configure `WORKSPACE_CHANNEL_ID=<ton_id>` dans `.env`.\n"
            f"Canaux : {', '.join(ch_names[:10])}",
            ephemeral=True,
        )
        return

    try:
        report = await asyncio.to_thread(_generate_workspace_report)
        await target_ch.send(report)
        logger.info("Rapport workspace envoyé dans #%s", target_ch.name)
        await interaction.followup.send(
            f"[REPORT] Rapport envoye dans `#{target_ch.name}` [OK]",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f"[FAIL] Pas la permission d'envoyer dans `#{target_ch.name}`.",
            ephemeral=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cmd_workspace failed")
        await interaction.followup.send(f"[WARN] Erreur : {exc}", ephemeral=True)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    """Synchronise les slash commands avec l'API Discord et trouve le canal workspace."""
    global _workspace_channel, _workspace_target

    logger.info("Bot connecté en tant que %s (ID: %d)", bot.user.name, bot.user.id)

    # Trouver le guild cible en premier (besoin pour sync guild-specific)
    target_guild = _find_guild()

    if target_guild:
        await bot.tree.sync(guild=target_guild)  # Sync guild-specific (immédiat < 1 min)
        logger.info("Slash commands synchronisés au guild (%d enregistrés)", len(bot.tree.get_commands()))
    else:
        await bot.tree.sync()  # Global sync fallback (peut prendre ~1h)
        logger.info("Slash commands synchronisés globalement (%d enregistrés)", len(bot.tree.get_commands()))

    # Trouver le canal workspace — la catégorie peut contenir plusieurs canaux
    guild = target_guild or _find_guild()
    if guild:
        target_cat_name = "[DESKTOP] WORKSPACE Z-ARCHITECT"

        # 1. Chercher d'abord la catégorie par son nom
        workspace_cat = None
        for cat in guild.categories:
            clean_cat = discord.utils.remove_markdown(cat.name).strip().lower()
            if target_cat_name.lower().replace("[DESKTOP] ", "").replace("[REPORT] ", "") in clean_cat.replace("[DESKTOP] ", "").replace("[REPORT] ", ""):
                workspace_cat = cat
                logger.info("Catégorie workspace trouvée : %s (canaux: %d)", cat.name, len(cat.text_channels))
                break

        if workspace_cat:
            # Lister tous les canaux de la catégorie pour info
            cat_channels = [f"#{ch.name}" for ch in workspace_cat.text_channels]
            logger.info("Catégorie workspace : %s → canaux : %s", workspace_cat.name, ", ".join(cat_channels))
            # Prendre le premier channel texte sous la catégorie comme target
            if workspace_cat.text_channels:
                _workspace_channel = workspace_cat.text_channels[0]
                logger.info("Canal workspace sélectionné : #%s (ID: %s)", _workspace_channel.name, _workspace_channel.id)
        else:
            # 2. Fallback : chercher par ID si configuré
            if settings.WORKSPACE_CHANNEL_ID:
                for guild_obj in bot.guilds:
                    ch = guild_obj.get_channel(settings.WORKSPACE_CHANNEL_ID)
                    if ch:
                        _workspace_channel = ch
                        logger.info("Canal workspace résolu par ID : #%s", ch.name)
                        break

            # 3. Fallback : chercher un canal avec "workspace" ou "z-architect" dans le nom
            if not _workspace_channel:
                for ch in guild.text_channels:
                    clean = discord.utils.remove_markdown(ch.name).strip().lower()
                    if "workspace" in clean or "z-architect" in clean or "z_architect" in clean:
                        _workspace_channel = ch
                        logger.info("Canal workspace (fallback) trouvé : #%s (ID: %s)", ch.name, ch.id)
                        break

    # Fallback ultime : rapport envoyé dans le premier channel visible si aucun workspace trouvé
    fallback_channel = None
    if not _workspace_channel and guild:
        for candidate in ["[STATS]・rapports", "[IDEA]・brainstorm", "[TODO]・tasks", "[CHAT]・general-dev"]:
            for ch in guild.text_channels:
                clean = discord.utils.remove_markdown(ch.name).strip().lower()
                if candidate.replace("・", "").replace("[STATS] ", "").replace("[IDEA] ", "").replace("[TODO] ", "").replace("[CHAT] ", "") in clean:
                    fallback_channel = ch
                    break
            if fallback_channel:
                break

    if not _workspace_channel and not fallback_channel:
        ch_names = [f"#{ch.name} (ID:{ch.id})" for ch in guild.text_channels] if guild else []
        cats_info = [f"{c.name} ({len(c.text_channels)} canaux)" for c in guild.categories[:10]]
        logger.warning(
            "Canal workspace non trouvé. Configure WORKSPACE_CHANNEL_ID dans le .env.\n"
            "Canaux disponibles : %s\nCatégories : %s", ", ".join(ch_names[:20]), ", ".join(cats_info),
        )

    # Stocker le channel à utiliser (workspace ou fallback)
    _workspace_target = _workspace_channel or fallback_channel


def _find_guild() -> discord.Guild | None:
    """Retourne le premier guild disponible."""
    if bot.guilds:
        return bot.guilds[0]
    return None


@bot.event
async def on_message(message: discord.Message):
    """Intercepte tous les messages et répond automatiquement."""
    # Ignore les messages du bot lui-même
    if message.author == bot.user:
        return

    # Ne répondre qu'aux DMs (pas aux channels publics pour éviter le spam)
    if not isinstance(message.channel, discord.DMChannel):
        return

    content = message.content.strip()
    if not content:
        await message.reply("Salut ! Je suis l'assistant Zomboid Knowledge Engine.")
        return

    logger.info("DM de %s : %s", message.author.name, content)

    try:
        result = await _wrap_llm(
            process_message(
                content,
                engine=engine, llm=llm,
                system_prompt=settings.DEFAULT_SYSTEM_PROMPT,
                game_version=_current_game_version,
            )
        )
    except asyncio.TimeoutError:
        logger.exception("process_message DM timeout")
        await message.reply("⏳ Le modèle met du temps à répondre. Réessaie dans 30 secondes.")
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("process_message DM échoué pour %s", message.author.name)
        await message.reply(f"[WARN] Erreur interne : {exc}")
        return

    # Découper la réponse si elle dépasse les limites Discord
    response_parts = _trunc_string(result.llm_response, settings.MAX_RESPONSE_LENGTH)
    for i, part in enumerate(response_parts):
        if i == 0:
            embed = _format_response(result)
            await message.reply(embed=embed)
        else:
            await message.reply(part)


# ---------------------------------------------------------------------------
# Démarrage
# ---------------------------------------------------------------------------

async def main():
    """Point d'entrée async du bot."""
    logger.info("Zomboid Knowledge Engine - Bot Discord v%s", "0.1.0-alpha")
    logger.info("LLM : %s (local=%s)", llm.name, llm.is_local)
    if claude:
        logger.info("Fallback Claude API : %s", settings.CLAUDE_MODEL)

    # Découvrir les collections du knowledge engine
    try:
        collections = await asyncio.wait_for(
            asyncio.to_thread(engine.discover_collections), timeout=5.0
        )
        logger.info("Collections engine : %s", ", ".join(collections))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossible de discover les collections : %s (fallback activé)", exc)

    await bot.start(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
