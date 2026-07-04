"""Versioning utilities for Project Zomboid game data.

This module centralizes all version-related logic so that every component
knows which game version (B41 / B42) is being processed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
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


# ─── ChromaDB filter builders ──────────────────────────────────────────────


def build_version_filter(
    game_version: GameVersion | str | None = None,
) -> dict[str, Any] | None:
    """Build a ChromaDB-compatible ``$and`` filter for game-version isolation.

    ChromaDB's native query API supports MongoDB-style operators such as
    ``$eq``, ``$and``, and ``$or``.  This helper constructs the minimal
    expression needed to isolate a single game version:

        {"game_version": {"$eq": "b41"}}

    When *game_version* is ``None`` the caller should NOT pass a filter at all
    (returning ``None`` tells callers to omit the filter entirely — ChromaDB
    has no operator called "$any" that means "all values").

    Args:
        game_version: A ``GameVersion`` enum member, its value string ("b41"),
            or ``None`` for unfiltered results.

    Returns:
        A dict ready to be slotted into ChromaDB's ``$and`` expression, or
        ``None`` when no filtering is desired.

    Examples:
        >>> build_version_filter(GameVersion.B41)
        {"game_version": {"$eq": "b41"}}
        >>> build_version_filter(None)  # doctest: +SKIP
        None
        >>> build_version_filter("b42")
        {"game_version": {"$eq": "b42"}}
    """
    if game_version is None:
        return None

    if isinstance(game_version, GameVersion):
        value = game_version.value
    else:
        # Accept a raw string like "b41", normalize to lowercase
        value = str(game_version).strip().lower()

    return {"game_version": {"$eq": value}}


def build_version_and(
    *filters: dict[str, Any],
    game_version: GameVersion | str | None = None,
) -> dict[str, Any] | None:
    """Compose a ChromaDB ``$and`` filter from multiple conditions.

    This is the workhorse for queries that need to combine version isolation
    with other constraints (e.g. type, collection).

        {"$and": [
            {"game_version": {"$eq": "b41"}},
            {"type": "item"},
        ]}

    Args:
        *filters: Additional top-level ChromaDB filter dicts to include in the
            ``$and`` array.
        game_version: Optional version constraint (see :func:`build_version_filter`).

    Returns:
        A complete ``{"$and": [...]}`` dict, or ``None`` when no constraints
        were provided.
    """
    parts: list[dict[str, Any]] = []

    if game_version is not None:
        vf = build_version_filter(game_version)
        if vf is not None:
            parts.append(vf)

    for f in filters:
        if f:  # skip empty dicts
            parts.append(f)

    return {"$and": parts} if parts else None


def build_version_not_filter(
    game_version: GameVersion | str,
) -> dict[str, Any] | None:
    """Build a ChromaDB ``$ne`` (not-equal) filter to EXCLUDE a version.

        {"game_version": {"$ne": "b41"}}

    Args:
        game_version: The version to exclude.

    Returns:
        A ``{"$and": [...]}`` expression with the ``$ne`` clause, or ``None``
        if the argument was empty.
    """
    if game_version is None:
        return None

    if isinstance(game_version, GameVersion):
        value = game_version.value
    else:
        value = str(game_version).strip().lower()

    return {"game_version": {"$ne": value}}
