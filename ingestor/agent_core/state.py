"""state — Definition de l'etat central de la boucle agentique.

Types enums :
    AgentStatus     — etat courant du pipeline mod (planning → building → …)
    ValidationLevel  — niveau de validation (l1_static … l4_functional)
    ValidationOutcome — resultat d'un niveau (passed / failed / warning / error / skipped)
    GovernanceTier   — tier de gouvernance (green / orange / red)
    BuildTarget      — build cible (41 stable / 42 bleeding0)

Classe principale :
    ModAgentState — TypedDict qui porte l'etat complet entre les nodes LangGraph.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Literal, Optional, TypedDict


# =============================================================================
# Enums
# =============================================================================


class AgentStatus(str, Enum):
    """Etats du pipeline agentique."""

    PLANNING = "planning"
    BUILDING = "building"
    VALIDATING = "validating"
    FIXING = "fixing"
    PACKAGING = "packaging"
    ESCALATED = "escalated"
    DONE = "done"
    FAILED = "failed"


class ValidationLevel(str, Enum):
    """Niveaux de validation progressifs."""

    L1_STATIC = "l1_static"
    L2_BOOT = "l2_boot"
    L3_RUNTIME = "l3_runtime"
    L4_FUNCTIONAL = "l4_functional"


class ValidationOutcome(str, Enum):
    """Resultat d'un niveau de validation."""

    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class GovernanceTier(str, Enum):
    """Niveaux de securite / gouvernance."""

    GREEN = "green"    # automation complete
    ORANGE = "orange"  # review obligatoire
    RED = "red"        # intervention humaine obligatoire


class BuildTarget(str, Enum):
    """Build cible du mod PZ."""

    BUILD41 = "build41"
    BUILD42 = "build42"
    BOTH = "both"


# =============================================================================
# Struct de validation individuelle
# =============================================================================


class ValidationResult(TypedDict, total=False):
    """Resultat d'un niveau de validation individuellement."""

    level: ValidationLevel
    outcome: ValidationOutcome
    passed: bool
    errors: list[dict]
    warnings: list[dict]
    files_checked: int
    duration_ms: int
    output_log: str


# =============================================================================
# Etat principal (TypedDict — lu par LangGraph StateGraph)
# =============================================================================


class ModAgentState(TypedDict, total=False):
    """Etat complet d'un run agentique pour un mod.

    Transite entre les nodes via la clef ``next_status`` qui indique quel noeud
    executer ensuite (retourne par `get_next_node`).  Si absente = fin du pipeline.

    TypedDict est utilise plutot que dataclass car LangGraph attend des dicts avec
    des operations de fusion (`|`) entre les retours des nodes.
    """

    # -- Identite --
    run_id: str                        # UUID unique du run courant
    project_id: Optional[str]          # UUID mod_projects (si connu)
    user_request: str                  # Demande utilisateur brute

    # -- Configuration --
    build_target: BuildTarget           # build41 / build42 / both
    max_retries: int                    # MAX_RETRIES par defaut 5

    # -- Compteur de retry global au run --
    retry_count: int                    # Tentatives cumulées (fixing + validating)

    # -- Status courant du pipeline --
    status: AgentStatus                 # Vue d'ensemble de la phase actuelle

    # -- Etape PLANNING --
    plan: Optional[dict]               # Plan d'action généré par planning_node
    context_chunks: list[dict]         # Chunks Qdrant/PG recupérés pour le contexte

    # -- Etape BUILDING --
    generated_files: dict[str, str]    # {relative_path: content} pour build 41
    mod_root: Optional[str]            # Chemin du dossier racine du mod (sur disque)

    # -- Etape VALIDATING --
    validation_results: list[ValidationResult]  # Resultats cumulés des niveaux
    errors: list[dict]                 # Erreurs non résolues apres fixings
    warnings: list[dict]               # Warnings conserves apres validation finale

    # -- Etape FIXING --
    fix_attempts: list[dict]           # {fix_number, level, error_type, fix_description, files_modified}

    # -- Etape PACKAGING --
    artifact_id: Optional[str]         # UUID mod_artifacts
    artifact_path: Optional[str]       # Chemin vers le ZIP final
    commit_sha: Optional[str]          # Commit Gitea
    minio_url: Optional[str]           # URL MinIO de l'artifact

    # -- Gouvernance --
    governance_tier: GovernanceTier    # Tier actuel (GREEN/ORANGE/RED)
    needs_human_approval: bool         # True si un humain doit approuver avant publication

    # -- Resultat final --
    report: Optional[dict]             # Rapport Markdown généré en fin de run
