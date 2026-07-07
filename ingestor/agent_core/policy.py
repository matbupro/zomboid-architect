"""policy — Retry, escalation et gouvernance pour la boucle agentique.

Politiques definit dans l'architecture doc (section A du doc) :

  RETRY_POLICY       — max_attempts=5, backoff exponential
  should_escalate()  — conditions d'escalade vers un humain
  governance_tier_for_run() — determination GREEN/ORANGE/RED basée sur les erreurs

Tiers de gouvernance :
    GREEN  — code propre, tests ok → merge auto
    ORANGE — nouvelles recettes/items ou modifications existent → review obligatoire
    RED    — fichiers core modifiés ou dependency externe → humain obligatoire
"""

from __future__ import annotations

import math
from typing import Any

from ingestor.agent_core.state import (
    GovernanceTier,
    ModAgentState,
    ValidationOutcome,
)


# =============================================================================
# Policy retry
# =============================================================================


RETRY_POLICY: dict[str, Any] = {
    "max_attempts": 5,
    "backoff_multiplier": 2,
    "initial_delay_seconds": 5,
    "escalation_on": [
        "syntax_error_after_5_retries",
        "runtime_crash_after_5_retries",
        "api_misuse_detected",
        "security_policy_violation",
        "dependency_conflict_unresolvable",
    ],
    "human_escalation_required_for": [
        "new_mod_requires_steam_workshop_upload",
        "mod_modifies_core_game_files",
        "external_api_key_required",
        "dependency_on_proprietary_mod",
    ],
}


def compute_backoff_delay(attempt: int) -> float:
    """Calcule le delai de backoff exponential pour un attempt donne.

    Delai = initial_delay * (backoff_multiplier ** (attempt - 1))
    Exemple : attempt=1 → 5s, attempt=2 → 10s, attempt=3 → 20s, ...

    Args:
        attempt: numero de tentative (1-indexed).

    Returns:
        Delai en secondes.
    """
    base = RETRY_POLICY["initial_delay_seconds"]
    multiplier = RETRY_POLICY["backoff_multiplier"]
    return base * (multiplier ** (attempt - 1))


def should_escalate(state: ModAgentState) -> bool:
    """Determiner si un run doit etre escalade a un humain.

    Conditions d'escalade :
      1. retry_count >= MAX_RETRIES
      2. Une erreur correspond a une clef dans RETRY_POLICY["escalation_on"]
      3. Une erreur correspond a une clef dans RETRY_POLICY["human_escalation_required_for"]

    Args:
        state: Etat actuel de la boucle agentique.

    Returns:
        True si l'escalade est justifiee.
    """
    max_retries = state.get("max_retries", RETRY_POLICY["max_attempts"])
    if state.get("retry_count", 0) >= max_retries:
        return True

    errors = state.get("errors", []) or []
    error_types = {e.get("type", "") for e in errors}

    escalation_keys = set(RETRY_POLICY["escalation_on"])
    human_keys = set(RETRY_POLICY["human_escalation_required_for"])

    if error_types & escalation_keys:
        return True
    if error_types & human_keys:
        return True

    return False


# =============================================================================
# Determination du tier de gouvernance
# =============================================================================


def governance_tier_for_run(state: ModAgentState) -> GovernanceTier:
    """Determiner le tier de gouvernance pour un run donne.

    Regles :
      GREEN  — Aucun fichier core modifie, pas de dependance externe, <=1 warning
      ORANGE — Nouvelles recettes ou modification d'items existants, >1 warning
      RED    — Modification de fichiers core du jeu, dependance externe, >=3 fix attempts

    Args:
        state: Etat actuel du run.

    Returns:
        GovernanceTier determined based on the analysis.
    """
    fix_count = len(state.get("fix_attempts", []) or [])
    warnings = state.get("warnings", []) or []
    plan = state.get("plan") or {}
    errors = state.get("errors", []) or []

    # Conditions RED
    if "mod_modifies_core_game_files" in {e.get("type", "") for e in errors}:
        return GovernanceTier.RED
    if any(e.get("type") == "dependency_on_proprietary_mod" for e in errors):
        return GovernanceTier.RED
    if fix_count >= 3:
        return GovernanceTier.RED

    # Conditions ORANGE
    mod_type = plan.get("mod_type", "")
    has_new_recipes = plan.get("has_new_recipes", False)
    has_modified_items = plan.get("has_modified_items", False)
    if has_new_recipes or has_modified_items:
        return GovernanceTier.ORANGE
    if len(warnings) > 1:
        return GovernanceTier.ORANGE

    # Par defaut : GREEN
    return GovernanceTier.GREEN


# =============================================================================
# Determiner si un mod est autorise a etre publie (sans humain)
# =============================================================================


def can_publish_auto(tier: GovernanceTier) -> bool:
    """Verifier si un mod peut etre publie automatiquement.

    Args:
        tier: Tier de gouvernance actuel.

    Returns:
        True si la publication automatique est autorisee.
    """
    return tier == GovernanceTier.GREEN


def requires_human_approval(tier: GovernanceTier) -> bool:
    """Verifier si un mod necessite une approbation humaine.

    Args:
        tier: Tier de gouvernance actuel.

    Returns:
        True si un humain doit approuver avant publication.
    """
    return tier in (GovernanceTier.ORANGE, GovernanceTier.RED)
