"""src/storage — Backend PostgreSQL/pgvector pour le stockage vectoriel.

Backend unique :
  STORAGE_BACKEND=postgres   → PostgreSQL + pgvector (V2, defaut)
  STORAGE_BACKEND=qdrant     → Qdrant distant + PG texte (S5-c, optionnel)

Usage :
    from src.storage import StorageBackend, SearchResult
    backend = StorageBackend()
"""

from __future__ import annotations

from .postgres_backend import (
    PostgresStorageBackend as StorageBackend,  # alias principal
    PostgresStorageBackend,
    SearchResult,
    _format_pgvector,
)
from .qdrant_backend import QdrantVectorBackend, QdrantSearchResult

# Default backend configuration
DEFAULT_BACKEND = "postgres"


def get_storage_config() -> dict:
    """Load storage config from environment variables."""
    import os

    return {
        "backend": os.getenv("STORAGE_BACKEND", DEFAULT_BACKEND).lower(),
        "pg_host": os.getenv("STORAGE_PG_HOST", "localhost"),
        "pg_port": int(os.getenv("STORAGE_PG_PORT", "5432")),
        "pg_db": os.getenv("STORAGE_PG_DB", "zomboid_storage"),
        "pg_user": os.getenv("STORAGE_PG_USER", "postgres"),
        "pg_pass": os.getenv("STORAGE_PG_PASS"),
        "ollama_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") or None,
        "qdrant_url": os.getenv("STORAGE_QDRANT_URL", "http://localhost:6333"),
    }


def create_backend() -> StorageBackend:  # type: ignore[name-defined]
    """Factory to create backend based on STORAGE_BACKEND env."""
    cfg = get_storage_config()
    if cfg["backend"] == "postgres":
        return StorageBackend(
            host=cfg["pg_host"],
            port=cfg["pg_port"],
            db=cfg["pg_db"],
            user=cfg["pg_user"],
            password=cfg["pg_pass"],
        )
    else:
        # Default to postgres for now
        return StorageBackend(
            host=cfg["pg_host"],
            port=cfg["pg_port"],
            db=cfg["pg_db"],
            user=cfg["pg_user"],
            password=cfg["pg_pass"],
        )


__all__ = [
    "SearchResult",
    "StorageBackend",
    "PostgresStorageBackend",
    "_format_pgvector",
    "QdrantVectorBackend",
    "QdrantSearchResult",
    "get_storage_config",
    "create_backend",
]
