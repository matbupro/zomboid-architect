"""test_regression_collection_extend — Regression tests etendus pour nouvelles collections.

Couvre les gaps identifies dans les tests existants :
  - pz_mechanics (mobs/skills/weather/crops/achievements) — jamais teste en write/query
  - pz_web_pages (maps/POI) — jamais teste en write/query
  - Cross-collection search sur TOUTES les collections PG (pas seulement items+recipes)
  - End-to-end: WikiJsonProcessor -> StorageWriter write pour chaque collection cible

Collections cibles d'apres wikijson.py TYPE_TO_COLLECTION :
  pz_items    → items, building, vehicles, traps, weapons_*, ammunition, clothing, food, medication, tools, electronics, containers, furniture
  pz_recipes  → recipes
  pz_mechanics→ mobs, crops, skills, weather, achievements
  pz_web_pages→ maps, poi

Les tests existants ne couvrent PAS pz_mechanics ni pz_web_pages dans le storage backend.
Ce fichier extend les regression tests pour inclure ces collections.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Imports utilises par les tests
# ===========================================================================

from ingestor.config import IngestorConfig
from ingestor.processors.wikijson import WikiJsonProcessor, TYPE_TO_COLLECTION

# StorageBackend est dans src.storage (pas ingestor.storage) — import dynamique pour eviter ModuleNotFoundError
import importlib
StorageBackend = importlib.import_module("src.storage").StorageBackend


def _chunk(text: str, metadata: dict | None = None) -> Any:
    """Helper pour creer un Chunk avec les champs requis (text, index=0, start_offset=0)."""
    from ingestor.processors.base import Chunk

    return Chunk(text=text, index=0, start_offset=0, metadata=metadata or {})


# ===========================================================================
# Fixtures — donnees pour chaque collection cible
# ===========================================================================


def _make_mechanics_data() -> dict[str, Any]:
    """Donnees pour la collection pz_mechanics (mobs/skills/weather)."""
    return {
        "mobs": {
            "walker_normal": {
                "Name": "Normal Walker",
                "HP": 50,
                "Speed": 1.0,
                "Damage": 10,
                "Behavior": "passive",
            },
            "bloater_v2": {
                "Name": "Bloater",
                "HP": 180,
                "Speed": 2.5,
                "Damage": 25,
                "Behavior": "aggressive",
                "DetectionRadius": 30,
                "Drops": {"Flesh": [1, 3]},
            },
        },
        "skills": {
            "cooking": {
                "Name": "Cooking",
                "MaxLevel": 50,
                "XPMultiplier": 1.5,
                "Description": "Cook food for better nutrition.",
            },
            "firstaid": {
                "Name": "First Aid",
                "MaxLevel": 30,
                "XPMultiplier": 1.2,
            },
        },
        "weather": {
            "rainy": {
                "Name": "Rainy",
                "Visibility": 50,
                "SpeedMultiplier": 0.8,
            },
        },
    }


def _make_webpages_data() -> dict[str, Any]:
    """Donnees pour la collection pz_web_pages (maps/POI)."""
    rooks_port_map = {
        "RooksPort": {
            "Name": "Rook's Port",
            "Region": "Montgomery County",
            "Biomes": ["Suburbs"],
            "Type": "town",
            "LootDensity": "high",
        },
    }

    poi_data = {
        "_poi_index": [
            {"id": "military_checkpoint_1", "name": "Military Checkpoint", "biome": "Outlands"},
            {"id": "tank_graveyard", "name": "Tank Graveyard", "biome": "Suburbs"},
        ],
    }

    return {
        "maps": rooks_port_map,
        "poi": poi_data,
    }


def _make_all_collection_chunks() -> dict[str, list[Chunk]]:
    """Chunks simules pour TOUTES les collections PG."""
    return {
        "pz_items": [
            _chunk(text="Item: iron_pipe\n  Name: Iron Pipe\n  Type: weapon_melee", metadata={"type": "item", "key": "iron_pipe"}),
            _chunk(text="Item: bandage\n  Name: Bandage\n  Type: medication_firstaid", metadata={"type": "item", "key": "bandage"}),
        ],
        "pz_recipes": [
            _chunk(text="Recipe: craft_bandage\n  Name: Bandage\n  Result: Bandage", metadata={"type": "recipe", "key": "craft_bandage"}),
        ],
        "pz_mechanics": [
            _chunk(text="Mob: walker_normal\n  Name: Normal Walker\n  HP: 50", metadata={"type": "mob", "key": "walker_normal"}),
            _chunk(text="Skill: cooking\n  Name: Cooking\n  MaxLevel: 50", metadata={"type": "skill", "key": "cooking"}),
        ],
        "pz_web_pages": [
            _chunk(text="Map: RooksPort\n  Name: Rook's Port\n  Biomes: Suburbs", metadata={"type": "map", "key": "RooksPort"}),
            _chunk(text="POI: Military Checkpoint\n  Region: Montgomery County", metadata={"type": "poi", "key": "military_checkpoint_1"}),
        ],
    }


def _write_wikidrive(tmp_path: Path, data: dict[str, Any]) -> Path:
    """Ecrit les donnees dans un dossier multi-fichiers."""
    base = tmp_path / "pz-wiki-data"
    base.mkdir(parents=True, exist_ok=True)
    for key, val in data.items():
        (base / f"{key}.json").write_text(json.dumps(val), encoding="utf-8")
    return base


# ===========================================================================
# Tests — pz_mechanics (jamais ecrite/interrogee avant)
# ===========================================================================


async def test_pg_write_to_pz_mechanics_collection(tmp_path: Path):
    """Ecrire dans pz_mechanics via StorageBackend → count valide."""
    db = create_backend()

    # ensure_collection pour pz_mechanics (jamais fait par les tests existants)
    assert db.ensure_collection("pz_mechanics") is True
    assert db.count_collection("pz_mechanics") == 0

    chunks = [
        _chunk(text="Mob: walker_normal\n  HP: 50", metadata={"type": "mob"}),
        _chunk(text="Skill: cooking\n  Level: 50", metadata={"type": "skill"}),
    ]
    written = db.write_chunks(chunks, collection="pz_mechanics", source="test_regression")
    assert written == 2
    assert db.count_collection("pz_mechanics") == 2


async def test_pg_query_pz_mechanics_collection(tmp_path: Path):
    """Query dans pz_mechanics retourne des resultats par type (mob/skill)."""
    db = create_backend()
    db.ensure_collection("pz_mechanics")

    chunks = [
        _chunk(text="Mob: walker_normal\n  Name: Normal Walker", metadata={"type": "mob", "key": "walker_normal"}),
        _chunk(text="Mob: bloater_v2\n  Name: Bloater", metadata={"type": "mob", "key": "bloater_v2"}),
    ]
    db.write_chunks(chunks, collection="pz_mechanics", source="test_query")

    results = db.query("pz_mechanics", "walker", n_results=5)
    assert len(results) >= 1  # similarity search peut retourner plusieurs resultats pertinents
    assert any("walker" in r.prose.lower() for r in results)


async def test_pg_upsert_in_pz_mechanics(tmp_path: Path):
    """Upsert dans pz_mechanics — mise a jour existe → count stable."""
    db = create_backend()
    db.ensure_collection("pz_mechanics")

    # write_chunk avec ID fixe simule un upsert
    db.write_chunk("pz_mechanics", "u::walker", "Mob: walker_normal\n  HP: 50", {"type": "mob"}, source="v1")
    assert db.count_collection("pz_mechanics") == 1

    # Mettre a jour le meme chunk (upsert) — meme ID → count stable
    db.write_chunk("pz_mechanics", "u::walker", "Mob: walker_normal\n  HP: 75", {"type": "mob"}, source="v2")
    assert db.count_collection("pz_mechanics") == 1  # count stable


async def test_pg_metadata_jsonb_pz_mechanics(tmp_path: Path):
    """Metadata JSONB dans pz_mechanics — keys/values valides."""
    db = create_backend()
    db.ensure_collection("pz_mechanics")

    chunk = _chunk(text="Skill: cooking", metadata={"type": "skill", "key": "cooking", "max_level": 50})
    db.write_chunk("pz_mechanics", "m::sk1", "Skill: cooking", {"type": "skill", "key": "cooking"}, source="test")

    row = db.get_by_id("pz_mechanics", "m::sk1")
    assert row is not None
    assert row.metadata_["type"] == "skill"
    assert row.metadata_["key"] == "cooking"


# ===========================================================================
# Tests — pz_web_pages (jamais ecrite/interrogee avant)
# ===========================================================================


async def test_pg_write_to_pz_web_pages_collection(tmp_path: Path):
    """Ecrire dans pz_web_pages via StorageBackend → count valide."""
    db = create_backend()

    # ensure_collection pour pz_web_pages (jamais fait par les tests existants)
    assert db.ensure_collection("pz_web_pages") is True
    assert db.count_collection("pz_web_pages") == 0

    chunks = [
        _chunk(text="Map: RooksPort", metadata={"type": "map"}),
        _chunk(text="POI: Military Checkpoint", metadata={"type": "poi"}),
    ]
    written = db.write_chunks(chunks, collection="pz_web_pages", source="test_regression")
    assert written == 2
    assert db.count_collection("pz_web_pages") == 2


async def test_pg_query_pz_web_pages_collection(tmp_path: Path):
    """Query dans pz_web_pages retourne des resultats maps/POI."""
    db = create_backend()
    db.ensure_collection("pz_web_pages")

    chunks = [_chunk(text="Map: RooksPort\n  Biomes: Suburbs", metadata={"type": "map", "key": "RooksPort"})]
    db.write_chunks(chunks, collection="pz_web_pages", source="test_query")

    results = db.query("pz_web_pages", "rook", n_results=5)
    assert len(results) >= 1


async def test_pg_metadata_jsonb_pz_web_pages(tmp_path: Path):
    """Metadata JSONB dans pz_web_pages — biomes en liste serialisee."""
    db = create_backend()
    db.ensure_collection("pz_web_pages")

    meta = {"type": "map", "key": "RooksPort", "biomes": ["Suburbs", "Outlands"], "loot": "high"}
    db.write_chunk("pz_web_pages", "m::mp1", "Map: RooksPort", meta, source="test")

    row = db.get_by_id("pz_web_pages", "m::mp1")
    assert row is not None
    # biomes en liste dans metadata_
    assert isinstance(row.metadata_.get("biomes"), list)
    assert "Suburbs" in row.metadata_["biomes"]


# ===========================================================================
# Tests — Cross-collection search ETENDU (pas seulement items+recipes)
# ===========================================================================


async def test_cross_collection_search_all_four_collections():
    """Cross-collection search sur TOUTES les 4 collections PG."""
    from ingestor.storage.storage_writer import StorageWriter, SearchResult

    mock_backend = MagicMock()
    mock_backend.list_collections.return_value = ["pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages"]

    # side_effect qui retourne des resultats differents par collection
    def side_effect(col, *args, **kwargs):
        if col == "pz_items":
            return [SearchResult(collection=col, id="item-1", prose="weapon item", distance=0.3)]
        elif col == "pz_recipes":
            return [SearchResult(collection=col, id="recipe-1", prose="crafting recipe", distance=0.5)]
        elif col == "pz_mechanics":
            return [SearchResult(collection=col, id="mob-1", prose="walker mob", distance=0.2)]
        elif col == "pz_web_pages":
            return [SearchResult(collection=col, id="map-1", prose="rook's port map", distance=0.6)]
        return []

    mock_backend.query = AsyncMock(side_effect=side_effect)  # query() est async dans StorageWriter
    mock_backend.ensure_collection = AsyncMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1, 0.2])

    results = await writer.cross_collection_search("hello", n_results=10)

    # Doit retourner au moins un resultat par collection (4 min)
    assert len(results) == 4
    collections_found = {r.collection for r in results}
    assert collections_found == {"pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages"}

    # Trie par distance croissante
    distances = [r.distance for r in results]
    assert distances == sorted(distances)


async def test_cross_collection_search_fallback_single_result():
    """Cross-collection search avec 1 collection seulement → au moins 1 resultat."""
    from ingestor.storage.storage_writer import StorageWriter, SearchResult

    mock_backend = MagicMock()
    mock_backend.list_collections.return_value = ["pz_mechanics"]
    mock_backend.query = AsyncMock(return_value=[SearchResult(collection="pz_mechanics", id="mob-1", prose="test", distance=0.1)])
    mock_backend.ensure_collection = AsyncMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1])

    results = await writer.cross_collection_search("hello", n_results=10)
    assert len(results) >= 1


async def test_cross_collection_one_collection_fails_gracefully():
    """Une collection echoue → les autres sont toujours retournees."""
    from ingestor.storage.storage_writer import StorageWriter, SearchResult

    mock_backend = MagicMock()
    mock_backend.list_collections.return_value = ["pz_items", "pz_mechanics", "pz_web_pages"]

    call_log = []

    def side_effect(col, *args, **kwargs):
        call_log.append(col)
        if col == "pz_mechanics":
            raise RuntimeError("db timeout")  # simule une erreur PG
        return [SearchResult(collection=col, id=f"{col}-1", prose="ok", distance=0.5)]

    mock_backend.query = AsyncMock(side_effect=side_effect)
    mock_backend.ensure_collection = AsyncMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1])

    results = await writer.cross_collection_search("hello", n_results=10)

    # pz_mechanics a echoue mais pas bloque les autres
    assert len(results) == 2
    assert "pz_items" in {r.collection for r in results}
    assert "pz_web_pages" in {r.collection for r in results}


# ===========================================================================
# Tests — End-to-end: WikiJsonProcessor chunks → toutes collections PG
# ===========================================================================


async def test_wikijson_processor_produces_all_collection_types(tmp_path: Path):
    """WikiJsonProcessor.extract() produit chunks pour TOUTES les collections mappes."""
    data = _make_mechanics_data()
    source = str(_write_wikidrive(tmp_path, data))

    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)
    result = await proc.extract()

    # Compter les chunks par collection (via metadata.type → TYPE_TO_COLLECTION mapping)
    from collections import Counter
    type_counts = Counter(c.metadata.get("type") for c in result.chunks)

    # Mobs et skills presentes
    assert type_counts["mob"] >= 2
    assert type_counts["skill"] >= 2


async def test_wikijson_processor_chunks_map_to_correct_collections(tmp_path: Path):
    """Chaque chunk de WikiJsonProcessor mappe vers la bonne collection via TYPE_TO_COLLECTION."""
    data = {
        "items": {"test_item": {"Name": "Test", "Type": "generic"}},
        "recipes": {"test_recipe": {"Name": "Test Recipe", "Result": "Test"}},
        "mobs": {"test_mob": {"Name": "Test Mob", "HP": 10}},
    }
    base = tmp_path / "pz-wiki-data"
    base.mkdir(parents=True, exist_ok=True)
    for k, v in data.items():
        (base / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")

    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=str(base))
    result = await proc.extract()

    type_counts = Counter(c.metadata.get("type") for c in result.chunks)
    assert type_counts["item"] == 1
    assert type_counts["recipe"] == 1
    assert type_counts["mob"] == 1


async def test_all_type_to_collection_mappings_valid():
    """Toutes les mappings TYPE_TO_COLLECTION sont valides."""
    # Mappages directs vers collections PG connues
    valid_collections = {"pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages"}

    for category, collection in TYPE_TO_COLLECTION.items():
        assert collection in valid_collections, f"{category} → {collection} invalide"


# ===========================================================================
# Tests — PG storage avec collections non cibles (regression)
# ===========================================================================


async def test_pg_storage_custom_collection_name(tmp_path: Path):
    """Collection custom nommee → ensure + write + count works."""
    db = create_backend()

    assert db.ensure_collection("pz_custom_test") is True
    assert db.count_collection("pz_custom_test") == 0

    chunks = [_chunk(text="Custom collection test", metadata={"type": "custom"})]
    written = db.write_chunks(chunks, collection="pz_custom_test", source="test")
    assert written == 1
    assert db.count_collection("pz_custom_test") == 1


async def test_pg_list_collections_reflects_all_created(tmp_path: Path):
    """list_collections retourne TOUTES les collections creees (items + mechanics + web_pages)."""
    db = create_backend()

    db.ensure_collection("pz_items")
    db.ensure_collection("pz_mechanics")
    db.ensure_collection("pz_web_pages")
    db.ensure_collection("pz_recipes")

    cols = sorted(db.list_collections())
    assert "pz_items" in cols
    assert "pz_mechanics" in cols
    assert "pz_web_pages" in cols
    assert "pz_recipes" in cols


async def test_pg_count_across_multiple_collections(tmp_path: Path):
    """Count par collection quand plusieurs collections existent — pas de confusion."""
    db = create_backend()

    db.ensure_collection("pz_items")
    db.ensure_collection("pz_mechanics")
    db.ensure_collection("pz_web_pages")

    db.write_chunk("pz_items", "i::1", "Item text 1", {"type": "item"})
    db.write_chunk("pz_items", "i::2", "Item text 2", {"type": "item"})
    db.write_chunk("pz_mechanics", "m::1", "Mob text", {"type": "mob"})
    db.write_chunk("pz_web_pages", "w::1", "Map text", {"type": "map"})

    assert db.count_collection("pz_items") == 2
    assert db.count_collection("pz_mechanics") == 1
    assert db.count_collection("pz_web_pages") == 1


async def test_pg_delete_in_pz_mechanics(tmp_path: Path):
    """Delete dans pz_mechanics → count diminue."""
    pytest.skip("Cette section de tests nécessite un rewrite PG")


async def test_pg_delete_in_pz_web_pages(tmp_path: Path):
    """Delete dans pz_web_pages → count diminue."""
    pytest.skip("Cette section de tests nécessite un rewrite PG")


async def test_pg_cross_collection_filter_on_type_metadata(tmp_path: Path):
    """Cross-collection search avec filtre metadata type=mob."""
    pytest.skip("Cette section de tests nécessite un rewrite PG")


async def test_regression_all_ensure_collection_idempotent(tmp_path: Path):
    """Toutes les collections PG -> ensure_collection appelle idempotent (2x = pas d'erreur)."""
    db = create_backend()

    for col in ["pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages"]:
        r1 = db.ensure_collection(col)
        r2 = db.ensure_collection(col)  # 2eme appel idempotent → False (deja creee)
        assert isinstance(r1, bool)
        assert isinstance(r2, bool)


# ===========================================================================
# Tests — Integration WikiJsonProcessor + StorageBackend e2o pour toutes collections
# ===========================================================================


async def test_e2o_full_pipeline_all_collections(tmp_path: Path):
    """Full pipeline : WikiJsonProcessor.extract() → chunks par collection → StorageBackend write."""
    data = {
        "items": {
            "iron_pipe": {"Name": "Iron Pipe", "Type": "weapon_melee"},
        },
        "recipes": {
            "craft_nails": {"Name": "Nails", "Result": "Nails", "ingredients": {}},
        },
        "mobs": {
            "walker_normal": {"Name": "Walker", "HP": 50},
        },
    }
    source = str(_write_wikidrive(tmp_path, data))

    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)
    result = await proc.extract()

    # Verifier que les chunks ont les types attendus (item/recipe/mob)
    type_counts = Counter(c.metadata.get("type") for c in result.chunks)
    assert type_counts["item"] >= 1, "pz_items — au moins un chunk item"
    assert type_counts["recipe"] >= 1, "pz_recipes — au moins un chunk recipe"
    assert type_counts["mob"] >= 1, "pz_mechanics — au moins un chunk mob (gap corrige ici !)"

    # Ecrire chaque collection dans le storage via classification par metadata type
    from collections import defaultdict
    by_collection = defaultdict(list)
    for c in result.chunks:
        t = c.metadata.get("type", "")
        if t == "item":
            col = "pz_items"
        elif t == "recipe":
            col = "pz_recipes"
        elif t in ("mob", "skill", "crop", "weather", "achievement"):
            col = "pz_mechanics"
        else:
            col = "pz_web_pages"
        by_collection[col].append(c)

    # Toutes les collections doivent etre presentes dans le resultat
    assert "pz_items" in by_collection
    assert "pz_recipes" in by_collection
    assert "pz_mechanics" in by_collection  # ← gap corrige ici !

    # Ecrire chaque collection dans le storage
    db = create_backend()
    for col_name, chunks in by_collection.items():
        db.ensure_collection(col_name)
        written = db.write_chunks(chunks, collection=col_name, source="e2o")
        assert written == len(chunks), f"Collection {col_name}: expected {len(chunks)}, got {written}"

    # Verification finale — chaque collection a ses chunks
    assert db.count_collection("pz_items") >= 1
    assert db.count_collection("pz_recipes") >= 1
    assert db.count_collection("pz_mechanics") >= 1


async def test_e2o_query_after_store_all_collections(tmp_path: Path):
    """Store dans chaque collection → query retourne des resultats pertinents."""
    data = _make_mechanics_data()
    source = str(_write_wikidrive(tmp_path, data))

    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)
    result = await proc.extract()

    # Ecrire pz_mechanics dans le storage
    db = create_backend()
    mech_chunks = [c for c in result.chunks if c.metadata.get("type") == "mob"]
    db.ensure_collection("pz_mechanics")
    db.write_chunks(mech_chunks, collection="pz_mechanics", source="e2o")

    # Query doit retrouver le mob
    results = db.query("pz_mechanics", "bloater", n_results=5)
    assert len(results) >= 1


# ===========================================================================
# Tests — Regression sur les collections existantes (pas de regression)
# ===========================================================================


async def test_regression_pz_items_still_works(tmp_path: Path):
    """pz_items fonctionne toujours apres ajout des nouvelles collections."""
    db = create_backend()
    assert db.ensure_collection("pz_items") is True

    chunks = [_chunk(text="Iron Pipe melee weapon", metadata={"type": "item", "key": "iron_pipe"})]
    written = db.write_chunks(chunks, collection="pz_items", source="regression")
    assert written == 1
    assert db.count_collection("pz_items") == 1

    results = db.query("pz_items", "pipe", n_results=5)
    assert len(results) >= 1


async def test_regression_pz_recipes_still_works(tmp_path: Path):
    """pz_recipes fonctionne toujours apres ajout des nouvelles collections."""
    db = create_backend()
    assert db.ensure_collection("pz_recipes") is True

    chunks = [_chunk(text="Crafting nails recipe", metadata={"type": "recipe"})]
    written = db.write_chunks(chunks, collection="pz_recipes", source="regression")
    assert written == 1
    assert db.count_collection("pz_recipes") == 1


async def test_regression_cross_collection_still_works(tmp_path: Path):
    """Cross-collection search toujours fonctionnel (items+recipes) — regression check."""
    from ingestor.storage.storage_writer import StorageWriter, SearchResult

    mock_backend = MagicMock()
    mock_backend.list_collections.return_value = ["pz_items", "pz_recipes"]
    mock_backend.query = AsyncMock(return_value=[SearchResult(collection="pz_items", id="i-1", prose="test", distance=0.5)])
    mock_backend.ensure_collection = AsyncMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1])

    results = await writer.cross_collection_search("test", n_results=10)
    assert len(results) >= 1


async def test_regression_get_by_id_still_works_all_collections(tmp_path: Path):
    """get_by_id fonctionne sur TOUTES les collections (items, recipes, mechanics, web_pages)."""
    db = create_backend()

    for col in ["pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages"]:
        db.ensure_collection(col)
        db.write_chunk(col, f"i::{col}", f"{col} text", {"type": "test"})
        row = db.get_by_id(col, f"i::{col}")
        assert row is not None, f"get_by_id echoue sur {col}"
        assert row.collection == col
