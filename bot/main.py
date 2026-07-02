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
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands

# ---------------------------------------------------------------------------
# Logging (format JSON pour ingestion machine)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bot")

# ---------------------------------------------------------------------------
# Initialisation du bot
# ---------------------------------------------------------------------------

from .config import load_settings  # noqa: E402
from .engine_client import KnowledgeEngineClient  # noqa: E402
from .llm_adapter import create_providers, LLMProvider  # noqa: E402
from .pipeline import process_message  # noqa: E402

settings = load_settings()
if not settings.DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN est vide. Copie .env.example → .env et configure-le.")
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
engine = KnowledgeEngineClient(settings.CHROMA_HOST)
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
        "/search <query> — Recherche sémantique libre\n\n"
        "**DM** — Envoie-moi un message en DM, je réponds automatiquement !"
    )

    embed = discord.Embed(
        title="Zomboid Knowledge Engine",
        description=help_text,
        color=discord.Color.dark_green(),
    )
    embed.set_footer(text="Propulsé par Ollama local + ChromaDB")
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
            )
        )
    except asyncio.TimeoutError:
        logger.exception("cmd_%s(%q) timeout après %.0fs", cmd_type, query_text[:50], LLM_TIMEOUT)
        await interaction.followup.send(
            "⏳ Le modèle met du temps à répondre (premier chargement de ~24 GB). Réessaie dans 30 secondes."
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("cmd_%s(%q) échoué", cmd_type, query_text[:50])
        await interaction.followup.send(f"⚠️ Erreur : {exc}")
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
        return result.stdout.strip() or "⚠️ Git non accessible dans le conteneur (mount -v ?)"
    except FileNotFoundError:
        return "⚠️ Git non disponible — installe-le dans l'image Docker ou monte le volume"
    except subprocess.TimeoutExpired:
        return "⚠️ Timeout git log"
    except Exception as exc:  # noqa: BLE001
        return f"⚠️ Erreur git : {exc}"


def _parse_phase_progress(todo_path: Path) -> tuple[str, int, int]:
    """Parse todo.md et retourne (titre_phases, total_cases, cases_faites)."""
    content = _read_file_safe(todo_path)
    if not content:
        return "⚠️ TODO introuvable", 0, 0

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
    ollama_status = "⚠️ Non testé"
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status == 200:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            ollama_status = f"✅ En ligne — modèles : {', '.join(models[:5])}"
    except Exception:
        ollama_status = "❌ Hors ligne ou injoignable"

    # ChromaDB health
    chroma_status = "⚠️ Non testé"
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{settings.CHROMA_HOST}/api/v2/heartbeat", timeout=5)
        if resp.status == 200:
            chroma_status = f"✅ En ligne (v{resp.read().decode()[:10]})"
    except Exception:
        try:
            resp = urllib.request.urlopen(f"{settings.CHROMA_HOST}/api/v2", timeout=5)
            chroma_status = "✅ En ligne" if resp.status == 200 else f"❌ HTTP {resp.status}"
        except Exception:
            chroma_status = "❌ Hors ligne ou injoignable"

    # LLM provider
    llm_info = f"{llm.name} (local={llm.is_local})"

    report = f"""**📋 Zomboid_Architect — Rapport Workspace**
*{now}*

━━━━━━━━━━━━━━━━━━━━━━

**🏗️ Version** : `{version}`
**🤖 LLM** : {llm_info}

**📊 Progression des phases** :
`{phases}`

**✅ Terminé** : {done}/{total} tâches

**📝 Derniers commits** :
```
{git_log or "Aucun commit (dépôt vierge ou pas de git)"}
```

**🔌 Services :**
- Ollama : {ollama_status}
- ChromaDB : {chroma_status}

**📌 Canaux actifs :**
- Discord : `{bot.user.name}` en ligne ✅
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
            "⚠️ Aucun canal workspace trouvé.\nConfigure `WORKSPACE_CHANNEL_ID=<ton_id>` dans `.env`.\n"
            f"Canaux : {', '.join(ch_names[:10])}",
            ephemeral=True,
        )
        return

    try:
        report = _generate_workspace_report()
        await target_ch.send(report)
        logger.info("Rapport workspace envoyé dans #%s", target_ch.name)
        await interaction.followup.send(
            f"📋 Rapport envoyé dans `#{target_ch.name}` ✅",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f"❌ Pas la permission d'envoyer dans `#{target_ch.name}`.",
            ephemeral=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cmd_workspace failed")
        await interaction.followup.send(f"⚠️ Erreur : {exc}", ephemeral=True)


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
        target_cat_name = "💻 WORKSPACE Z-ARCHITECT"

        # 1. Chercher d'abord la catégorie par son nom
        workspace_cat = None
        for cat in guild.categories:
            clean_cat = discord.utils.remove_markdown(cat.name).strip().lower()
            if target_cat_name.lower().replace("💻 ", "").replace("📋 ", "") in clean_cat.replace("💻 ", "").replace("📋 ", ""):
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
        for candidate in ["📊・rapports", "🧠・brainstorm", "📝・tasks", "💬・général-dev"]:
            for ch in guild.text_channels:
                clean = discord.utils.remove_markdown(ch.name).strip().lower()
                if candidate.replace("・", "").replace("📊 ", "").replace("🧠 ", "").replace("📝 ", "").replace("💬 ", "") in clean:
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
            )
        )
    except asyncio.TimeoutError:
        logger.exception("process_message DM timeout")
        await message.reply("⏳ Le modèle met du temps à répondre. Réessaie dans 30 secondes.")
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("process_message DM échoué pour %s", message.author.name)
        await message.reply(f"⚠️ Erreur interne : {exc}")
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
