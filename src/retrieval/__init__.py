"""src/retrieval -- Interface de stockage pour le knowledge engine.

Exposé public :
  - query_staging(question, k=5, filters=None) -> dict avec chunks
  - query_production(question, k=5, filters=None) -> dict avec chunks
  - list_collections() -> list[str]
  - Health check methods

Backend de stockage : PostgreSQL/pgvector par defaut.
"""

from __future__ import annotations

import json
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)


def _get_storage_backend():
    """Retourne le backend PG (via create_backend)."""
    from src.storage import create_backend
    return create_backend()


# ===========================================================================
# API publique
# ===========================================================================

def query_staging(
    question: str,
    k: int = 5,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Interroge le storage staging et retourne les chunks correspondants."""
    try:
        backend = _get_storage_backend()
        results = backend.query("pz_staging", question, n_results=k, filters=filters)  # type: ignore[union-attr]
        chunks = [
            {"id": r.id, "prose": r.prose if isinstance(r.prose, str) else "", "metadata": getattr(r, "metadata_", {}) or {}}
            for r in results[:k]
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("query_staging échoué : %s", exc)
        chunks = []
    return {"chunks": chunks, "query": question, "k": k}


def query_production(
    question: str,
    k: int = 5,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Même chose que query_staging mais sur la base production."""
    try:
        backend = _get_storage_backend()
        results = backend.query("pz_production", question, n_results=k, filters=filters)  # type: ignore[union-attr]
        chunks = [
            {"id": r.id, "prose": r.prose if isinstance(r.prose, str) else "", "metadata": getattr(r, "metadata_", {}) or {}}
            for r in results[:k]
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("query_production échoué : %s", exc)
        chunks = []
    return {"chunks": chunks, "query": question, "k": k}


def get_production_client():
    """Retourne le client storage de production (pour tests / consumers externes)."""
    from src.storage import create_backend
    return create_backend()


def get_staging_client():
    """Retourne le client storage de staging."""
    from src.storage import create_backend
    return create_backend()


def list_collections(stage: str = "staging") -> list[str]:
    """Liste les collections dans le storage."""
    try:
        backend = _get_storage_backend()
        return backend.list_collections()  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return []


# ===========================================================================
# Health check
# ===========================================================================

def health_check(stage: str = "staging") -> dict[str, Any]:
    """Vérifie la santé du storage et retourne un statut."""
    try:
        backend = _get_storage_backend()
        status = backend.health()  # type: ignore[union-attr]
        return {"stage": stage, **status}
    except Exception as exc:  # noqa: BLE001
        return {
            "stage": stage,
            "available": False,
            "mode": "error",
            "error": str(exc),
        }


# ===========================================================================
# Main (CLI)
# ===========================================================================

def main(argv=None):
    """Point d'entrée CLI pour le retrieval."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.retrieval",
        description="Storage query interface (staging + production)",
    )
    parser.add_argument("stage", choices=["staging", "production"], help="Base à interroger")
    parser.add_argument("question", help="Texte de la requête")
    parser.add_argument("-k", type=int, default=5, help="Nombre de résultats (def: 5)")

    args = parser.parse_args(argv)
    result = query_staging(args.question, k=args.k) if args.stage == "staging" else query_production(args.question, k=args.k)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
