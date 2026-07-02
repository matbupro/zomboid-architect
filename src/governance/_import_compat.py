"""Centralized import helpers for cross-module fallbacks.

Used by restore.py, promote.py and other modules to handle the dual-layout
where governance modules exist in both ``src/governance/`` and ``ingestor/legacy`` paths.
"""

from __future__ import annotations


def get_logger(name: str):
    """Get a logger, trying ``src.governance.logger`` first, falling back to ``ingestor.logger``."""
    try:
        from src.governance.logger import get_logger as _gl  # type: ignore[import-not-found]
        return _gl(name)
    except ImportError:
        from ingestor.logger import get_logger as _gl  # type: ignore[import-not-found, assignment]
        return _gl(name)


def get_filelock():
    """Return ``FileLock``, trying ``src.governance.lock`` first, falling back to ``ingestor.lock``."""
    try:
        from src.governance.lock import FileLock as _FL  # type: ignore[import-not-found]
        return _FL
    except ImportError:
        from ingestor.lock import FileLock as _FL  # type: ignore[import-not-found, assignment]
        return _FL


def get_game_version():
    """Return ``(get_current_game_version, GameVersion)``, trying ``src.governance.game_version`` first."""
    try:
        from src.governance.game_version import (  # type: ignore[import-not-found]
            get_current_game_version,
            GameVersion,
        )
        return get_current_game_version, GameVersion  # noqa: PLC0414
    except ImportError:
        from ingestor.game_version import (  # type: ignore[import-not-found, assignment]
            get_current_game_version as _gc,
            GameVersion as _GV,
        )
        return _gc, _GV  # noqa: PLC0414
