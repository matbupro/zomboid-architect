"""src/storage — Abstraction du stockage vectoriel (SQLite / PostgreSQL / Qdrant).

Backends interchangeables :
  STORAGE_BACKEND=sqlite     → SQLite local (defaut, V1)
  STORAGE_BACKEND=postgres   → PostgreSQL + pgvector (V2)
  STORAGE_BACKEND=qdrant     → Qdrant distant + SQLite texte (S5-c, V3)

Usage :
    from src.storage import StorageBackend, SQLiteStorage, SearchResult
    # SQLite (defaut)
    backend = StorageBackend()
    # Ou explicitement
    backend = StorageBackend(config=_load_storage_config())
"""

from __future__ import annotations

from .qdrant_backend import QdrantVectorBackend, QdrantSearchResult
from .sqlite_storage import SearchResult, SQLiteStorage, StorageBackend, _load_storage_config

__all__ = [
    "SearchResult",
    "SQLiteStorage",
    "StorageBackend",
    "_load_storage_config",
    "QdrantVectorBackend",
    "QdrantSearchResult",
]
