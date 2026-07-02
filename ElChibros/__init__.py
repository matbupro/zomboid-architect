"""ingestor/__init__.py — Package entry point.

Exporte les symboles publics et charge __version__ depuis VERSION.
"""

from __future__ import annotations

from pathlib import Path

from ingestor.game_version import GameVersion, get_current_game_version, tag_chunk_with_version
from ingestor.logger import get_logger
from ingestor.lock import FileLock
from ingestor.parser import Parser, ParsedChunk, ContentType, ParseError
from ingestor.engine import IngestionEngine, query_staging

# ─── Version ─────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent
_VERSION_FILE = _ROOT / "VERSION"

__version__: str = "0.1.0-alpha"

if _VERSION_FILE.exists():
    raw = _VERSION_FILE.read_text(encoding="utf-8").strip().split()[0]
    if raw:
        __version__ = raw

# ─── Exports publics ───────────────────────────────────────────────────────────

__all__ = [
    # Version
    "__version__",
    "GameVersion",
    "get_current_game_version",
    "tag_chunk_with_version",
    # Logger
    "get_logger",
    # Lock
    "FileLock",
    # Parser
    "Parser",
    "ParsedChunk",
    "ContentType",
    "ParseError",
    # Engine
    "IngestionEngine",
    "query_staging",
]
