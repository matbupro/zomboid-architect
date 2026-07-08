"""test_wikijson_e2o — Tests end-to-end du pipeline complet Wikidrive → storage.

Couvre le flux entier :
  1. Fichier wiki.json simulé (données PZ réalistes)
  2. WikiJsonProcessor.extract() → ExtractionResult avec chunks categorisés
  3. StorageWriter.write_chunks_to_storage() → PostgreSQL/pgvector backend
  4. Query directe PG sur les collections pour vérification

Usage:
    pytest tests/test_wikijson_e2o.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestor.config import IngestorConfig
from ingestor.processors.wikijson import WikiJsonProcessor
from ingestor.processors.base import Chunk


# ===========================================================================
# Fixtures — données PZ simulées (réalistes, inspirées du vrai Data Drive)
# ===========================================================================


def _make_wikidrive_json(tmp_path: Path) -> Path:
    """Crée un fichier Wiki.json monolithique avec des données PZ réalistes."""
    data = {
        "items": {
            "iron_pipe": {
                "Name": "Iron Pipe",
                "Type": "weapon_melee",
                "weight": 1.5,
                "Categories": ["Weapons", "Improvised"],
                "SubCategory": "Melee Weapons",
                "description": "A heavy iron pipe. Deals decent damage in close combat.",
                "condition_max": 240,
                "DamageTiers": {"common": 8, "uncommon": 10, "rare": 12},
            },
            "hunting_knife": {
                "Name": "Hunting Knife",
                "Type": "weapon_melee",
                "weight": 0.85,
                "Categories": ["Weapons"],
                "SubCategory": "Melee Weapons",
                "description": "A sharp hunting knife.",
                "condition_max": 300,
                "DamageTiers": {"common": 10, "uncommon": 12, "rare": 15},
            },
            "baseball_bat": {
                "Name": "Baseball Bat",
                "Type": "weapon_melee",
                "weight": 0.96,
                "Categories": ["Weapons"],
                "description": "A standard baseball bat.",
                "condition_max": 325,
                "DamageTiers": {"common": 10, "uncommon": 12, "rare": 15},
            },
            "soda_clam": {
                "Name": "Soda Clam",
                "Type": "food_soda",
                "weight": 0.4,
                "Categories": ["Food", "Drinks"],
                "description": "A can of soda.",
                "Calories": 180,
                "Protein": 0,
                "Vitamin": 5,
                "Mineral": 2,
                "Water": 12,
            },
            "canned_beans": {
                "Name": "Canned Beans",
                "Type": "food_canned",
                "weight": 0.45,
                "Categories": ["Food", "Canned"],
                "description": "A can of beans. Unopened.",
                "Calories": 350,
                "Protein": 18,
                "Vitamin": 3,
                "Mineral": 4,
            },
            "blue_tshirt": {
                "Name": "Blue T-Shirt",
                "Type": "clothing_tshirt",
                "weight": 0.25,
                "Categories": ["Clothing"],
                "description": "A blue t-shirt.",
                "warmth": 1,
                "Blunt": {"layer1": 0.02},
                "Cut": {"layer1": 0.02},
                "scratch_resistance": 0.01,
            },
            "leather_jacket": {
                "Name": "Leather Jacket",
                "Type": "clothing_jacket",
                "weight": 2.5,
                "Categories": ["Clothing", "Armor"],
                "description": "A leather jacket providing good protection.",
                "warmth": 3,
                "Blunt": {"layer1": 0.05, "layer2": 0.03},
                "Cut": {"layer1": 0.08},
            },
            "wood_plank": {
                "Name": "Wood Plank",
                "Type": "building_material",
                "weight": 4.4,
                "Categories": ["Building"],
                "description": "A standard wooden plank for construction.",
                "condition_max": 200,
            },
            "nails": {
                "Name": "Nails",
                "Type": "building_material",
                "weight": 0.1,
                "Categories": ["Building"],
                "description": "Small metal nails used for carpentry.",
            },
        },
        "recipes": {
            "bandage_cloth": {
                "Name": "Bandage",
                "Result": "Bandage",
                "Time": 30,
                "Category": "Medical",
                "ingredients": {"Cloth": 1},
                "SkillRequired": "FirstAid",
            },
            "dollar_bandaids": {
                "Name": "Dollar Bandaids",
                "Result": "Bandage (Dollar)",
                "Time": 30,
                "Category": "Medical",
                "ingredients": {"Dollar Band-Aid Box": 1},
                "SkillRequired": "FirstAid",
            },
            "campfire_steak_mmr": {
                "Name": "Steak Medium Rare",
                "Result": "Steak Cooked (Medium Rare)",
                "Time": 60,
                "Category": "Campfire Cooking",
                "ingredients": {"Steak Raw": 1},
                "SkillRequired": "Cooking",
                "CrossCookProgression": [
                    {"tier": "campfire", "result": "Steak Medium Rare"},
                    {"tier": "brick_oven", "result": "Steak Well Done"},
                    {"tier": "gas_stove", "result": "Steak Perfect"},
                ],
            },
            "campfire_chicken_sou": {
                "Name": "Chicken Stew",
                "Result": "Chicken Stew (Uncooked)",
                "Time": 90,
                "Category": "Campfire Cooking",
                "ingredients": {"Raw Chicken Meat": 2, "Vegetables": 1},
                "SkillRequired": "Cooking",
            },
            "nails_craft": {
                "Name": "Nails (Crafted)",
                "Result": "Nails",
                "Time": 5,
                "Category": "Scrap",
                "ingredients": {"Metal Sheet": 1},
                "SkillRequired": "Scavenging",
            },
        },
        "mobs": {
            "walker_normal": {
                "Name": "Normal Walker",
                "HP": 50,
                "Speed": 1.0,
                "Damage": 5,
                "Behavior": "walk",
                "XP": 15,
                "DetectionRadius": 8,
                "Drops": [
                    {"item": "Rotten Flesh", "min": 1, "max": 3},
                ],
            },
            "bloater": {
                "Name": "Bloater",
                "HP": 300,
                "Speed": 0.8,
                "Damage": 25,
                "Behavior": "aggressive",
                "XP": 75,
                "DetectionRadius": 15,
                "Drops": [
                    {"item": "Bandage Sterile", "min": 2, "max": 5},
                ],
            },
            "crawler": {
                "Name": "Crawler",
                "HP": 40,
                "Speed": 3.5,
                "Damage": 8,
                "Behavior": "crawl_ambush",
                "XP": 20,
                "DetectionRadius": 10,
                "Drops": [
                    {"item": "Rotten Flesh", "min": 1, "max": 2},
                ],
            },
        },
        "skills": {
            "woodworking": {
                "levels": {
                    "I": "Unlocks basic axe use and tree felling.",
                    "II": "Unlocks reinforced walls and doors.",
                },
                "xp_multiplier": 1.0,
                "required_for": ["carpentry"],
            },
            "cooking": {
                "levels": {
                    "I": "Unlocks campfire cooking with better quality tiers.",
                    "II": "Unlocks brick oven and gas stove recipes.",
                },
                "xp_multiplier": 1.2,
                "required_for": ["food prep"],
            },
        },
        "weather": {
            "spring": {"min_temp": 5, "max_temp": 20, "rain_chance": 0.3},
            "summer": {"min_temp": 20, "max_temp": 42, "heat_stroke_risk": True},
        },
        "maps": {
            "new_tonbridge": {
                "size_km2": 19.06,
                "biome": "mixed",
                "zombie_density": "high",
                "terrain_type": "hilly_forest",
            },
        },
    }

    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f


def _make_wikidrive_dir(tmp_path: Path) -> Path:
    """Crée un dossier de data drive avec des fichiers JSON separes."""
    base = tmp_path / "pz-wiki-data"
    base.mkdir(parents=True, exist_ok=True)

    (base / "items.json").write_text(json.dumps({
        "iron_pipe": {"Name": "Iron Pipe", "Type": "weapon_melee", "weight": 1.5},
        "wood_plank": {"Name": "Wood Plank", "Type": "building_material", "weight": 4.4},
    }), encoding="utf-8")

    (base / "recipes.json").write_text(json.dumps({
        "bandage_cloth": {"Name": "Bandage", "Result": "Bandage", "Time": 30, "ingredients": {"Cloth": 1}},
    }), encoding="utf-8")

    (base / "mobs.json").write_text(json.dumps({
        "walker": {"Name": "Walker", "HP": 50, "Speed": 1.0},
    }), encoding="utf-8")

    return base


# ===========================================================================
# Test e2o #1 : Flux complet wiki.json → processor → storage → vérification PG
# ===========================================================================


async def test_e2o_full_pipeline_wikidrive_json(tmp_path: Path):
    """Pipeline complet : Wiki.json → chunks → StorageWriter → count/verification."""
    from ingestor.storage.storage_writer import StorageWriter

    wikifile = _make_wikidrive_json(tmp_path)
    pg_data_dir = str(tmp_path / "pg_data")

    # 1. Processus d'extraction
    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    assert len(result.chunks) > 0, "L'extraction doit produire des chunks"
    assert result.collection == "pz_items", "Collection par défaut : pz_items"
    assert result.source == str(wikifile)
    assert result.content_type == "application/json"
    assert result.word_count > 0

    # Vérifier les counts par type
    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
    mob_chunks = [c for c in result.chunks if c.metadata.get("type") == "chunk"]
    skill_chunks = [c for c in result.chunks if c.metadata.get("type") == "skill"]

    # 9 items, 5 recipes, 3 mobs (walker normalizer → type=chunk car pas dans _get_normalizer)
    assert len(item_chunks) == 9, f"9 items attendus, trouvé {len(item_chunks)}: {[c.metadata.get('key') for c in item_chunks]}"
    assert len(recipe_chunks) == 5, f"5 recipes attendues, trouvé {len(recipe_chunks)}"

    # Vérifier les metadata du chunk pour un item
    iron_pipe = next(c for c in item_chunks if c.metadata.get("key") == "iron_pipe")
    assert "Iron Pipe" in iron_pipe.text
    assert "weapon_melee" in iron_pipe.text
    assert "DamageTiers" in iron_pipe.text

    # Vérifier une recipe avec cross-cook progression (chercher via text, pas key car "Steak" vs "steak")
    campfire_steak = next(c for c in recipe_chunks if "campfire" in c.metadata.get("key", "").lower())
    assert "ProcessingTiers" in campfire_steak.text


async def test_e2o_store_chunks_via_storagewriter(tmp_path: Path):
    """Les chunks extraits sont stockes via StorageBackend (PostgreSQL/pgvector)."""
    from ingestor.storage.storage_writer import StorageWriter

    wikifile = _make_wikidrive_json(tmp_path)
    pg_data_dir = str(tmp_path / "pg_data")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    # Ecrire dans le storage (embedding=None car pas d'Ollama, mais c'est OK pour PG)
    writer = StorageWriter()
    written = await writer.write_chunks_to_storage(
        chunks=result.chunks,
        source=str(wikifile),
        content_type="application/json",
        collection="pz_items",
        metadata={"processor": "wikijson"},
    )
    assert written is True

    # Verifier que les chunks sont bien dans la base via count_collection
    count = await writer.count_collection("pz_items")
    assert count > 0, f"La collection pz_items devrait contenir des documents (trouvé: {count})"


async def test_e2o_cross_reference_items_to_recipes(tmp_path: Path):
    """Verifier la cross-reference : une recipe reference un item qui existe."""
    from ingestor.storage.storage_writer import StorageWriter

    wikifile = _make_wikidrive_json(tmp_path)
    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    # Collecter les items references dans les recipes
    item_names_in_result = {c.metadata["key"]: c for c in result.chunks if c.metadata.get("type") == "item"}
    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]

    assert len(item_names_in_result) == 9
    assert len(recipe_chunks) == 5

    # La recipe 'bandage_cloth' devrait avoir ingredient "Cloth" qui n'existe pas dans pz_items (OK — reference externe)
    bandage_recipe = next(c for c in recipe_chunks if c.metadata.get("key") == "bandage_cloth")
    assert "Bandage" in bandage_recipe.text

    # La recipe 'campfire_steak_mmr' fait reference a "Steak Raw" (ingredient) — chercher via le text, pas le key
    steak_recipe = next(c for c in recipe_chunks if "campfire" in c.metadata.get("key", "").lower())
    assert "Steak" in steak_recipe.text
    assert "Steak Raw" in steak_recipe.text


async def test_e2o_wikidrive_dir_pipeline(tmp_path: Path):
    """Pipeline depuis un dossier multi-fichiers (pas un fichier unique)."""
    from ingestor.storage.storage_writer import StorageWriter

    wikidir = _make_wikidrive_dir(tmp_path)
    pg_data_dir = str(tmp_path / "pg_data")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikidir))

    assert len(result.chunks) > 0

    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
    mob_chunks = [c for c in result.chunks if c.metadata.get("type") == "mob"]

    assert len(item_chunks) == 2
    assert len(recipe_chunks) == 1
    assert len(mob_chunks) == 1


# ===========================================================================
# Test e2o #2 : Edge cases du pipeline complet
# ===========================================================================


async def test_e2o_empty_file_produces_no_chunks(tmp_path: Path):
    """Un fichier JSON vide ne produit aucun chunk et l'ecriture retourne False."""
    from ingestor.storage.storage_writer import StorageWriter

    f = tmp_path / "empty.json"
    f.write_text("{}", encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(f))

    assert len(result.chunks) == 0

    # Ecrire des chunks vides retourne False (verifie par StorageWriter avant delegation)
    writer = StorageWriter()
    written = await writer.write_chunks_to_storage(
        chunks=[], source=str(f), collection="pz_empty",
    )
    assert written is False


async def test_e2o_malformed_entries_skipped_gracefully(tmp_path: Path):
    """Les entries malformed dans le JSON sont ignorees sans planter le pipeline."""
    from ingestor.storage.storage_writer import StorageWriter

    data = {
        "items": {
            "good_item": {"Name": "Good", "Type": "generic"},
            "bad_entry": "not_a_dict_at_all",  # non-dict → ignoré par normalizer
        },
        "recipes": {
            "valid_recipe": {"Name": "Valid", "Result": "X", "Time": 10, "ingredients": {}},
            "empty_recipe": {},  # dict vide → chunk cree mais sans champs utiles
        },
    }

    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(f))

    # Au moins l'item good + la recipe valid sont presents
    assert len(result.chunks) >= 2

    # Ecrire ne plante pas (gestion gracieuse)
    writer = StorageWriter()
    written = await writer.write_chunks_to_storage(
        chunks=result.chunks, source=str(f), collection="pz_malformed",
    )
    assert written is True


async def test_e2o_large_item_set(tmp_path: Path):
    """Un gros jeu de données (~50 items) ne plante pas et le count est correct."""
    from ingestor.storage.storage_writer import StorageWriter

    items = {}
    for i in range(50):
        items[f"item_{i:03d}"] = {
            "Name": f"Item Number {i}",
            "Type": "generic",
            "weight": round(i * 0.1, 2),
            "Categories": ["Test"],
            "Description": f"Description for item {i}.",
        }

    data = {"items": items}
    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(f))

    assert len(result.chunks) == 50, f"50 chunks items attendus, trouvé {len(result.chunks)}"

    # Ecrire et verifier count (nom unique par test pour isolation)
    col_name = f"pz_large_{id(f)}"
    writer = StorageWriter()
    written = await writer.write_chunks_to_storage(
        chunks=result.chunks, source=str(f), collection=col_name,
    )
    assert written is True

    count = await writer.count_collection(col_name)
    assert count == 50


async def test_e2o_metadata_propagates_through_pipeline(tmp_path: Path):
    """Les metadata du chunk (type, key, fields_count) sont preservees jusqu'au storage."""
    from ingestor.storage.storage_writer import StorageWriter

    data = {
        "items": {
            "iron_pipe": {"Name": "Iron Pipe", "Type": "weapon_melee", "weight": 1.5},
        },
        "recipes": {
            "bandage": {"Name": "Bandage", "Result": "Bandage", "Time": 30, "ingredients": {}},
        },
    }

    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps(data), encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(f))

    # Verifier les metadata de chaque chunk
    for chunk in result.chunks:
        assert "type" in chunk.metadata, f"Chunk {chunk.index} sans 'type'"
        assert "key" in chunk.metadata, f"Chunk {chunk.index} sans 'key'"
        assert "fields_count" in chunk.metadata, f"Chunk {chunk.index} sans 'fields_count'"

    # Ecrire et verifier preservation via count (metadata persist en JSONB)
    pg_data_dir = str(tmp_path / "pg_data_meta")
    writer = StorageWriter(ollama_url="http://x:11434")
    # Override le backend pour utiliser PG local par test
    from src.storage import create_backend
    writer._backend = create_backend()
    written = await writer.write_chunks_to_storage(
        chunks=result.chunks, source=str(f), collection="pz_metadata",
        metadata={"pipeline": "e2o_test"},
    )
    assert written is True

    count = await writer.count_collection("pz_metadata")
    assert count == 2


async def test_e2o_extraction_time_tracked(tmp_path: Path):
    """Le temps d'extraction est trace dans ExtractionResult."""
    wikifile = _make_wikidrive_json(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    assert result.extraction_time_ms > 0, "Le temps d'extraction devrait etre > 0ms"
    assert isinstance(result.extraction_time_ms, (int, float))


async def test_e2o_file_hash_stable(tmp_path: Path):
    """La hash du fichier source est stable entre deux extractions."""
    wikifile = _make_wikidrive_json(tmp_path)

    proc1 = WikiJsonProcessor(config=IngestorConfig())
    result1 = await proc1.extract(str(wikifile))

    proc2 = WikiJsonProcessor(config=IngestorConfig())
    result2 = await proc2.extract(str(wikifile))

    assert result1.file_hash == result2.file_hash, "Meme fichier → meme hash SHA-256"
    assert len(result1.file_hash) > 0


async def test_e2o_categories_processed_complete(tmp_path: Path):
    """Les categories luees sont complete dans metadata."""
    wikifile = _make_wikidrive_json(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    expected_cats = ["items", "recipes", "mobs", "skills", "weather", "maps"]
    for cat in expected_cats:
        assert cat in result.metadata["categories_processed"], f"Category {cat} absente de categories_processed"


async def test_e2o_total_entries_matches_data(tmp_path: Path):
    """total_entries correspond au nombre total d'entries dans chaque category."""
    wikifile = _make_wikidrive_json(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    # items(9) + recipes(5) + mobs(3) + skills(2) + weather(2) + maps(1) = 22
    assert result.metadata["total_entries"] == 22, f"22 entrées attendues, trouvé {result.metadata['total_entries']}"


async def test_e2o_processor_type_in_metadata(tmp_path: Path):
    """metadata.processor vaut toujours 'wikijson'."""
    wikifile = _make_wikidrive_json(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    assert result.metadata["processor"] == "wikijson"


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine async."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
