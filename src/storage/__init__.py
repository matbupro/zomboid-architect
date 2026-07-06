"""src/storage — Stockage local sans service externe.

Remplacement de ChromaDB via SQLite + embedding optionnel Ollama.

Usage :
    from src.storage.sqlite_storage import SQLiteStorage, StorageBackend
    # Auto fallback (ChromaDB → SQLite si injoignable)
    backend = StorageBackend()  # ou
    backend = SQLiteStorage(data_dir="data/storage")
"""

from __future__ import annotations

from .sqlite_storage import SQLiteStorage

__all__ = ["SQLiteStorage"]
