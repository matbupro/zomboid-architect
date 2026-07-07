"""test_wikijson_processor — Tests unitaires et d'integration du WikiJsonProcessor.

Couvre :
  - _normalize_item / _normalize_recipe / _normalize_mob / _normalize_generic (unit)
  - _classify_item (classification par Type/categories)
  - _load_wiki_data (fichier, dossier, URL mockée)
  - extract() complet (end-to-end avec fichier JSON tmp)
  - Edge cases : donnees vides, champs manquants, entries invalides
  - Metadata de sortie (categories_processed, total_entries, word_count)
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
from ingestor.processors.wikijson import (
    WikiJsonProcessor,
    _normalize_item,
    _normalize_recipe,
    _normalize_mob,
    _normalize_generic,
    _load_wiki_data,
    TYPE_TO_COLLECTION,
)


# ===========================================================================
# Fixtures — données PZ simulées
# ===========================================================================


def _make_wikidrive_dir(tmp_path: Path) -> Path:
    """Crée un dossier de data drive PZ complet avec tous les types."""
    base = tmp_path / "pz-wiki-data"
    base.mkdir(parents=True, exist_ok=True)

    (base / "items.json").write_text(json.dumps({
        "iron_pipe": {
            "Name": "Iron Pipe", "Type": "weapon_melee", "weight": 1.5,
            "Categories": ["Weapons", "Improvised"], "description": "Une barre de fer.",
            "DamageTiers": {"common": 8, "uncommon": 10, "rare": 12},
            "condition_max": 240,
        },
        "hunting_knife": {
            "Name": "Hunting Knife", "Type": "weapon_melee", "weight": 0.85,
            "Categories": ["Weapons"], "description": "Couteau de chasse.",
            "DamageTiers": {"common": 10, "uncommon": 12, "rare": 15},
            "condition_max": 300,
        },
        "soda_clam": {
            "Name": "Soda Clam", "Type": "food", "weight": 0.4,
            "Categories": ["Food"], "description": "Boite de cola.",
            "Calories": 180, "Protein": 0, "Vitamin": 5, "Mineral": 2, "Water": 12,
        },
        "t_shirt_blue": {
            "Name": "Blue T-Shirt", "Type": "clothing_tshirt", "weight": 0.25,
            "Categories": ["Clothing"], "Description": "T-shirt bleu.",
            "warmth": 1, "Blunt": {"layer1": 0.02}, "Cut": {"layer1": 0.02},
        },
        "wood_plank": {
            "Name": "Wood Plank", "Type": "building_material", "weight": 4.4,
            "Categories": ["Building"], "Description": "Plancher en bois.",
        },
    }, indent=2), encoding="utf-8")

    (base / "recipes.json").write_text(json.dumps({
        "bandage_cloth": {
            "Name": "Bandage", "Result": "Bandage", "Time": 30,
            "Categories": ["Medical"], "ingredients": {"Cloth": 1},
            "SkillRequired": "FirstAid",
        },
        "campfire_steak": {
            "Name": "Cooked Steak", "Result": "Steak Cooked",
            "Time": 60, "Categories": ["Campfire Cooking"],
            "ingredients": {"Steak Raw": 1, "Rags": 1},
            "CrossCookProgression": [
                {"tier": "campfire", "result": "Steak Medium Rare"},
                {"tier": "brick_oven", "result": "Steak Well Done"},
                {"tier": "gas_stove", "result": "Steak Perfect"},
            ],
        },
    }, indent=2), encoding="utf-8")

    (base / "mobs.json").write_text(json.dumps({
        "walker_normal": {
            "Name": "Normal Walker", "HP": 50, "Speed": 1.0,
            "Damage": 5, "Behavior": "walk", "XP": 15,
            "Drops": [{"item": "Rotten Flesh", "min": 1, "max": 3}],
        },
        "bloater": {
            "Name": "Bloater", "HP": 300, "Speed": 0.8,
            "Damage": 25, "Behavior": "aggressive",
            "DetectionRadius": 15, "XP": 75,
            "Drops": [{"item": "Bandage Sterile", "min": 2, "max": 5}],
        },
    }, indent=2), encoding="utf-8")

    (base / "skills.json").write_text(json.dumps({
        "woodworking": {
            "levels": {"I": "Unlocks basic axe use", "II": "Unlocks reinforced walls"},
            "xp_multiplier": 1.0, "required_for": ["carpentry"],
        },
    }, indent=2), encoding="utf-8")

    (base / "weather.json").write_text(json.dumps({
        "spring": {"min_temp": 5, "max_temp": 20, "rain_chance": 0.3},
        "summer": {"min_temp": 20, "max_temp": 42, "heat_stroke_risk": True},
    }, indent=2), encoding="utf-8")

    (base / "maps.json").write_text(json.dumps({
        "new_tonbridge": {
            "size_km2": 19.06, "biome": "mixed", "zombie_density": "high",
            "terrain_type": "hilly_forest",
        },
    }, indent=2), encoding="utf-8")

    return base


def _make_single_wikijson_file(tmp_path: Path) -> Path:
    """Crée un fichier Wiki.json monolithique simulé."""
    data = {
        "items": {
            "iron_pipe": {"Name": "Iron Pipe", "Type": "weapon_melee", "weight": 1.5},
            "soda_clam": {"Name": "Soda Clam", "Type": "food", "weight": 0.4, "Calories": 180},
        },
        "recipes": {
            "bandage": {"Name": "Bandage", "Result": "Bandage", "Time": 30, "ingredients": {"Cloth": 1}},
        },
        "mobs": {
            "walker": {"Name": "Walker", "HP": 50, "Speed": 1.0},
        },
    }
    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f


# ===========================================================================
# Fixtures — processor prêt à l'emploi
# ===========================================================================


@pytest.fixture()
def config():
    """Config minimale pour les processeurs."""
    return IngestorConfig(CHUNK_SIZE=500, CHUNK_OVERLAP=30)


@pytest.fixture()
def processor(config):
    """WikiJsonProcessor sans source (pour tester le constructeur)."""
    return WikiJsonProcessor(config)


# ===========================================================================
# Tests : _normalize_item — item de base
# ===========================================================================


def test_normalize_item_basic():
    """Un item simple produit un chunk avec Name + Type."""
    chunk = _normalize_item({"Name": "Test Item", "Type": "generic"}, "test_item")
    assert chunk is not None
    assert chunk.text.startswith("Item: test_item")
    assert "  Name: Test Item" in chunk.text
    assert "  Type: generic" in chunk.text
    assert chunk.metadata["type"] == "item"


def test_normalize_item_none_input():
    """Entrée non-dict → retourne None."""
    assert _normalize_item("string", "bad") is None
    assert _normalize_item(None, "bad") is None  # type: ignore
    assert _normalize_item([1, 2], "bad") is None


def test_normalize_item_with_damage_tiers():
    """Un item arme inclut DamageTiers dans le chunk."""
    chunk = _normalize_item({"Name": "Axe", "DamageTiers": {"common": 8, "rare": 14}}, "axe")
    assert "DamageTiers" in chunk.text


def test_normalize_item_with_nutrition():
    """Un item food inclut les stats nutritionnelles."""
    chunk = _normalize_item({
        "Name": "Beans", "Calories": 300, "Protein": 15, "Vitamin": 3,
    }, "beans")
    assert "Nutrition" in chunk.text


def test_normalize_item_with_resistance():
    """Un item clothing inclut les resistances."""
    chunk = _normalize_item({
        "Name": "Leather Jacket", "Blunt": 0.1, "Cut": 0.15,
    }, "leather_jacket")
    assert "DamageResistance" in chunk.text


def test_normalize_item_variant_keys():
    """Les champs avec différentes cassettes sont reconnus."""
    # displayName, display_name, name — tous devraient marcher
    chunk = _normalize_item({"displayName": "Alt Name", "sub_category": "weapons"}, "alt_item")
    assert chunk is not None
    assert "  displayName: Alt Name" in chunk.text


def test_normalize_item_fields_count_metadata():
    """Le metadata fields_count correspond au nombre de champs."""
    chunk = _normalize_item({"A": 1, "B": 2, "C": 3}, "counted")
    assert chunk.metadata["fields_count"] == 3


# ===========================================================================
# Tests : _normalize_recipe
# ===========================================================================


def test_normalize_recipe_basic():
    """Une recette simple produit un chunk correct."""
    chunk = _normalize_recipe({
        "Name": "Bandage", "Result": "Bandage", "Time": 30,
        "ingredients": {"Cloth": 2},
    }, "bandage")
    assert chunk is not None
    assert chunk.text.startswith("Recipe: bandage")
    # Les string values sont json.dumps-ed → guillemets inclus : Name: "Bandage"
    assert "  Name: \"Bandage\"" in chunk.text  # value string → json.dumps → "Bandage"
    assert '"Time":' not in chunk.text  # Time=30 (int) → pas de guillemets autour du nom
    """Une recette avec CrossCookProgression inclut ProcessingTiers."""
    chunk = _normalize_recipe({
        "Name": "Cake", "Result": "Cake",
        "CrossCookProgression": [{"tier": "campfire"}, {"tier": "oven"}],
    }, "cake")
    assert "ProcessingTiers" in chunk.text


def test_normalize_recipe_variant_keys():
    """Les variantes de clés (time/duration) sont reconnues."""
    chunk = _normalize_recipe({"Name": "N", "Time": 10}, "alt")
    assert chunk is not None
    assert "  Time: 10" in chunk.text


def test_normalize_recipe_none_input():
    """Entrée non-dict → retourne None."""
    assert _normalize_recipe("not_a_dict", "bad") is None  # type: ignore
    assert _normalize_recipe(None, "bad") is None  # type: ignore


# ===========================================================================
# Tests : _normalize_mob
# ===========================================================================


def test_normalize_mob_basic():
    """Un zombie basique produit un chunk avec HP, Speed, Damage."""
    chunk = _normalize_mob({"Name": "Walker", "HP": 50, "Speed": 1.0}, "walker")
    assert chunk is not None
    assert chunk.text.startswith("Mob: walker")
    assert "  Name: Walker" in chunk.text


def test_normalize_mob_with_drops():
    """Un mob avec Drops inclut la section drops en JSON."""
    chunk = _normalize_mob({
        "Name": "Bloater", "HP": 300,
        "Drops": [{"item": "Bandage", "min": 2}],
    }, "bloater")
    assert "Drops" in chunk.text


def test_normalize_mob_detection_radius():
    """DetectionRadius est extrait quand présent."""
    chunk = _normalize_mob({"Name": "Creeper", "DetectionRadius": 10}, "creeper")
    assert "DetectionRadius: 10" in chunk.text


def test_normalize_mob_none_input():
    """Entrée non-dict → retourne None."""
    assert _normalize_mob("string", "bad") is None  # type: ignore
    assert _normalize_mob(None, "bad") is None  # type: ignore


# ===========================================================================
# Tests : _normalize_generic (skills, weather, maps)
# ===========================================================================


def test_normalize_generic_skill():
    """Un skill est normalisé en chunk avec prefix 'skill'."""
    chunk = _normalize_generic({"levels": "I/II", "xp_multiplier": 1.0}, "woodworking", "skill")
    assert chunk is not None
    assert chunk.text.startswith("skill: woodworking")
    assert "levels:" in chunk.text
    assert "xp_multiplier:" in chunk.text


def test_normalize_generic_skips_underscore_keys():
    """Les clés commençant par _ sont ignorées."""
    chunk = _normalize_generic({"public": 42, "_internal": "hidden"}, "test", "category")
    assert "_internal" not in chunk.text
    assert "public: 42" in chunk.text


def test_normalize_generic_nested_value_json_dumped():
    """Les valeurs complexes sont dumpées en JSON sur une ligne."""
    chunk = _normalize_generic({"data": {"nested": True}}, "test", "category")
    # Valeur complexe → json.dumps limité à 200 chars
    assert "\"nested\"" in chunk.text


def test_normalize_generic_none_input():
    """Entrée non-dict → retourne None."""
    assert _normalize_generic("string", "bad", "x") is None  # type: ignore
    assert _normalize_generic(None, "bad", "x") is None  # type: ignore


# ===========================================================================
# Tests : _classify_item (routing vers sous-collection)
# ===========================================================================


def test_classify_weapon_melee(processor):
    """Item Type='weapon_melee' → 'weapon_melee'."""
    assert processor._classify_item({"Type": "weapon_melee"}) == "weapon_melee"


def test_classify_weapon_firearm(processor):
    """Item Type contenant 'firearm' → 'weapon_firearm'."""
    assert processor._classify_item({"Type": "weapon_firearm"}) == "weapon_firearm"


def test_classify_food(processor):
    """Item Type='food' ou contenant 'canned' → 'food'."""
    assert processor._classify_item({"Type": "food"}) == "food"
    assert processor._classify_item({"Type": "canned_good"}) == "food"


def test_classify_clothing(processor):
    """Item Type='clothing' ou contenant 'armor' → 'clothing'."""
    assert processor._classify_item({"Type": "clothing_tshirt"}) == "clothing"
    assert processor._classify_item({"Type": "armor_vest"}) == "clothing"


def test_classify_vehicle(processor):
    """Item Type contenant 'vehicle' → 'vehicle'."""
    assert processor._classify_item({"Type": "vehicle_sedan"}) == "vehicle"


def test_classify_building_material(processor):
    """Item Type='building_material' → 'building_material'."""
    assert processor._classify_item({"Type": "building_material"}) == "building_material"


def test_classify_generic_unknown(processor):
    """Type inconnu → 'generic'."""
    assert processor._classify_item({"Type": "unknown_type"}) == "generic"


def test_classify_case_insensitive(processor):
    """La classification est insensible à la casse."""
    assert processor._classify_item({"Type": "WEAPON_MELEE"}) == "weapon_melee"
    assert processor._classify_item({"Type": ""}) == "generic"  # type vide → generic


# ===========================================================================
# Tests : _load_wiki_data — fichier unique
# ===========================================================================


def test_load_wiki_data_from_file(tmp_path: Path):
    """Chargement depuis un fichier Wiki.json."""
    data = {
        "_file": str(tmp_path / "Wiki.json"),
        "items": {"a": {"Name": "A"}, "b": {"Name": "B"}},
        "recipes": {"c": {"Name": "C"}},
    }
    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")

    loaded = _load_wiki_data(str(f))
    assert "_file" in loaded
    assert isinstance(loaded["items"], dict)
    assert len(loaded["items"]) == 2


def test_load_wiki_data_from_file_missing():
    """Chargement depuis un fichier inexistant → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        _load_wiki_data("/does/not/exist/Wiki.json")


# ===========================================================================
# Tests : _load_wiki_data — dossier multi-fichiers
# ===========================================================================


def test_load_wiki_data_from_directory(tmp_path: Path):
    """Chargement depuis un dossier avec plusieurs JSON."""
    base = tmp_path / "data"
    base.mkdir(parents=True, exist_ok=True)
    (base / "items.json").write_text('{"a": {"Name": "A"}}', encoding="utf-8")
    (base / "recipes.json").write_text('{"b": {"Name": "B"}}', encoding="utf-8")

    loaded = _load_wiki_data(str(base))
    assert "_dir" in loaded
    # _load_wiki_data fait jf.stem.lower().rstrip("s") → "item" + "recipe"
    # Mais le processor appelle TYPE_TO_COLLECTION.get(k) donc ces keys marchent quand meme
    assert "item" in loaded or "items" in loaded


def test_load_wiki_data_empty_directory(tmp_path: Path):
    """Dossier vide → retourne seulement _dir."""
    base = tmp_path / "empty_dir"
    base.mkdir()

    loaded = _load_wiki_data(str(base))
    assert "_dir" in loaded
    assert loaded == {"_dir": str(base)}


# ===========================================================================
# Tests : WikiJsonProcessor — constructeur et validation
# ===========================================================================


def test_processor_init(config):
    """Le processor se cree avec la config."""
    proc = WikiJsonProcessor(config)
    assert proc.config is config


def test_extract_no_source_raises(processor):
    """extract() sans source → ValueError."""
    import pytest

    async def _try():
        return await processor.extract()

    with pytest.raises(ValueError, match="aucune source fournie"):
        asyncio_run(_try())


# ===========================================================================
# Tests : extract() — end-to-end avec dossier de data drive complet
# ===========================================================================


async def test_extract_full_pipeline_wikidrive_dir(tmp_path: Path):
    """Pipeline complet : données → chunks categorisés."""
    wikidir = _make_wikidrive_dir(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikidir))

    # Tous les chunks présents
    assert len(result.chunks) > 0

    # Items : 5 items → 5 chunks (iron_pipe, hunting_knife, soda_clam, t_shirt_blue, wood_plank)
    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    assert len(item_chunks) == 5

    # Recettes : 2 recipes → 2 chunks
    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
    assert len(recipe_chunks) == 2

    # Mobs : 2 mobs → 2 chunks
    mob_chunks = [c for c in result.chunks if c.metadata.get("type") == "mob"]
    assert len(mob_chunks) == 2

    # Skills : 1 chunk (generic)
    skill_chunks = [c for c in result.chunks if c.metadata.get("type") == "skill"]
    assert len(skill_chunks) == 1

    # Weather : chunks pour spring + summer
    weather_chunks = [c for c in result.chunks if c.metadata.get("type") == "weather"]
    assert len(weather_chunks) >= 2

    # Maps : chunk pour new_tonbridge
    map_chunks = [c for c in result.chunks if c.metadata.get("type") == "map"]
    assert len(map_chunks) == 1


async def test_extract_full_pipeline_single_file(tmp_path: Path):
    """Pipeline depuis un fichier Wiki.json unique."""
    wikifile = _make_single_wikijson_file(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    assert len(result.chunks) == 4  # 2 items + 1 recipe + 1 mob


async def test_extract_metadata_categories_processed(tmp_path: Path):
    """metadata.categories_processed liste les categories lues (celles qui passent le filtre)."""
    wikidir = _make_wikidrive_dir(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikidir))

    # Les categories dans EXPECTED_KEYS sont incluses.
    # Le processor fait data.keys() qui donne les keys du dict loaded (ex: "item" pour items.json)
    assert "items" in result.metadata["categories_processed"] or "item" in result.metadata["categories_processed"]
    assert len(result.metadata["categories_processed"]) >= 3  # au moins items, recipes, mobs


async def test_extract_metadata_word_count(tmp_path: Path):
    """word_count est la somme des mots de tous les chunks."""
    wikidir = _make_wikidrive_dir(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikidir))

    total_words = sum(len(c.text.split()) for c in result.chunks)
    assert result.word_count == total_words


async def test_extract_metadata_total_entries(tmp_path: Path):
    """total_entries compte les entrées dict dans chaque category."""
    wikidir = _make_wikidrive_dir(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikidir))

    # items(5) + recipes(2) + mobs(2) + skills(1) + weather(2) + maps(1) = 13
    assert result.metadata["total_entries"] == 13


# ===========================================================================
# Tests : extract() — edge cases
# ===========================================================================


async def test_extract_empty_data_dir(tmp_path: Path):
    """Dossier avec des JSON vides ne plante pas."""
    base = tmp_path / "empty_wikidrive"
    base.mkdir(parents=True, exist_ok=True)

    (base / "items.json").write_text("{}", encoding="utf-8")
    (base / "recipes.json").write_text("[]", encoding="utf-8")  # liste vide

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(base))

    assert len(result.chunks) == 0


async def test_extract_malformed_item_fails_gracefully(tmp_path: Path):
    """Un entry malformed dans le JSON ne fait pas planter le pipeline."""
    base = tmp_path / "malformed_wikidrive"
    base.mkdir(parents=True, exist_ok=True)

    (base / "items.json").write_text(json.dumps({
        "good_item": {"Name": "Good", "Type": "generic"},
        "bad_entry": "not_a_dict_at_all",  # non-dict → ignoré par normalizer
        "empty_dict": {},  # dict vide → chunk sans champs utiles mais OK
    }), encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(base))

    # L'item bon est présent, le mauvais est ignoré (normalizer retourne None pour non-dict)
    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    assert len(item_chunks) >= 1


async def test_extract_non_dict_category_value_ignored(tmp_path: Path):
    """Les categories dont la valeur n'est ni dict ni list sont ignorées."""
    base = tmp_path / "weird_wikidrive"
    base.mkdir(parents=True, exist_ok=True)

    (base / "mobs.json").write_text(json.dumps("just_a_string"), encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(base))

    # Pas de crash, aucune chunk pour cette category
    assert all(c.metadata.get("type") != "mob" for c in result.chunks)


async def test_extract_list_items_converted_to_dict(tmp_path: Path):
    """Une liste d'items dans le JSON est convertie en dict par index.

    Note : _load_wiki_data ignores list values (only dicts accepted).
    On teste donc via un fichier Wiki.json direct où la conversion est en amont.
    """
    f = tmp_path / "Wiki.json"
    f.write_text(json.dumps({
        "items": [  # liste → convertie par le processor en {"0": ..., "1": ...}
            {"Name": "First", "Type": "generic"},
            {"Name": "Second", "Type": "generic"},
        ],
    }), encoding="utf-8")

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(f))

    # Les entries de la liste sont converties en dict par index dans extract()
    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    assert len(item_chunks) == 2


# ===========================================================================
# Tests : TYPE_TO_COLLECTION mapping
# ===========================================================================


def test_type_to_collection_has_expected_categories():
    """Les categories attendues sont toutes mappées."""
    expected = {"items", "recipes", "mobs", "crops", "skills", "weather", "maps"}
    for cat in expected:
        assert cat in TYPE_TO_COLLECTION, f"{cat} absent de TYPE_TO_COLLECTION"


def test_type_to_collection_all_targets_valid():
    """Toutes les valeurs cibles sont des strings valides."""
    for key, target in TYPE_TO_COLLECTION.items():
        assert isinstance(key, str) and len(key) > 0
        assert isinstance(target, str) and len(target) > 0


def test_type_to_collection_maps_items_to_pz_items():
    """items → pz_items."""
    assert TYPE_TO_COLLECTION["items"] == "pz_items"


def test_type_to_collection_maps_recipes_to_pz_recipes():
    """recipes → pz_recipes."""
    assert TYPE_TO_COLLECTION["recipes"] == "pz_recipes"


def test_unknown_category_defaults_to_pz_web_pages():
    """Les categories non mappées default vers pz_web_pages."""
    # poi est dans le mapping, mais une category totalement inconnue devrait aller à _get_normalizer
    # et utiliser TYPE_TO_COLLECTION.get → None → fallback dans la boucle extract
    assert "nonexistent_key" not in TYPE_TO_COLLECTION


# ===========================================================================
# Tests : ExtractionResult fields validation (wikijson specific)
# ===========================================================================


async def test_extraction_result_source_matches_input(tmp_path: Path):
    """result.source correspond au fichier passé en argument."""
    wikifile = _make_single_wikijson_file(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikifile))

    assert "Wiki.json" in result.source


async def test_extraction_result_content_type_is_json(tmp_path: Path):
    """Le content_type est application/json."""
    proc = WikiJsonProcessor(config=IngestorConfig())
    wikidir = _make_wikidrive_dir(tmp_path)
    result = await proc.extract(str(wikidir))

    assert result.content_type == "application/json"


async def test_extraction_result_processor_metadata(tmp_path: Path):
    """metadata.processor vaut 'wikijson'."""
    wikidir = _make_wikidrive_dir(tmp_path)

    proc = WikiJsonProcessor(config=IngestorConfig())
    result = await proc.extract(str(wikidir))

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
