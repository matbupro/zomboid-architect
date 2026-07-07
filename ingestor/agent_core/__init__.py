"""agent_core — Boucle agentique LangGraph pour la production de mods PZ.

Orchestre une sequence etatique generate -> tester -> corriger -> valider -> packager.
Le coeur du systeme est la boucle, pas le stockage.

Architecture :
    START -> PLANNING -> BUILDING -> VALIDATING -> (errors ? FIXING -> VALIDATING | PACKAGING) -> END

Chaque node est une fonction stand-alone qui lit/ecrit ModAgentState.
"""

from __future__ import annotations

# -- Sous-modules exports --

from ingestor.agent_core.state import AgentStatus, GovernanceTier, BuildTarget, ValidationLevel, ValidationOutcome, ModAgentState
from ingestor.agent_core.validation import validate_level1, validate_level2, validate_level3, validate_level4
from ingestor.agent_core.policy import RETRY_POLICY, should_escalate, governance_tier_for_run
from ingestor.agent_core.nodes import (
    planning_node,
    building_node,
    validating_node,
    fixing_node,
    packaging_node,
    escalation_node,
)
from ingestor.agent_core.graph import build_graph

__all__ = [
    # State + enums
    "ModAgentState",
    "AgentStatus",
    "GovernanceTier",
    "BuildTarget",
    "ValidationLevel",
    "ValidationOutcome",
    # Validation levels
    "validate_level1",
    "validate_level2",
    "validate_level3",
    "validate_level4",
    # Policy
    "RETRY_POLICY",
    "should_escalate",
    "governance_tier_for_run",
    # Agent nodes
    "planning_node",
    "building_node",
    "validating_node",
    "fixing_node",
    "packaging_node",
    "escalation_node",
    # Graph assembly
    "build_graph",
]
