"""src/storage — Abstraction du stockage vectoriel (SQLite / PostgreSQL).

Remplacement d'un storage fixe par un backend interchangeable SQLite/PostgreSQL.

Config via .env :
  STORAGE_BACKEND=sqlite     → SQLite local (defaut, V1)
  STORAGE_BACKEND=postgres   → PostgreSQL + pgvector (V2)

Usage :
    from src.storage import StorageBackend, SQLiteStorage, SearchResult
    # SQLite (defaut)
    backend = StorageBackend()
    # Ou explicitement
    backend = StorageBackend(config=_load_storage_config())
"""

from __future__ import annotations

from .sqlite_storage import SearchResult, SQLiteStorage, StorageBackend, _load_storage_config

__all__ = [
    "SearchResult",
    "SQLiteStorage",
    "StorageBackend",
    "_load_storage_config",
]
