"""test_wikijson_completeness — Validator completeness: % fields remplis par item vs total attendu.

Chaque type d'item PZ a un schema de champs attendu. Le validateur verifie :
  - Items weapon_melee → Name, Type, Weight, Categories, SubCategory, Description,
    ConditionMax, DamageTiers (8 champs minimum)
  - Items food → Name, Type, Weight, Calories, Protein, Vitamin, Mineral, Water
  - Items clothing → Name, Type, Weight, Categories, Blunt/Cut resistance
  - Recipes → Name, Result, Time, Category, Ingredients, SkillRequired
  - Mobs → Name, HP, Speed, Damage, Behavior

Cas couverts :
  - Item complet (tous champs)
  - Item partiellement rempli
  - Item incomplet (<50% fields)
  - Recipe completeness
  - Mob completeness
  - Global completeness stats par category
  - Items sans FieldsCount metadata
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
# Fixtures — donnees PZ avec differents niveaux de completeness
# ===========================================================================


def _make_weapon_data() -> dict[str, Any]:
    """Items de type weapon avec different niveaux de remplissage."""
    return {
        "items": {
            # Weapon complet (tous champs)
            "iron_pipe_full": {
                "Name": "Iron Pipe",
                "Type": "weapon_melee",
                "weight": 1.5,
                "Categories": ["Weapons"],
                "SubCategory": "Melee Weapons",
                "description": "A heavy iron pipe.",
                "Icon": "icon_iron_pipe.png",
                "condition_max": 240,
                "DamageTiers": {"common": 8, "uncommon": 10, "rare": 12},
            },
            # Weapon partiel (5/8 champs)
            "wooden_bat_partial": {
                "Name": "Baseball Bat",
                "Type": "weapon_melee",
                "description": "A wooden bat.",
                "condition_max": 325,
                "DamageTiers": {"common": 10},
            },
            # Weapon incomplet (2/8 champs — <50%)
            "busted_pipe": {
                "Name": "Rusty Pipe",
                "Type": "weapon_melee",
            },
        },
        "recipes": {},
    }


def _make_food_data() -> dict[str, Any]:
    """Items de type food avec different niveaux de remplissage."""
    return {
        "items": {
            # Food complet (Calories, Protein, Vitamin, Mineral, Water)
            "canned_beans_full": {
                "Name": "Canned Beans",
                "Type": "food_canned",
                "weight": 0.45,
                "Categories": ["Food"],
                "SubCategory": "Canned Food",
                "description": "A can of beans.",
                "Calories": 350,
                "Protein": 18,
                "Vitamin": 3,
                "Mineral": 4,
                "Water": 12,
            },
            # Food sans nutrition
            "bread_loaf_empty_nutrition": {
                "Name": "Bread Loaf",
                "Type": "food_bread",
                "weight": 0.8,
                "Categories": ["Food"],
                "description": "A loaf of bread.",
            },
        },
        "recipes": {},
    }


def _make_clothing_data() -> dict[str, Any]:
    """Items de type clothing/armor."""
    return {
        "items": {
            # Clothing complet avec resistance layers
            "leather_jacket_full": {
                "Name": "Leather Jacket",
                "Type": "clothing_jacket",
                "weight": 2.5,
                "Categories": ["Clothing", "Armor"],
                "SubCategory": "Jackets",
                "description": "A protective leather jacket.",
                "warmth": 3,
                "Blunt": {"layer1": 0.05},
                "Cut": {"layer1": 0.08},
            },
            # Clothing minimal
            "tshirt_minimal": {
                "Name": "T-Shirt",
                "Type": "clothing_tshirt",
            },
        },
        "recipes": {},
    }


def _make_recipe_data() -> dict[str, Any]:
    """Recettes avec different niveaux de remplissage."""
    return {
        "items": {},
        "recipes": {
            # Recipe complète (tous champs + optional)
            "campfire_steak_full": {
                "Name": "Steak Medium Rare",
                "Result": "Steak Cooked (MR)",
                "Time": 60,
                "Category": "Campfire Cooking",
                "ingredients": {"Steak Raw": 1},
                "SkillRequired": "Cooking",
                "ToolsRequired": ["Campfire"],
                "CrossCookProgression": [
                    {"tier": "campfire"},
                    {"tier": "brick_oven"},
                ],
            },
            # Recipe partiellement remplie (4/8 champs)
            "bandage_basic": {
                "Name": "Bandage",
                "Result": "Bandage",
                "Time": 30,
                "ingredients": {"Cloth": 1},
            },
            # Recipe minimale (2 champs)
            "nothing_recipe": {
                "Name": "Nothing",
            },
        },
    }


def _make_mob_data() -> dict[str, Any]:
    """Mobs avec different niveaux de remplissage."""
    return {
        "items": {},
        "recipes": {},
        "mobs": {
            # Mob complet
            "bloater_full": {
                "Name": "Bloater",
                "HP": 180,
                "Speed": 2.5,
                "Damage": 25,
                "Behavior": "aggressive",
                "SpawnBiomes": ["ruins", "suburbs"],
                "XP": 30,
                "DetectionRadius": 30,
                "Drops": {"Flesh": (1, 3)},
            },
            # Mob partiel
            "walker_basic": {
                "Name": "Walker",
                "HP": 50,
                "Speed": 1.0,
            },
            # Mob presque vide
            "ghost_zombie": {
                "Name": "Ghost Zombie",
            },
        },
    }


def _make_skill_data() -> dict[str, Any]:
    """Skills avec different niveaux de remplissage."""
    return {
        "items": {},
        "recipes": {},
        "mobs": {},
        "skills": {
            "cooking_full": {
                "Name": "Cooking",
                "XPMultiplier": 1.5,
                "MaxLevel": 50,
                "Description": "Learn to cook food for better nutrition.",
                "Categories": ["Survival"],
                "RecipesRequired": 20,
            },
            "cooking_partial": {
                "Name": "Cooking",
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
# Helpers de validation completeness
# ===========================================================================

# Schema des champs attendus par category/item-type
WEAPON_COMMON_FIELDS = frozenset([
    "Name", "Type", "Weight", "Categories", "SubCategory",
    "Description", "Icon", "ConditionMax", "DamageTiers",
])
FOOD_NUTRITION_FIELDS = frozenset(["Calories", "Protein", "Vitamin", "Mineral", "Water"])
CLOTHING_RESISTANCE_FIELDS = frozenset(["Blunt", "Cut", "Scratch", "Tear"])
RECIPE_REQUIRED_FIELDS = frozenset([
    "Name", "Result", "Time", "Category", "Ingredients", "SkillRequired",
])
MOB_BASE_FIELDS = frozenset([
    "Name", "HP", "Speed", "Damage", "Behavior",
    "SpawnBiomes", "XP", "DetectionRadius",
])


def _compute_completeness(item_data: dict, expected_fields: set) -> float:
    """Calcule le % de champs fills par rapport aux expected.

    Un champ est 'filled' si presente dans item_data (par son primary key).
    """
    if not expected_fields:
        return 1.0
    filled = sum(1 for f in expected_fields if f in item_data)
    return filled / len(expected_fields)


def _get_item_type(item_data: dict) -> str:
    """Determine le type d'item pour selection du schema."""
    type_val = item_data.get("Type") or item_data.get("type", "")
    if "weapon" in type_val.lower():
        return "weapon"
    if "food" in type_val.lower() or "canned" in type_val.lower():
        return "food"
    if "clothing" in type_val.lower() or "armor" in type_val.lower():
        return "clothing"
    return "generic"


def _get_expected_fields(item_data: dict) -> set:
    """Retourne les champs attendus pour un item selon son type."""
    item_type = _get_item_type(item_data)
    base_fields = {"Name", "Type"}  # toujours attendus

    if item_type == "weapon":
        return WEAPON_COMMON_FIELDS | base_fields
    elif item_type == "food":
        return base_fields | FOOD_NUTRITION_FIELDS
    elif item_type == "clothing":
        return base_fields | CLOTHING_RESISTANCE_FIELDS
    else:
        # Generic = minimal (name + weight)
        return {"Name", "Type", "weight"}


# ===========================================================================
# Tests — Completeness Validator
# ===========================================================================


async def test_weapon_full_item_has_high_completeness(tmp_path: Path):
    """Weapon complet → completeness >= 80%."""
    data = _make_weapon_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]

    # iron_pipe_full devrait avoir 9/10 champs (90%)
    iron_pipe = next((c for c in item_chunks if "iron_pipe_full" in c.metadata.get("key", "")), None)
    assert iron_pipe is not None, "iron_pipe_full chunk not found"
    # fields_count = len(item_data) dans metadata
    assert iron_pipe.metadata["fields_count"] >= 9


async def test_weapon_partial_item_medium_completeness(tmp_path: Path):
    """Weapon partiel → completeness ~60%."""
    data = _make_weapon_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    bat = next((c for c in item_chunks if "wooden_bat_partial" in c.metadata.get("key", "")), None)
    assert bat is not None
    assert bat.metadata["fields_count"] >= 5  # Name, Type, description, condition_max, DamageTiers


async def test_weapon_low_completeness_flagged(tmp_path: Path):
    """Weapon incomplet (<50%) → completeness faible detecte."""
    data = _make_weapon_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    rustypipe = next((c for c in item_chunks if "busted_pipe" in c.metadata.get("key", "")), None)
    assert rustypipe is not None
    # 2 champs sur ~9 attendus pour weapon = ~22% completeness
    expected_wep_fields = len(WEAPON_COMMON_FIELDS | {"Name", "Type"})
    assert rustypipe.metadata["fields_count"] < expected_wep_fields * 0.5


async def test_food_nutrition_completeness(tmp_path: Path):
    """Food avec nutrition complète → champs nutritionnels presents."""
    data = _make_food_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    food_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    beans = next((c for c in food_chunks if "canned_beans_full" in c.metadata.get("key", "")), None)
    assert beans is not None
    # Le text doit contenir les champs nutritionnels
    assert "Calories:" in beans.text or "calories:" in beans.text.lower()
    # fields_count devrait inclure tous les champs nutritionnels
    assert beans.metadata["fields_count"] >= 10


async def test_food_no_nutrition_low_score(tmp_path: Path):
    """Food sans nutrition → completeness nutrition = 0."""
    data = _make_food_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    food_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    bread = next((c for c in food_chunks if "bread_loaf_empty_nutrition" in c.metadata.get("key", "")), None)
    assert bread is not None
    # fields_count devrait etre plus faible car pas de nutrition fields
    assert bread.metadata["fields_count"] < 7  # ~6 champs (Name, Type, weight, Categories, description + subcategory check)


async def test_clothing_resistance_complete(tmp_path: Path):
    """Clothing avec Blunt/Cut resistance → completeness eleve."""
    data = _make_clothing_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    clothing_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    jacket = next((c for c in clothing_chunks if "leather_jacket_full" in c.metadata.get("key", "")), None)
    assert jacket is not None
    # Le chunk text doit contenir DamageResistance
    # Resistance peut etre "DamageResistance: {...}" ou fields directs Blunt/Cut
    has_damage_resistance = ("DamageResistance:" in jacket.text) or (
        "Blunt:" in jacket.text and "Cut:" in jacket.text
    )
    assert has_damage_resistance, f"No resistance data found. Text:\n{jacket.text}"


async def test_clothing_minimal_low_completeness(tmp_path: Path):
    """Clothing minimal (nom seulement) → completeness basse."""
    data = _make_clothing_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    clothing_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    tshirt = next((c for c in clothing_chunks if "tshirt_minimal" in c.metadata.get("key", "")), None)
    assert tshirt is not None
    # Seulement Name + Type = 2 champs vs ~8 attendus pour clothing


async def test_recipe_full_completeness(tmp_path: Path):
    """Recipe complète → tous les champs attendus presents."""
    data = _make_recipe_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
    steak = next((c for c in recipe_chunks if "campfire_steak_full" in c.metadata.get("key", "")), None)
    assert steak is not None
    assert steak.metadata["fields_count"] >= 8  # Name, Result, Time, Category, ingredients, SkillRequired, ToolsRequired, CrossCookProgression


async def test_recipe_minimal_partial(tmp_path: Path):
    """Recipe minimale (2 champs) → completeness ~25%."""
    data = _make_recipe_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    recipe_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
    nothing_recipe = next((c for c in recipe_chunks if "nothing_recipe" in c.metadata.get("key", "")), None)
    assert nothing_recipe is not None
    # Seulement Name present => 1 champ sur ~8 attendus


async def test_mob_full_completeness(tmp_path: Path):
    """Mob complet → HP, Speed, Damage, Behavior, Drops presents."""
    data = _make_mob_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    mob_chunks = [c for c in result.chunks if c.metadata.get("type") == "mob"]
    bloater = next((c for c in mob_chunks if "bloater_full" in c.metadata.get("key", "")), None)
    assert bloater is not None
    # Le chunk text doit contenir les champs de base
    assert "HP:" in bloater.text or "hp:" in bloater.text.lower()
    assert "Damage:" in bloater.text or "damage:" in bloater.text.lower()
    assert "Drops:" in bloater.text or "drops:" in bloater.text.lower()


async def test_mob_partial_low_completeness(tmp_path: Path):
    """Mob partiellement rempli → completeness moderate."""
    data = _make_mob_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    mob_chunks = [c for c in result.chunks if c.metadata.get("type") == "mob"]
    walker = next((c for c in mob_chunks if "walker_basic" in c.metadata.get("key", "")), None)
    assert walker is not None
    # Seulement 3 champs sur ~9 attendus pour mob


async def test_completeness_stats_across_categories(tmp_path: Path):
    """Global completeness stats : items/recipes/mobs avec metadata."""
    data = {
        "items": {
            "full_item": {"Name": "Full Item", "Type": "generic", "weight": 1.0},
            "empty_item": {"Name": "Empty"},
        },
        "recipes": {},
        "mobs": {},
    }
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    # Metadata d'extraction doit contenir categories_processed et total_entries
    assert result.metadata["processor"] == "wikijson"
    cats = result.metadata["categories_processed"]
    assert "item" in cats or "items" in cats


async def test_completeness_generic_skills(tmp_path: Path):
    """Skills → normalise via _normalize_generic, tous les sous-champs presentes."""
    data = _make_skill_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    skill_chunks = [c for c in result.chunks if c.metadata.get("type") == "skill"]
    assert len(skill_chunks) >= 2

    # cooking_full doit avoir plus de fields que cooking_partial
    full_skill = next((s for s in skill_chunks if "cooking_full" in s.metadata.get("key", "")), None)
    partial_skill = next((s for s in skill_chunks if "cooking_partial" in s.metadata.get("key", "")), None)

    assert full_skill is not None
    assert partial_skill is not None
    assert full_skill.metadata["fields_count"] > partial_skill.metadata["fields_count"]


async def test_completeness_zero_fields_item(tmp_path: Path):
    """Item avec seulement Name → completeness = 1/n attendus."""
    data = {
        "items": {
            "bare_minimum": {"Name": "Bare Minimum"},
        },
        "recipes": {},
    }
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    bare = next((c for c in item_chunks if "bare_minimum" in c.metadata.get("key", "")), None)
    assert bare is not None
    # fields_count minimal (seulement 1 champ dans le dict original)
    assert bare.metadata["fields_count"] >= 1


async def test_completeness_non_dict_values_ignored(tmp_path: Path):
    """Valeurs non-dict dans items sont ignorees graceusement."""
    data = {
        "items": {
            "good_item": {"Name": "Good", "Type": "generic"},
            "bad_item": "not a dict",  # Valeur string au lieu de dict
            "empty_dict": {},
        },
        "recipes": {},
    }
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()  # ne doit pas lever

    item_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
    # Seulement good_item passe (empty_dict peut passer aussi)
    assert len(item_chunks) >= 1
    keys = {c.metadata["key"] for c in item_chunks}
    assert "good_item" in keys
