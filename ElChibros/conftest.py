"""tests/conftest.py — Fixtures pytest partagées."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestor.parser import Parser, ParsedChunk
from ingestor.game_version import GameVersion


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def golden_path() -> Path:
    root = Path(__file__).parent.parent
    return root / "tests" / "golden_set" / "golden.json"


@pytest.fixture
def golden_questions(golden_path: Path) -> list[dict]:
    if not golden_path.exists():
        pytest.skip(f"Golden set not found: {golden_path}")
    with open(golden_path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def sources_dir() -> Path:
    root = Path(__file__).parent.parent
    return root / "data" / "sources"


@pytest.fixture
def parser() -> Parser:
    return Parser()


@pytest.fixture
def sample_chunk() -> ParsedChunk:
    from datetime import datetime, timezone
    import uuid
    return ParsedChunk(
        id=str(uuid.uuid4()),
        type="item",
        version=GameVersion.B41.value,
        title="Test Axe",
        content="Item: Test Axe\nDamage: 10",
        metadata={"item_id": "Base.Axe", "damage": "10"},
        source_file="tests/items.xml",
        parsed_at=datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture
def staging_dir(tmp_path: Path) -> Path:
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    return staging


# ─── Helpers de test ──────────────────────────────────────────────────────────


def chunk_has_version(chunk: ParsedChunk, version: GameVersion) -> bool:
    return chunk.version == version.value


def chunks_have_versions(chunks: list[ParsedChunk]) -> bool:
    return all(
        c.version in [gv.value for gv in GameVersion]
        for c in chunks
    )
