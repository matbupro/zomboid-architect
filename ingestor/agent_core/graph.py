"""graph — Construction du graphe LangGraph pour la boucle agentique PZ.

 assemble les nodes, les conditional edges et l'etat dans un StateGraph compile.

Le graphe suit le diagramme d'etat de l'architecture doc :

    START -> PLANNING -> BUILDING -> VALIDATING
                                               /      \\
                                          FIXING        PACKAGING
                                             |              |
                                      (retry < 5?)     END
                                         |
                                    ESCALATE -> END

Usage programmatique :
    graph = build_graph()
    state = ModAgentState(user_request="Add a new axe", build_target="build42")
    result = graph.invoke(state)

Usage CLI :
    python -m ingestor.agent_core.graph --request "Create a custom farming tool" --target build42
"""

from __future__ import annotations

import sys
from typing import Any, Optional


def _get_next_node(state: dict[str, Any]) -> str:  # type: ignore[type-arg]
    """Conditional edge dispatcher — determine le prochain noeud a executer.

    Logique :
      - Si status=ESCALATED ou DONE ou FAILED → END
      - Si status=VALIDATING et errors present → FIXING (si retry < max) ou ESCALATE (si retry >= max)
      - Si status=FIXING → VALIDATING
      - Si status=PACKAGING → END
      - Sinon → END

    Args:
        state: Etat complet du run courant.

    Returns:
        Nom de la prochaine node ("fixing_node", "packaging_node", "escalate_node" ou "__end__").
    """
    status = state.get("status", "")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 5)

    if status in ("escalated", "done", "failed"):
        return "__end__"

    if status == "validating":
        errors = state.get("errors") or []
        # Si erreurs et retry max atteint → escalate
        if errors and retry_count >= max_retries:
            return "escalate_node"
        # Si erreurs mais retry disponible → fixing
        if errors:
            return "fixing_node"
        # Pas d'erreurs → packaging
        return "packaging_node"

    if status == "fixing":
        return "validating_node"

    if status == "packaging":
        return "__end__"

    return "__end__"


def build_graph():  # -> Any: LangGraph StateGraph compilee
    """Construit et retourne le graphe LangGraph compile.

    Etapes de construction :
      1. Creer un StateGraph avec ModAgentState comme type d'etat
      2. Ajouter chaque node (planning, building, validating, fixing, packaging, escalate)
      3. Definir les edges directs (sans conditional)
      4. Definir l'edge conditionnel depuis validating_node vers fix/pack/escalate
      5. Compiler le graphe

    Returns:
        Un graphe compile LangGraph pret a etre invoke avec graph.invoke(state).
    """
    # Importe langgraph de facon lazy — leve ImportError si pas installe
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as exc:
        raise ImportError(
            "langgraph est requis pour la boucle agentique. "
            "Installer avec : pip install langgraph langgraph-checkpoint-sqlite"
        ) from exc

    # Importer les nodes
    from ingestor.agent_core.nodes import (
        planning_node,
        building_node,
        validating_node,
        fixing_node,
        packaging_node,
        escalation_node,
    )
    from ingestor.agent_core.state import ModAgentState

    # -- Creer le graphe --------------------------------------------------------
    graph_builder = StateGraph(ModAgentState)  # type: ignore[arg-type]

    # -- Ajouter les nodes ------------------------------------------------------
    graph_builder.add_node("planning_node", planning_node)
    graph_builder.add_node("building_node", building_node)
    graph_builder.add_node("validating_node", validating_node)
    graph_builder.add_node("fixing_node", fixing_node)
    graph_builder.add_node("packaging_node", packaging_node)
    graph_builder.add_node("escalation_node", escalation_node)

    # -- Edges directs ----------------------------------------------------------
    graph_builder.add_edge(START, "planning_node")
    graph_builder.add_edge("planning_node", "building_node")
    graph_builder.add_edge("building_node", "validating_node")
    graph_builder.add_edge("fixing_node", "validating_node")
    graph_builder.add_edge("packaging_node", END)
    graph_builder.add_edge("escalation_node", END)

    # -- Edge conditionnel depuis validating_node -------------------------------
    graph_builder.add_conditional_edges(
        "validating_node",
        _get_next_node,
        {
            "fixing_node": "fixing_node",
            "packaging_node": "packaging_node",
            "escalation_node": "escalation_node",
            "__end__": END,
        },
    )

    # -- Compiler ---------------------------------------------------------------
    compiled_graph = graph_builder.compile()
    return compiled_graph


# =============================================================================
# Fonction de facilite — run un mod en une ligne
# =============================================================================


def run_agent_loop(
    user_request: str,
    build_target: str = "build42",
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """Execute la boucle agentique complete pour une demande utilisateur.

    Fonction convenience qui :
      1. Construit le graphe (ou le met en cache)
      2. Initialise un ModAgentState
      3. Invoke le graphe
      4. Retourne l'etat final

    Args:
        user_request: Demande de l'utilisateur (ex: "Ajouter une hache custom").
        build_target: "build41" | "build42" | "both".
        project_id: UUID du mod_projects (optionnel).

    Returns:
        ModAgentState final avec status, report, validation_results, etc.
    """
    from ingestor.agent_core.state import AgentStatus, ModAgentState

    # Initialiser l'etat
    initial_state: ModAgentState = {  # type: ignore[dict-item]
        "run_id": "",
        "project_id": project_id,
        "user_request": user_request,
        "build_target": build_target,
        "max_retries": 5,
        "retry_count": 0,
        "status": AgentStatus.PLANNING,
        "plan": None,
        "context_chunks": [],
        "generated_files": {},
        "mod_root": None,
        "validation_results": [],
        "errors": [],
        "warnings": [],
        "fix_attempts": [],
        "artifact_id": None,
        "artifact_path": None,
        "commit_sha": None,
        "minio_url": None,
        "governance_tier": "green",
        "needs_human_approval": False,
        "report": None,
    }

    # Build + invoke
    graph = build_graph()
    final_state = graph.invoke(initial_state)

    return final_state


# =============================================================================
# CLI entry point
# =============================================================================


def main():  # pragma: no cover — CLI entry point
    """Entry point CLI pour la boucle agentique.

    Usage:
        python -m ingestor.agent_core.graph --request "Add a custom farming tool"
        python -m ingestor.agent_core.graph --request "Create a new zombie type" --target build41
    """
    import argparse

    parser = argparse.ArgumentParser(description="Boucle agentique de production de mods PZ")
    parser.add_argument("--request", "-r", required=True, help="Demande utilisateur (ex: 'Add a custom axe')")
    parser.add_argument("--target", "-t", default="build42", choices=["build41", "build42", "both"],
                        help="Build cible (default: build42)")
    parser.add_argument("--project-id", "-p", default=None, help="UUID du mod_projects (optionnel)")
    args = parser.parse_args()

    result = run_agent_loop(
        user_request=args.request,
        build_target=args.target,
        project_id=args.project_id,
    )

    # Afficher un resume
    status = result.get("status", "unknown")
    tier = result.get("governance_tier", "unknown")
    report = result.get("report") or {}

    print(f"\n{'='*60}")
    print(f"  Agent loop terminé — Status: {status} | Tier: {tier}")
    print(f"{'='*60}\n")

    if status.value == "done":
        summary = report.get("validation_summary", {})
        for level, details in summary.items():
            passed_str = "PASSED" if details.get("passed") else "FAILED"
            errors = details.get("errors_count", 0)
            print(f"  {level}: {passed_str} (errors={errors})")
        artifact_path = report.get("zip_path", "N/A")
        print(f"\n  Artifact ZIP: {artifact_path}")

    elif status.value == "escalated":
        reason = report.get("escalation_reason", "inconnu")
        fixes = report.get("fix_attempts_made", 0)
        print(f"  Escalade necessaire — Raison: {reason}")
        print(f"  Tentatives de correction: {fixes}")

    elif status.value == "failed":
        errors = result.get("errors", [])
        for err in errors:
            print(f"  ERREUR: {err.get('detail', 'unknown')}")

    else:
        print(f"  Status inattendu: {status}")

    print()


if __name__ == "__main__":
    main()
