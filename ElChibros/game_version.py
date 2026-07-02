"""Versioning utilities for Project Zomboid game data.

This module centralizes all version-related logic so that every component
knows which game version (B41 / B42) is being processed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
import os

# ─── Enums ────────────────────────────────────────────────────────────────────


class GameVersion(Enum):
    """Supported game versions. Add B43, B44, ... as the game evolves."""

    B41 = "b41"  # Stable 41.x branch
    B42 = "b42"  # Experimental 42.x branch

    @classmethod
    def from_string(cls, value: str) -> "GameVersion":
        """Parse a string into a GameVersion, case-insensitive."""
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized or member.name.lower() == normalized:
                return member
        raise ValueError(
            f"Unknown game version '{value}'. "
            f"Valid values: {[m.value for m in cls]}"
        )

    @classmethod
    def all(cls) -> list["GameVersion"]:
        return list(cls)


# ─── Dataclasses ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VersionStamp:
    """Immutable, human-readable version identifier attached to any artifact."""

    major: int
    minor: int
    patch: int
    pre: str = ""          # e.g. "alpha", "beta.1"
    game_version: GameVersion = GameVersion.B41

    def __str__(self) -> str:
        pre = f"-{self.pre}" if self.pre else ""
        return f"{self.major}.{self.minor}.{self.patch}{pre} ({self.game_version.value})"

    @property
    def semver(self) -> str:
        """Pure SemVer string without the game version tag."""
        pre = f"-{self.pre}" if self.pre else ""
        return f"{self.major}.{self.minor}.{self.patch}{pre}"

    @property
    def sortable_tuple(self) -> tuple:
        """Four-element tuple used for reliable sorting comparisons."""
        pre_order = (self.pre or "z").split(".")
        # "alpha" < "beta.1" < "rc.3" < ""  (empty = final release)
        pre_major = pre_order[0]
        pre_order_map = {"alpha": 0, "beta": 1, "rc": 2}
        pre_num = int(pre_order[1]) if len(pre_order) > 1 else 0
        pre_rank = pre_order_map.get(pre_major, 99)
        game_rank = list(GameVersion).index(self.game_version)
        return (
            self.major,
            self.minor,
            self.patch,
            (pre_rank, pre_num),
            game_rank,
        )


# ─── Version Resolution ─────────────────────────────────────────────────────


_loaded_from_env: Optional[str] = None


def get_current_game_version() -> GameVersion:
    """Return the game version targeted by the current ingestion run.

    Priority order:
      1. Environment variable  PZ_GAME_VERSION  (highest)
      2. VERSION file at repo root
      3. Fallback: B41 (safe default)

    Callers that need a guaranteed GameVersion enum should use this function
    rather than hard-coding GameVersion.B41.
    """
    global _loaded_from_env

    if _loaded_from_env is not None:
        return GameVersion.from_string(_loaded_from_env)

    # 1. Env var
    env_val = os.environ.get("PZ_GAME_VERSION", "").strip()
    if env_val:
        _loaded_from_env = env_val
        return GameVersion.from_string(env_val)

    # 2. VERSION file
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        raw = version_file.read_text().strip()
        # Accept either "0.1.0-alpha (b41)" or plain "0.1.0-alpha"
        for gv in GameVersion:
            suffix = f"({gv.value})"
            if suffix in raw:
                _loaded_from_env = gv.value
                return gv
        # Fallback to first tag in file
        first_word = raw.split()[0]
        try:
            _loaded_from_env = first_word
            return GameVersion.from_string(first_word)
        except ValueError:
            pass

    # 3. Safe default
    _loaded_from_env = GameVersion.B41.value
    return GameVersion.B41


def tag_chunk_with_version(chunk: dict) -> dict:
    """Ensure every ChromaDB chunk dict carries the current game version.

    This function is the single place where ``game_version`` is stamped onto
    chunks produced by the parser.  Call it before writing any chunk to
    ChromaDB so that both the staging and production databases always carry
    a version tag.

    Args:
        chunk: Mutable chunk dict (must contain at least an ``id`` key).

    Returns:
        The same dict with ``game_version`` set in ``metadata``.
    """
    gv = get_current_game_version()
    if "metadata" not in chunk:
        chunk["metadata"] = {}
    chunk["metadata"]["game_version"] = gv.value
    return chunk
