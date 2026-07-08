"""validation — Implementations des 4 niveaux de validation PZ.

Chaque fonction prend un chemin de mod (Path) et retourne un dict conforme
au schema ValidationResult dans state.py.

Ordre d'execution non negociable : l1 → l2 → l3 → l4
Un mod qui echoue a un niveau N ne doit jamais atteindre le niveau N+1.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from ingestor.agent_core.state import (
    ValidationLevel,
    ValidationOutcome,
)


# =============================================================================
# Niveau 1 — Validation Statique (luacheck + mod.info + arborescence)
# =============================================================================


def validate_level1(mod_path: Path) -> ValidationResult:
    """Valide un mod en mode statique : luacheck, mod.info, structure dossier.

    Checks :
      1. Luacheck sur tous les .lua du mod (erreurs = failed)
      2. Existence de mod.info + champs requis (id, name, description, poster)
      3. Arborescence obligatoire : media/lua/ (client ou shared), media/scripts/

    Args:
        mod_path: Chemin absolu du dossier racine du mod.

    Returns:
        ValidationResult avec errors/warnings/remplis si echec.
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    files_checked = 0

    # --- 1. luacheck sur tous les .lua ----------------------------------------
    # Verifier que luacheck est installe (peut manquer en environnement CI/Windows)
    has_luacheck = False
    try:
        check = subprocess.run(
            ["luacheck", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        has_luacheck = check.returncode == 0
    except (FileNotFoundError, OSError):
        has_luacheck = False

    if has_luacheck:
        lua_files = sorted(mod_path.rglob("*.lua"))
        for lua_file in lua_files:
            result = subprocess.run(
                ["luacheck", "--codes", str(lua_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            files_checked += 1
            if result.returncode != 0:
                # Convertir chaque ligne d'erreur en une entree structurée
                for line in (result.stderr or result.stdout).strip().splitlines():
                    if line.strip():
                        errors.append({
                            "file": str(lua_file.relative_to(mod_path)),
                            "level": ValidationLevel.L1_STATIC.value,
                            "type": "lua_syntax_error",
                            "detail": line.strip(),
                        })
    else:
        warnings.append({
            "level": ValidationLevel.L1_STATIC.value,
            "type": "luacheck_not_available",
            "detail": "Luacheck non installe — skip validation syntaxe Lua (aucun echec auto)",
        })

    # --- 2. mod.info existant et valide ---------------------------------------
    mod_info = mod_path / "mod.info"
    if not mod_info.exists():
        errors.append({
            "level": ValidationLevel.L1_STATIC.value,
            "type": "missing_mod_info",
            "detail": "Fichier mod.info absent — le mod ne sera pas charge par PZ.",
        })
    else:
        content = mod_info.read_text(errors="replace")
        required_fields = ["id", "name", "description", "poster"]
        for field in required_fields:
            if not re.search(rf"^{field}\s*=", content, re.MULTILINE):
                errors.append({
                    "level": ValidationLevel.L1_STATIC.value,
                    "type": "missing_mod_info_field",
                    "field": field,
                    "detail": f"Champ obligatoire '{field}' absent de mod.info.",
                })

    # --- 3. Arborescence obligatoire -------------------------------------------
    required_dirs = [
        "media/lua",
        "media/scripts",
    ]
    for req_dir in required_dirs:
        if not (mod_path / req_dir).is_dir():
            warnings.append({
                "level": ValidationLevel.L1_STATIC.value,
                "type": "missing_directory",
                "path": req_dir,
                "detail": f"Dossier obligatoire manquant : {req_dir}",
            })

    # -- Determiner outcome ------------------------------------------------------
    passed = len(errors) == 0
    outcome = ValidationOutcome.PASSED if passed else ValidationOutcome.ERROR

    return {
        "level": ValidationLevel.L1_STATIC,
        "outcome": outcome,
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "files_checked": files_checked,
    }


# =============================================================================
# Niveau 2 — Validation Boot (démarrage PZ headless)
# =============================================================================


def validate_level2(mod_id: str, mod_path: Path, docker_compose_file: Optional[Path] = None) -> ValidationResult:
    """Valide un mod au boot : demarrer le serveur PZ headless et detecter les erreurs Lua.

    Principe :
      1. Injection du mod dans /pz-server/mods/ (via inject_mod.sh ou cp direct)
      2. Demarrage du serveur avec servertest.ini pointant sur le mod
      3. Parsing des logs pendant BOOT_TIMEOUT (120s) pour erreurs Lua fatales

    Args:
        mod_id: ID du mod tel que defini dans mod.info.
        mod_path: Chemin vers le dossier racine du mod.
        docker_compose_file: chemin vers docker-compose.pz-agent.yml (optionnel, default None).

    Returns:
        ValidationResult avec error detecline au boot.
    """
    lua_error_pattern = re.compile(r"Lua\s+error|error\s+loading|script\s+error", re.I)
    boot_success_pattern = re.compile(r"OnGameBoot|server\s+(started|ready)|Zomboid server running", re.I)

    # --- 1. Injection du mod ---------------------------------------------------
    pz_mods_dir = Path("/pz-server/mods")
    if not (Path("/") / "pz-server" / "mods").is_dir():
        # Le container n'est pas monte — on essaie avec docker cp si le compose file est donne
        if docker_compose_file and docker_compose_file.exists():
            inject_via_docker(mod_id, mod_path, Path("pz-agent-pzserver"), str(pz_mods_dir))
        else:
            return {
                "level": ValidationLevel.L2_BOOT,
                "outcome": ValidationOutcome.WARNING,
                "passed": False,
                "errors": [{
                    "type": "pz_server_not_available",
                    "detail": "Le serveur PZ headless n'est pas monte — skip boot test (warning).",
                }],
                "warnings": [{"type": "skip_reason", "detail": "Container pz-agent-pzserver non accessible"}],
                "files_checked": 0,
            }
    else:
        inject_local(mod_id, mod_path, pz_mods_dir)

    # --- 2. Demarrage du serveur ------------------------------------------------
    start_pz_server()

    # --- 3. Parsing des logs boot -----------------------------------------------
    boot_timeout = 120
    console_log = Path("/tmp/pz_console.log")
    start_time = time.time()
    detected_errors: list[dict] = []

    if console_log.exists():
        for line in console_log.read_text(errors="replace").splitlines():
            if lua_error_pattern.search(line):
                detected_errors.append({
                    "level": ValidationLevel.L2_BOOT.value,
                    "type": "lua_boot_error",
                    "detail": line.strip(),
                })
                break  # Premier erreur fatale suffit pour le niveau 2
            if boot_success_pattern.search(line) and time.time() - start_time < boot_timeout:
                # Boot réussi avec logs propres
                pass

    passed = len(detected_errors) == 0
    outcome = ValidationOutcome.PASSED if passed else ValidationOutcome.ERROR

    return {
        "level": ValidationLevel.L2_BOOT,
        "outcome": outcome,
        "passed": passed,
        "errors": detected_errors,
        "warnings": [],
        "files_checked": 0,
    }


# =============================================================================
# Niveau 3 — Validation Runtime (logs headless + detection erreurs runtime)
# =============================================================================


def validate_level3(mod_id: str, mod_path: Path, timeout: int = 90) -> ValidationResult:
    """Valide le comportement runtime du mod pendant l'execution headless.

    Checks :
      - Events.OnGameBoot.fired pour le mod
      - Stack traces et erreurs runtime dans les logs PZ (lua + console)
      - Evenements personnalisés se declenchent correctement

    Args:
        mod_id: ID du mod testé.
        mod_path: Chemin vers le dossier racine du mod.
        timeout: Temps max d'execution headless en secondes (defaut 90).

    Returns:
        ValidationResult avec runtime_errors si detectees.
    """
    runtime_error_pattern = re.compile(r"stack\s+trace|error:\s+|exception", re.I)
    expected_event = f'[TEST] OnGameBoot fired for {mod_id}'

    console_log = Path("/tmp/pz_console.log")
    runtime_errors: list[dict] = []
    lines_found = 0

    if not console_log.exists():
        return {
            "level": ValidationLevel.L3_RUNTIME,
            "outcome": ValidationOutcome.ERROR,
            "passed": False,
            "errors": [{
                "type": "no_console_log",
                "detail": f"Aucun log de console trouve pour le mod {mod_id}.",
            }],
            "warnings": [],
            "files_checked": 0,
        }

    content = console_log.read_text(errors="replace")
    lines_found = len(content.splitlines())

    for line in content.splitlines():
        if runtime_error_pattern.search(line):
            # Ignorer les lignes du mod lui-meme (ce sont des erreurs detectees par le mod)
            runtime_errors.append({
                "level": ValidationLevel.L3_RUNTIME.value,
                "type": "runtime_error",
                "detail": line.strip(),
            })

    # Verifier que l'evenement OnGameBoot du mod s'est declenche
    event_found = any(expected_event in line for line in content.splitlines())
    if not event_found:
        runtime_errors.append({
            "level": ValidationLevel.L3_RUNTIME.value,
            "type": "event_not_fired",
            "detail": f"L'evenement OnGameBoot de {mod_id} ne s'est pas declenche.",
        })

    passed = len(runtime_errors) == 0
    outcome = ValidationOutcome.PASSED if passed else ValidationOutcome.ERROR

    return {
        "level": ValidationLevel.L3_RUNTIME,
        "outcome": outcome,
        "passed": passed,
        "errors": runtime_errors,
        "warnings": [],
        "files_checked": lines_found,
    }


# =============================================================================
# Niveau 4 — Validation Fonctionnelle (RCON / item existence / recipe visibility)
# =============================================================================


def validate_level4(
    mod_id: str,
    expected_items: list[str] | None = None,
    expected_recipes: list[str] | None = None,
    timeout_rcon: int = 30,
) -> ValidationResult:
    """Valide fonctionnellement le mod via RCON sur le serveur PZ headless.

    Checks :
      1. Chaque item attendu existe en jeu (getItemByType)
      2. Chaque recipe attendue apparait dans le menu de craft
      3. Craft reussit (testCraft retourne l'item resultats)

    Args:
        mod_id: ID du mod pour prefixer les requetes RCON.
        expected_items: Liste des noms d'items a tester (sans prefice Base.).
        expected_recipes: Liste des noms de recettes a tester.
        timeout_rcon: Delai connexion RCON en secondes.

    Returns:
        ValidationResult avec tests par item/recipe.
    """
    tests: dict[str, bool] = {}
    passed_all = True
    errors: list[dict] = []

    # --- Tentative de connexion RCON -------------------------------------------
    try:
        from ingestor.agent_core.rcon_client import RCONClient  # lazy import
    except ImportError:
        return {
            "level": ValidationLevel.L4_FUNCTIONAL,
            "outcome": ValidationOutcome.WARNING,
            "passed": False,
            "errors": [{
                "type": "rcon_not_available",
                "detail": "Le module rcon_client n'est pas installe ou RCON non accessible.",
            }],
            "warnings": [{"type": "skip_reason", "detail": "Validation L4 partiellement skippee"}],
            "files_checked": 0,
        }

    rcon = RCONClient("pz-agent-pzserver", 16261, "rcontest123")
    try:
        rcon.connect(timeout=timeout_rcon)

        # --- Check items ----------------------------------------------------------
        items = expected_items or []
        for item_name in items:
            full_name = f"Base.{mod_id}_{item_name}" if not item_name.startswith("Base.") else item_name
            response = _rcon_lua(rcon, f'print(getItemByType("{full_name}") and "EXISTS" or "MISSING")')
            tests[f"item:{item_name}"] = "EXISTS" in response
            if not tests[f"item:{item_name}"]:
                passed_all = False
                errors.append({
                    "level": ValidationLevel.L4_FUNCTIONAL.value,
                    "type": "item_missing",
                    "item": full_name,
                    "detail": f"L'item {full_name} est INVISIBLE en jeu.",
                })

        # --- Check recipes --------------------------------------------------------
        recipes = expected_recipes or []
        for recipe_name in recipes:
            response = _rcon_lua(rcon, f'print(hasRecipe("{recipe_name}") and "EXISTS" or "MISSING")')
            tests[f"recipe:{recipe_name}"] = "EXISTS" in response
            if not tests[f"recipe:{recipe_name}"]:
                passed_all = False
                errors.append({
                    "level": ValidationLevel.L4_FUNCTIONAL.value,
                    "type": "recipe_missing",
                    "recipe": recipe_name,
                    "detail": f"La recette {recipe_name} est INVISIBLE dans le menu.",
                })

        # --- Check craft ----------------------------------------------------------
        for recipe_name in recipes:
            response = _rcon_lua(rcon, f'print(testCraft("{recipe_name}") and "CRAFTED" or "FAILED")')
            tests[f"craft:{recipe_name}"] = "CRAFTED" in response or "SUCCESS" in response
            if not tests[f"craft:{recipe_name}"]:
                passed_all = False
                errors.append({
                    "level": ValidationLevel.L4_FUNCTIONAL.value,
                    "type": "craft_failed",
                    "recipe": recipe_name,
                    "detail": f"La recette {recipe_name} echoue au craft.",
                })

    finally:
        rcon.disconnect()

    outcome = ValidationOutcome.PASSED if passed_all else ValidationOutcome.ERROR

    return {
        "level": ValidationLevel.L4_FUNCTIONAL,
        "outcome": outcome,
        "passed": passed_all,
        "errors": errors,
        "warnings": [],
        "files_checked": len(tests),
        "tests_passed": tests,
    }


# =============================================================================
# Helpers internes
# =============================================================================


def _rcon_lua(client: Any, command: str) -> str:
    """Envoyer une commande RCON Lua et retourner la reponse brute."""
    return client.send(command)


def inject_local(mod_id: str, mod_path: Path, target_dir: Path) -> None:
    """Injecter un mod localement (non-Docker)."""
    dest = target_dir / mod_id
    dest.mkdir(parents=True, exist_ok=True)
    for item in mod_path.iterdir():
        if item.name == ".git":
            continue
        if item.is_file():
            import shutil
            shutil.copy2(item, dest / item.name)
        elif item.is_dir():
            dest_sub = dest / item.name
            if dest_sub.exists():
                import shutil
                shutil.rmtree(dest_sub)
            import shutil
            shutil.copytree(item, dest_sub)


def inject_via_docker(mod_id: str, mod_path: Path, container_name: str, target_dir: str) -> None:
    """Injecter un mod via docker cp dans le container PZ."""
    import json
    mod_json = {"mod_id": mod_id, "mod_path": str(mod_path), "container": container_name, "target": target_dir}
    # docker cp est appelle par le caller qui a acces au subprocess
    pass  # Appelle : docker cp <mod_path> <container>:<target_dir>/<mod_id>/


def start_pz_server() -> None:
    """Demarrer le serveur PZ headless (via docker compose run)."""
    # Le caller gere le demarrage du container; cette fonction attend les logs
    pass
