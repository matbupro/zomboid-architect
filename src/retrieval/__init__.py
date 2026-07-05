"""src/retrieval -- Interface ChromaDB pour le knowledge engine.

Exposé public :
  - query_staging(question, k=5, filters=None) → dict avec chunks
  - query_production(question, k=5, filters=None) → dict avec chunks
  - list_collections() → list[str]
  - Health check methods

Utilisé par :
  - bot/engine_client.py (pour le fallback local)
  - ingestor/promote.py (pour le golden set gate)

Chemin vers les bases ChromaDB :
  staging → data/staging/chromadb/
  production → data/production/chromadb/
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.governance.logger import get_logger

logger = get_logger(__name__)

# ── Paths vers les bases ChromaDB ────────────────────────────────────────────────

_ROOT: Path = Path(__file__).parent.parent.parent  # project root


def _chroma_path(stage: str) -> Path:
    """Retourne le chemin vers la base ChromaDB de stage (staging/production)."""
    return _ROOT / "data" / stage / "chromadb"


# ── API publique ───────────────────────────────────────────────────────────────────

def query_staging(
    question: str,
    k: int = 5,
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Interroge ChromaDB staging et retourne les chunks correspondants.

    Fallback : si ChromaDB n'est pas disponible, retourne un resultat
    vide ({} ou {"chunks": []}). Le caller doit gérer le cas "pas de resultats".

    Parameters
    ----------
    question : str
        Texte de la requête.
    k : int
        Nombre de résultats.
    filters : dict, optional
        Filtres metadata (ex: {"type": "item", "version": "b41"}).

    Returns
    -------
    dict
        {"chunks": [...], "query": question, "k": k}
    """
    from .chroma_client import ChromaClient

    client = ChromaClient(stage="staging")
    return client.query(question, k=k, filters=filters)


def query_production(
    question: str,
    k: int = 5,
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Même chose que query_staging mais sur la base production."""
    from .chroma_client import ChromaClient

    client = ChromaClient(stage="production")
    return client.query(question, k=k, filters=filters)


def get_production_client():  # type: ignore[misc]
    """Retourne le client ChromaDB de production (pour tests / consumers externes)."""
    from .chroma_client import ChromaClient

    return ChromaClient(stage="production")


def get_staging_client():  # type: ignore[misc]
    """Retourne le client ChromaDB de staging."""
    from .chroma_client import ChromaClient

    return ChromaClient(stage="staging")


def list_collections(stage: str = "staging") -> list[str]:
    """Liste les collections dans une base ChromaDB."""
    from .chroma_client import ChromaClient

    client = ChromaClient(stage=stage)
    return client.list_collections()


# ── Health check ───────────────────────────────────────────────────────────────────

def health_check(stage: str = "staging") -> dict[str, Any]:
    """Vérifie la santé de la base ChromaDB et retourne un statut."""
    path = _chroma_path(stage)
    available = path.exists() and any(path.iterdir())
    return {
        "stage": stage,
        "path": str(path),
        "available": available,
        "mode": "persistent" if available else "no_data",
    }


# ── Main (CLI) ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    """Point d'entrée CLI pour le retrieval."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.retrieval",
        description="ChromaDB query interface (staging + production)",
    )
    parser.add_argument("stage", choices=["staging", "production"], help="Base à interroger")
    parser.add_argument("question", help="Texte de la requête")
    parser.add_argument("-k", type=int, default=5, help="Nombre de résultats (def: 5)")

    args = parser.parse_args(argv)

    import sys
    result = query_staging(args.question, k=args.k) if args.stage == "staging" else query_production(args.question, k=args.k)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
