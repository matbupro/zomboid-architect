"""nodes — Implémentation des 6 noeuds de la boucle agentique LangGraph.

Chaque node est une fonction stand-alone qui :
  1. Lit l'etat d'entree (ModAgentState)
  2. Execute sa logique specifique
  3. Retourne un dict partiel a fusionner dans l'etat global

Les nodes :
  planning_node   — Analyse la demande, consulte KB, genere un plan
  building_node   — Genere les fichiers du mod selon le plan
  validating_node — Lance les validations niveau 1→4 en sequence
  fixing_node     — Analyse les erreurs et applique des corrections
  packaging_node  — Assemble le ZIP, commit Gitea, upload MinIO
  escalation_node — Marque le run comme necessitant une intervention humaine
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from src.governance.logger import get_logger

from ingestor.agent_core.state import (
    AgentStatus,
    BuildTarget,
    GovernanceTier,
    ModAgentState,
    ValidationLevel,
    ValidationOutcome,
)
from ingestor.agent_core.validation import (
    validate_level1,
    validate_level2,
    validate_level3,
    validate_level4,
)

logger = get_logger("agent_core")


# =============================================================================
# Nodes helpers
# =============================================================================


def _init_state(user_request: str, build_target: str = "build42", project_id: Optional[str] = None) -> ModAgentState:
    """Creer un ModAgentState initialise pour un nouveau run.

    Args:
        user_request: Demande brute de l'utilisateur.
        build_target: "build41" | "build42" | "both".
        project_id: UUID du mod_projects (optionnel).

    Returns:
        Etat initial avec status=PLANNING.
    """
    import uuid

    return ModAgentState(
        run_id=str(uuid.uuid4()),
        project_id=project_id,
        user_request=user_request,
        build_target=BuildTarget(build_target),
        max_retries=5,
        retry_count=0,
        status=AgentStatus.PLANNING,
        plan=None,
        context_chunks=[],
        generated_files={},
        mod_root=None,
        validation_results=[],
        errors=[],
        warnings=[],
        fix_attempts=[],
        artifact_id=None,
        artifact_path=None,
        commit_sha=None,
        minio_url=None,
        governance_tier=GovernanceTier.GREEN,
        needs_human_approval=False,
        report=None,
    )


# =============================================================================
# Node 1 — PLANNING
# =============================================================================


def planning_node(state: ModAgentState) -> dict[str, Any]:
    """Analyse la demande utilisateur et genere un plan d'action.

    Etapes :
      1. Parser la demande (nom du mod, type, features principales)
      2. Interroger Qdrant pour contexte semantique sur des demandes similaires
      3. Interroger PostgreSQL pour les projets existants et dependances
      4. Generer un plan structuré : fichiers a creer, templates a utiliser

    Args:
        state: Etat d'entree (avec user_request au minimum).

    Returns:
        Dict partiel avec plan, context_chunks, status=BUILDING.
    """
    logger.info("planning_node — debut pour run %s", state.get("run_id"))

    request = state.get("user_request", "")
    build_target = str(state.get("build_target", "build42"))

    # TODO: requête Qdrant pour contexte semantique (similar requests)
    context_chunks: list[dict] = []

    # TODO: requête PG pour projets existants avec le meme mod_id / nom
    # SELECT * FROM mod_projects WHERE name ILIKE %s LIMIT 5;

    plan: dict[str, Any] = {
        "mod_type": _extract_mod_type(request),
        "mod_name": _extract_mod_name(request),
        "has_new_recipes": False,
        "has_modified_items": False,
        "files_to_generate": [],
        "build_target": build_target,
    }

    logger.info("planning_node — plan genere : %s", json.dumps(plan, ensure_ascii=False))

    return {
        "plan": plan,
        "context_chunks": context_chunks,
        "status": AgentStatus.BUILDING,
    }


# =============================================================================
# Node 2 — BUILDING
# =============================================================================


def building_node(state: ModAgentState) -> dict[str, Any]:
    """Genere les fichiers du mod selon le plan.

    Pour chaque fichier du plan :
      1. Charger un template (mod.info, items.txt, recipes.txt, .lua…)
      2. Remplir avec les donnees du plan + contexte KB
      3. Ecrire dans workspace/{run_id}/

    Args:
        state: Etat avec plan et user_request.

    Returns:
        Dict partiel avec generated_files, mod_root, status=VALIDATING.
    """
    plan = state.get("plan") or {}
    run_id = state.get("run_id", "unknown")

    # TODO: utiliser src.modgen.generator.ModGenerator pour generer le mod
    # C'est l'equivalent de la section ETAPE 2 du pseudocode du doc
    from src.modgen.generator import ModGenerator, ModSpec
    from src.modgen.schema import ModType

    spec = ModSpec(
        name=plan.get("mod_name", "GeneratedMod"),
        description=state.get("user_request", ""),
        mod_type=ModType(plan.get("mod_type", "feature")),
        author="Zomboid Architect",
    )

    generator = ModGenerator()
    # NOTE: require asyncio pour le generate asynchrone
    import asyncio

    manifest = asyncio.run(generator.generate(spec))

    # Collecter tous les fichiers generes
    generated_files: dict[str, str] = {}
    mod_root_str = str(manifest.output_path)
    for file_item in manifest.spec.files:
        full_path = Path(manifest.output_path) / file_item.relative_path
        if full_path.exists():
            generated_files[file_item.relative_path] = full_path.read_text(errors="replace")

    return {
        "generated_files": generated_files,
        "mod_root": mod_root_str,
        "status": AgentStatus.VALIDATING,
        "governance_tier": GovernanceTier.GREEN,
    }


# =============================================================================
# Node 3 — VALIDATING (lance les 4 niveaux en sequence)
# =============================================================================


def validating_node(state: ModAgentState) -> dict[str, Any]:
    """Execute la chaine de validation niveau 1 → 2 → 3 → 4.

    Chaque niveau est appele dans l'ordre. Si un niveau echoue avec errors > 0 :
      - Le resultat est ajoute a validation_results
      - Les erreurs sont collectees dans state.errors
      - La chaine s'arrete (les niveaux superieurs ne s'executent pas)

    Args:
        state: Etat courant du run.

    Returns:
        Dict partiel avec validation_results, errors/warnings, status=FIXING si erreurs.
    """
    mod_root = state.get("mod_root")
    if not mod_root:
        return {
            "status": AgentStatus.FAILED,
            "errors": [{"type": "no_mod_root", "detail": "Aucun mod_root defini — impossible de valider."}],
        }

    mod_path = Path(mod_root)
    validation_results: list[dict] = []
    all_errors: list[dict] = []
    all_warnings: list[dict] = []
    errors_found_at_level = False

    # --- Niveau 1 : Statique ----------------------------------------------------
    logger.info("validating_node — L1 statique pour %s", mod_root)
    result_l1 = validate_level1(mod_path)
    validation_results.append(result_l1)
    if not result_l1.get("passed", True):
        all_errors.extend(result_l1.get("errors", []))
        all_warnings.extend(result_l1.get("warnings", []))
        errors_found_at_level = True

    # --- Niveau 2 : Boot (si L1 passe) ------------------------------------------
    if not errors_found_at_level:
        logger.info("validating_node — L2 boot pour %s", mod_root)
        result_l2 = validate_level2(
            mod_id=state.get("plan", {}).get("mod_name", "unknown"),
            mod_path=mod_path,
        )
        validation_results.append(result_l2)
        if not result_l2.get("passed", True):
            all_errors.extend(result_l2.get("errors", []))
            errors_found_at_level = True

    # --- Niveau 3 : Runtime (si L1+L2 passes) -----------------------------------
    if not errors_found_at_level:
        logger.info("validating_node — L3 runtime pour %s", mod_root)
        result_l3 = validate_level3(
            mod_id=state.get("plan", {}).get("mod_name", "unknown"),
            mod_path=mod_path,
        )
        validation_results.append(result_l3)
        if not result_l3.get("passed", True):
            all_errors.extend(result_l3.get("errors", []))
            errors_found_at_level = True

    # --- Niveau 4 : Fonctionnel (si L1+L2+L3 passes) ---------------------------
    plan = state.get("plan") or {}
    if not errors_found_at_level:
        logger.info("validating_node — L4 functional pour %s", mod_root)
        expected_items = plan.get("expected_items", [])
        expected_recipes = plan.get("expected_recipes", [])
        result_l4 = validate_level4(
            mod_id=state.get("plan", {}).get("mod_name", "unknown"),
            expected_items=expected_items or None,
            expected_recipes=expected_recipes or None,
        )
        validation_results.append(result_l4)
        if not result_l4.get("passed", True):
            all_errors.extend(result_l4.get("errors", []))
            errors_found_at_level = True

    # -- Determiner le next status -----------------------------------------------
    needs_fix = errors_found_at_level or any(not vr.get("passed", True) for vr in validation_results)
    new_tier = _compute_tier_after_validation(all_errors, all_warnings, state)

    if needs_fix:
        return {
            "validation_results": validation_results,
            "errors": all_errors,
            "warnings": all_warnings,
            "status": AgentStatus.FIXING,
            "governance_tier": new_tier,
        }

    # Tous les niveaux passes → passer au packaging
    return {
        "validation_results": validation_results,
        "errors": [],
        "warnings": all_warnings,
        "status": AgentStatus.PACKAGING,
        "governance_tier": GovernanceTier.GREEN,
    }


# =============================================================================
# Node 4 — FIXING (analyse et corrige les erreurs)
# =============================================================================


def fixing_node(state: ModAgentState) -> dict[str, Any]:
    """Analyse les erreurs de validation et applique des corrections.

    Pour chaque erreur :
      1. Identifier le type d'erreur (syntaxe, missing field, arborescence…)
      2. Appliquer une correction automatique si possible
      3. Enregistrer la correction dans fix_attempts
      4. Incremente retry_count

    Si should_escalate() est True → status=ESCALATED.
    Sinon → status=VALIDATING (renvoie a validating_node).

    Args:
        state: Etat courant avec errors et fix_attempts.

    Returns:
        Dict partiel avec updated files, incremented retry_count, next status.
    """
    import uuid

    errors = state.get("errors", []) or []
    if not errors:
        # Aucune erreur = retour direct au validating (loop sans fin prevener)
        return {"status": AgentStatus.VALIDATING}

    max_retries = state.get("max_retries", 5)
    new_fix_number = len(state.get("fix_attempts", []) or []) + 1

    fix_description_parts: list[str] = []
    modified_files: list[str] = []

    for error in errors:
        error_type = error.get("type", "")

        if error_type == "lua_syntax_error":
            fix_description_parts.append(f"Correction erreur syntaxe Lua : {error.get('detail', '')}")
            # TODO: utiliser LLM pour generer le code corrige
            modified_files.append(error.get("file", "<unknown>"))

        elif error_type == "missing_mod_info_field":
            field = error.get("field", "?")
            fix_description_parts.append(f"Ajout champ obligatoire '{field}' dans mod.info.")
            modified_files.append("mod.info")

        elif error_type == "lua_boot_error":
            fix_description_parts.append(f"Erreur au boot : {error.get('detail', '')}")
            # TODO: analyser la stack trace pour identifier le fichier fautif

        else:
            fix_description_parts.append(f"Erreur inconnue type '{error_type}' — requires manual review")

    fix_attempt = {
        "fix_number": new_fix_number,
        "error_types": [e.get("type", "") for e in errors],
        "fix_description": "\n".join(fix_description_parts),
        "files_modified": modified_files,
    }

    # Enregistrer la tentative de correction
    all_fixes = list(state.get("fix_attempts", []) or [])
    all_fixes.append(fix_attempt)

    new_retry_count = state.get("retry_count", 0) + 1

    return {
        "fix_attempts": all_fixes,
        "retry_count": new_retry_count,
        "errors": errors,  # Conserver les erreurs pour re-validation
        "status": AgentStatus.VALIDATING,
    }


# =============================================================================
# Node 5 — PACKAGING (ZIP + Gitea commit + MinIO upload)
# =============================================================================


def packaging_node(state: ModAgentState) -> dict[str, Any]:
    """Assemble le mod final : ZIP, commit Gitea, upload MinIO.

    Etapes :
      1. Determiner governance_tier (GREEN/ORANGE/RED)
      2. Creer archive .zip du mod
      3. Upload vers MinIO
      4. Commit + push sur Gitea
      5. Generer rapport de validation

    Args:
        state: Etat courant avec validation_results et mod_root.

    Returns:
        Dict partiel avec artifact info, status=DONE.
    """
    import shutil
    import zipfile
    from pathlib import Path

    mod_root = state.get("mod_root")
    if not mod_root:
        return {
            "status": AgentStatus.FAILED,
            "errors": [{"type": "no_mod_root", "detail": "Aucun mod_root — packaging impossible."}],
        }

    # -- Tier determination ------------------------------------------------------
    tier = state.get("governance_tier") or GovernanceTier.GREEN
    needs_approval = _requires_human(tier)
    if needs_approval and not state.get("needs_human_approval"):
        state["needs_human_approval"] = True

    if needs_approval:
        return {
            "status": AgentStatus.ESCALATED,
            "governance_tier": tier,
            "errors": [{"type": "requires_human_approval", "detail": f"Tier {tier.value} — approbation humaine obligatoire avant publication."}],
        }

    # -- Creer ZIP ---------------------------------------------------------------
    mod_path = Path(mod_root)
    zip_dir = mod_path.parent / "artifacts"
    zip_dir.mkdir(parents=True, exist_ok=True)

    run_id = state.get("run_id", "unknown")
    plan = state.get("plan") or {}
    mod_name = plan.get("mod_name", "Mod")
    zip_filename = f"{mod_name}_{run_id[:8]}.zip"
    zip_path = zip_dir / zip_filename

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in Path(mod_root).rglob("*"):
            if root.is_file():
                arcname = root.relative_to(mod_path.parent)
                zf.write(root, arcname)

    # -- TODO: Upload MinIO (minio mc put ou boto3) --------------------------------
    minio_url = None  # f"http://<minio-host>:9000/mods/{run_id}/{zip_filename}"

    # -- TODO: Commit Gitea -------------------------------------------------------
    commit_sha = None  # git add + git commit + git push sur le repo du mod

    # -- Rapport ------------------------------------------------------------------
    validation_summary = {}
    for vr in state.get("validation_results", []):
        level_name = str(vr.get("level", "unknown"))
        passed = vr.get("passed", False)
        validation_summary[level_name] = {
            "outcome": str(vr.get("outcome", "unknown")),
            "passed": passed,
            "errors_count": len(vr.get("errors", [])),
            "warnings_count": len(vr.get("warnings", [])),
        }

    report = {
        "run_id": run_id,
        "mod_name": mod_name,
        "status": "completed",
        "governance_tier": tier.value,
        "validation_summary": validation_summary,
        "zip_path": str(zip_path),
        "minio_url": minio_url,
        "commit_sha": commit_sha,
    }

    return {
        "artifact_id": run_id,
        "artifact_path": str(zip_path),
        "minio_url": minio_url,
        "commit_sha": commit_sha,
        "report": report,
        "status": AgentStatus.DONE,
    }


# =============================================================================
# Node 6 — ESCALATION (demande d'intervention humaine)
# =============================================================================


def escalation_node(state: ModAgentState) -> dict[str, Any]:
    """Marque le run comme necessitant une intervention humaine.

    Etapes :
      1. Determiner pourquoi l'escalade est necessaire
      2. Generer un rapport d'escalade avec les erreurs non resolues
      3. Retourner status=ESCALATED + requires_human_approval=True

    Args:
        state: Etat courant du run (avec errors et fix_attempts).

    Returns:
        Dict partiel marque ESCALATED + rapport d'escalade.
    """
    errors = state.get("errors", []) or []
    fixes = state.get("fix_attempts", []) or []

    escalation_report = {
        "run_id": state.get("run_id"),
        "mod_name": (state.get("plan") or {}).get("mod_name", "unknown"),
        "escalation_reason": _determine_escalation_reason(errors),
        "unresolved_errors": errors,
        "fix_attempts_made": len(fixes),
        "requires_human_approval": True,
    }

    return {
        "status": AgentStatus.ESCALATED,
        "needs_human_approval": True,
        "report": escalation_report,
    }


# =============================================================================
# Helpers pour les nodes
# =============================================================================


def _extract_mod_name(request: str) -> str:
    """Extrait un nom de mod depuis la demande utilisateur.

    Heuristic simple : prendre le premier mot capitalise ou l'entiere requete si courte.
    TODO: utiliser LLM pour une extraction precise.
    """
    import re

    # Chercher un modele "Mod X" ou "Ajoute X" ou simplement un nom propre
    patterns = [
        r"[Mm][Oo][Dd]\s+([A-Z][a-zA-Z0-9_-]+)",
        r"(?:ajouter|creer|generer)\s+(?:un|une)\s+[A-Za-z0-9_]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, request)
        if match:
            name = match.group(1).strip()
            if name:
                return name

    # Fallback : premiere partie de la requete < 64 chars
    return request.strip()[:64] or "GeneratedMod"


def _extract_mod_type(request: str) -> str:
    """Devine le type de mod depuis la demande.

    TODO: utiliser LLM pour une classification precise.
    """
    lower = request.lower()
    if any(kw in lower for kw in ["arme", "weapon", "hache", "sword", "epée"]):
        return "item"
    if any(kw in lower for kw in ["recette", "recipe", "craft", "cuisin", "meal"]):
        return "feature"
    if any(kw in lower for kw in ["zombie", "ennemi", "enemy", "mob"]):
        return "zombie"
    if any(kw in lower for kw in ["vehicle", "voiture", "car", "camion"]):
        return "vehicle"
    if any(kw in lower for kw in ["interface", "ui", "menu", "hud"]):
        return "ui"
    return "feature"  # default


def _compute_tier_after_validation(errors: list[dict], warnings: list[dict], state: ModAgentState) -> GovernanceTier:
    """Determiner le tier de gouvernance apres une validation.

    Simplification : si erreurs >= 3 → RED, >= 1 → ORANGE, sinon GREEN.
    TODO: utiliser ingestor.agent_core.policy.governance_tier_for_run pour la version complete.
    """
    from ingestor.agent_core.policy import governance_tier_for_run

    # Temporairement ajouter les errors/warnings a l'etat pour le calcul complet
    state_copy = dict(state)
    state_copy["errors"] = errors
    state_copy["warnings"] = warnings
    return governance_tier_for_run(state_copy)


def _requires_human(tier: GovernanceTier) -> bool:
    """Verifier si un tier necessite une approbation humaine."""
    return tier in (GovernanceTier.ORANGE, GovernanceTier.RED)


def _determine_escalation_reason(errors: list[dict]) -> str:
    """Determiner la raison principale d'escalade."""
    if not errors:
        return "Pas d'erreurs specifiees — escalation preventif."

    error_types = [e.get("type", "") for e in errors]
    from ingestor.agent_core.policy import RETRY_POLICY

    # Verifier si une erreur correspond a une clef d'escalade
    for key in RETRY_POLICY["human_escalation_required_for"]:
        if key in error_types:
            return f"Erreur critique : {key}"

    return "; ".join(set(error_types[:3]))  # premiere raison found
