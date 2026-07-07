"""test_wikijson_schema — Validator schema: le JSON Wiki.json match-il les types PG attendus ?

Schema PostgreSQL attendu (chacune des collections) :
    chunk_id  TEXT PRIMARY KEY
    text      TEXT NOT NULL
    embedding vector(768)
    metadata_ jsonb DEFAULT '{}'
    source    TEXT
    game_version TEXT
    ingest_time DOUBLE PRECISION

Le validateur verifie que toutes les donnees du processor sont PG-compatible :
  - Metadata values JSON-serializable (str/int/float/bool/list/dict)
  - Text ne contient pas de NUL bytes (\x00) ni sequences invalides
  - Chunk keys sont des strings valides (pas None, pas empty pour le key)
  - fields_count est int positif
  - Categories processed sont des strings non vides
  - total_entries est un entier >= 0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestor.config import IngestorConfig
from ingestor.processors.wikijson import WikiJsonProcessor


# ===========================================================================
# Fixtures — donnees PZ avec schemas valides et invalides
# ===========================================================================


def _make_valid_data() -> dict[str, Any]:
    """Donnees 100% PG-compatible."""
    return {
        "items": {
            "iron_pipe": {
                "Name": "Iron Pipe",
                "Type": "weapon_melee",
                "weight": 1.5,
                "Categories": ["Weapons"],
                "SubCategory": "Melee Weapons",
                "description": "A heavy iron pipe.",
                "condition_max": 240,
                "DamageTiers": {"common": 8, "uncommon": 10, "rare": 12},
            },
        },
        "recipes": {
            "craft_nails": {
                "Name": "Nails",
                "Result": "Nails",
                "Time": 5,
                "Category": "Scrap",
                "ingredients": {"Metal Sheet": 2},
                "SkillRequired": "Scavenging",
            },
        },
        "mobs": {
            "walker_normal": {
                "Name": "Normal Walker",
                "HP": 50,
                "Speed": 1.0,
                "Damage": 10,
            },
        },
    }


def _write_wikidrive(tmp_path: Path, data: dict[str, Any]) -> Path:
    """Ecrit les donnees dans un dossier multi-fichiers."""
    base = tmp_path / "pz-wiki-data"
    base.mkdir(parents=True, exist_ok=True)
    for key, val in data.items():
        (base / f"{key}.json").write_text(json.dumps(val), encoding="utf-8")
    return base


# ===========================================================================
# Tests — Schema Validation
# ===========================================================================


async def test_schema_metadata_jsonb_serializable(tmp_path: Path):
    """Toutes les metadata values sont JSONB-serializables (str/int/float/bool/list/dict)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    # Verifier chaque chunk metadata
    for c in result.chunks:
        _assert_jsonb_compatible(c.metadata, f"chunk {c.metadata.get('key')}")


def _assert_jsonb_compatible(data: Any, context: str = "root"):
    """Recursive check that data is valid PostgreSQL JSONB type."""
    if isinstance(data, dict):
        for k, v in data.items():
            assert isinstance(k, str), f"{context}: key '{k}' is not str — JSONB keys must be strings"
            _assert_jsonb_compatible(v, f"{context}.{k}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            _assert_jsonb_compatible(item, f"{context}[{i}]")
    elif isinstance(data, (str, int, float, bool)):
        pass  # valid JSON types
    elif data is None:
        pass  # JSON null — PG-compatible (stored as NULL)
    else:
        pytest.fail(f"{context}: value {type(data).__name__}({data!r}) not valid JSONB type")


async def test_schema_chunk_text_no_null_bytes(tmp_path: Path):
    """Texte des chunks ne contient pas de NUL bytes (\x00)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    for c in result.chunks:
        assert "\x00" not in c.text, f"Chunk {c.metadata.get('key')} contains NUL bytes"


async def test_schema_chunk_keys_are_strings(tmp_path: Path):
    """Tous les chunk metadata keys sont des strings valides."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    for c in result.chunks:
        key = c.metadata.get("key")
        assert isinstance(key, str), f"Chunk key is {type(key)}, expected str"
        assert len(key) > 0, f"Chunk key is empty string"


async def test_schema_fields_count_is_int_positive(tmp_path: Path):
    """metadata fields_count est un int >= 0 pour chaque chunk."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    for c in result.chunks:
        fc = c.metadata.get("fields_count")
        assert isinstance(fc, int), f"fields_count is {type(fc)}, expected int"
        assert fc >= 0, f"fields_count negative: {fc}"


async def test_schema_categories_processed_are_nonempty_strings(tmp_path: Path):
    """categories_processed contient des strings non vides."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    cats = result.metadata["categories_processed"]
    assert isinstance(cats, list)
    for cat in cats:
        assert isinstance(cat, str), f"category {cat!r} is not str"
        assert len(cat) > 0, f"Empty category name"


async def test_schema_total_entries_is_int_non_negative(tmp_path: Path):
    """total_entries est un entier >= 0."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    total = result.metadata.get("total_entries")
    assert isinstance(total, int), f"total_entries is {type(total)}, expected int"
    assert total >= 0, f"total_entries negative: {total}"


async def test_schema_word_count_valid(tmp_path: Path):
    """word_count est un entier > 0 (quand chunks existes)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    assert isinstance(result.word_count, int)
    assert result.word_count > 0


async def test_schema_extraction_time_is_number(tmp_path: Path):
    """extraction_time_ms est un number (int/float)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    assert isinstance(result.extraction_time_ms, (int, float))
    assert result.extraction_time_ms >= 0


async def test_schema_file_hash_non_empty_string(tmp_path: Path):
    """file_hash est un string non vide (SHA-256 hex)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    assert isinstance(result.file_hash, str)
    assert len(result.file_hash) > 0
    # SHA-256 hex string — 64 chars
    assert len(result.file_hash) == 64, f"file_hash length {len(result.file_hash)} expected 64"
    int(result.file_hash, 16)  # must be valid hex


async def test_schema_source_is_non_empty_string(tmp_path: Path):
    """source est un string non vide."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    assert isinstance(result.source, str)
    assert len(result.source) > 0


async def test_schema_collection_is_known_collection_name(tmp_path: Path):
    """Le collection name est une collection PG valide."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    # La collection par defaut du processor est "pz_items"
    assert result.collection in ("pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages")


async def test_schema_text_not_too_long(tmp_path: Path):
    """Texte de chunk pas excessivement long (> 100k caracteres → suspect)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    for c in result.chunks:
        assert len(c.text) < 100_000, (
            f"Chunk {c.metadata.get('key')} text too long ({len(c.text)} chars)"
        )


async def test_schema_text_valid_utf8(tmp_path: Path):
    """Texte des chunks est un string Python valide (toujours UTF-8 en memoire)."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    for c in result.chunks:
        # En memoire Python 3, tout est unicode — validation de re-serialisation
        encoded = c.text.encode("utf-8")
        assert len(encoded) > 0


async def test_schema_recipe_ingredients_serializable(tmp_path: Path):
    """Recipe ingredients dict est JSONB-compatible."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
    assert len(recipe_chunks) >= 1

    for r in recipe_chunks:
        # Le text contient un ligne Ingredients: {...}
        # Verifier que le dict parse est serializable JSON
        import re
        for line in r.text.split("\n"):
            m = re.match(r"\s*ingredients:\s*(\{.*\})", line, re.IGNORECASE)
            if m:
                ing_dict = json.loads(m.group(1))
                # Tentative de serialisation JSONB (standard JSON)
                serialized = json.dumps(ing_dict, ensure_ascii=True)
                assert isinstance(serialized, str)


async def test_schema_item_damage_tiers_serializable(tmp_path: Path):
    """DamageTiers dict (weapon) est JSONB-compatible."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    weapon_chunks = [c for c in result.chunks if "weapon_melee" in c.text.lower()]
    assert len(weapon_chunks) >= 1

    for w in weapon_chunks:
        assert "DamageTiers:" in w.text or "damage_tiers:" in w.text.lower()
        # Extraire le DamageTiers JSON et verifier la serialisation
        import re
        for line in w.text.split("\n"):
            m = re.match(r"\s*DamageTiers:\s*(\[.*?\{.*\}.*?])", line)
            if m:
                tier_data = json.loads(m.group(1))
                json.dumps(tier_data, ensure_ascii=True)  # ne doit pas lever


async def test_schema_empty_result_valid(tmp_path: Path):
    """Dataset vide → ExtractionResult avec metadata valides (mais vides)."""
    base = tmp_path / "pz-wiki-data-empty"
    base.mkdir(parents=True, exist_ok=True)

    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=str(base))
    result = await proc.extract()

    # Metadata valides meme avec 0 chunks
    assert isinstance(result.metadata.get("categories_processed"), list)
    assert isinstance(result.metadata.get("total_entries"), int)
    assert result.metadata["total_entries"] >= 0
    assert isinstance(result.word_count, int)
    assert result.word_count == 0
    assert isinstance(result.file_hash, str)


async def test_schema_nested_json_deeply_compatible(tmp_path: Path):
    """Structures JSON profondes (nested lists/dicts) serializables."""
    data = {
        "items": {
            "complex_weapon": {
                "Name": "Complex Weapon",
                "Type": "weapon_melee",
                "DamageTiers": {
                    "common": 10,
                    "uncommon": {"min": 15, "max": 20},  # nested dict
                    "rare": [18, 22, 25],  # nested list
                },
            },
        },
        "recipes": {},
    }
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    weapon = next((c for c in result.chunks if "complex_weapon" in c.metadata.get("key", "")), None)
    assert weapon is not None

    # Le DamageTiers nested doit etre serializable JSON
    import re
    for line in weapon.text.split("\n"):
        m = re.match(r"\s*DamageTiers:\s*(\[.*?\{.*\}.*?])", line)
        if m:
            tier_data = json.loads(m.group(1))
            # Nested structure validation
            assert isinstance(tier_data, dict)
            assert "uncommon" in tier_data
            assert isinstance(tier_data["uncommon"], dict)
            assert "rare" in tier_data
            assert isinstance(tier_data["rare"], list)
            json.dumps(tier_data, ensure_ascii=True)


async def test_schema_processor_type_in_metadata(tmp_path: Path):
    """metadata.processor == 'wikijson'."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    assert result.metadata["processor"] == "wikijson"
    assert isinstance(result.metadata.get("source_data_size"), int)


async def test_schema_chunk_index_start_offset_valid(tmp_path: Path):
    """Chunk index et start_offset sont des entiers >= 0."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    for c in result.chunks:
        assert isinstance(c.index, int), f"index is {type(c.index)}, expected int"
        assert isinstance(c.start_offset, int), f"start_offset is {type(c.start_offset)}, expected int"
        assert c.index >= 0
        assert c.start_offset >= 0


async def test_schema_all_expected_collection_types_present(tmp_path: Path):
    """Tous les chunks ont metadata.type dans les types attendus."""
    data = _make_valid_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    valid_types = {"item", "recipe", "mob", "skill", "weapon", "crop",
                   "weather", "map", "building", "vehicle", "achievement", "poi"}
    for c in result.chunks:
        assert c.metadata["type"] in valid_types, (
            f"Unknown chunk type: {c.metadata['type']}"
        )
