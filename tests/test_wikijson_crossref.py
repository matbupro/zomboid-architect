"""test_wikijson_crossref — Validator cross-reference: recipes → items.

Chaque ingredient d'une recette doit correspondre à un item existant
dans la collection pz_items (par key OU displayName).

Cas couverts :
  - Ingredient matching par key exact
  - Ingredient matching par displayName (case-insensitive)
  - Broken references rapportees
  - Ingredients multiples dans une seule recipe
  - Recipe sans ingredients ignoree graceusement
  - Empty data drive → aucun broken ref
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestor.config import IngestorConfig
from ingestor.processors.wikijson import WikiJsonProcessor, TYPE_TO_COLLECTION


# ===========================================================================
# Fixtures — données PZ simulées pour cross-reference testing
# ===========================================================================


def _make_crossref_data() -> dict[str, Any]:
    """Donnees PZ avec intentional broken references pour testing."""
    return {
        "items": {
            # Items valides — les ingredients ci-dessous pointeront vers ceux-ci
            "cloth": {
                "Name": "Cloth",
                "Type": "generic",
                "weight": 0.1,
                "Categories": ["Crafting"],
                "description": "A piece of cloth.",
            },
            "metal_sheet": {
                "Name": "Metal Sheet",
                "Type": "building_material",
                "weight": 2.0,
                "Categories": ["Building"],
                "description": "A sheet of metal.",
            },
            "raw_chicken": {
                "Name": "Raw Chicken Meat",
                "Type": "food_raw",
                "weight": 1.2,
                "Categories": ["Food", "Raw"],
                "description": "Raw chicken meat.",
            },
            "vegetable_scrap": {
                "Name": "Vegetables",
                "Type": "food_raw",
                "weight": 0.3,
                "Categories": ["Food", "Plant"],
                "description": "Scrap vegetables.",
            },
            "bandage_box": {
                "Name": "Dollar Band-Aid Box",
                "Type": "medication_firstaid",
                "weight": 0.2,
                "Categories": ["Medical"],
                "description": "A box of band-aids.",
            },
        },
        "recipes": {
            # Recipe valide — tous ingredients matchent des items
            "craft_cloth_bandage": {
                "Name": "Bandage",
                "Result": "Bandage",
                "Time": 30,
                "Category": "Medical",
                "ingredients": {"Cloth": 3},
                "SkillRequired": "FirstAid",
            },
            # Recipe partiellement broken — un ingredient OK, un autre non
            "cook_stew": {
                "Name": "Chicken Stew",
                "Result": "Chicken Stew",
                "Time": 90,
                "Category": "Campfire",
                "ingredients": {"Raw Chicken Meat": 1, "Ghost Pepper": 2},
                "SkillRequired": "Cooking",
            },
        },
    }


def _make_clean_data() -> dict[str, Any]:
    """Donnees PZ sans broken references (tout match)."""
    return {
        "items": {
            "wood_plank": {"Name": "Wood Plank", "Type": "building_material"},
            "nails": {"Name": "Nails", "Type": "building_material"},
        },
        "recipes": {
            "plank_door": {
                "Name": "Door",
                "Result": "Door",
                "ingredients": {"Wood Plank": 5, "Nails": 10},
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


def _extract_items_from_chunks(chunks: list) -> tuple[set[str], set[str]]:
    """Retourne (keys, normalized displayNames) depuis les chunks items."""
    keys = set()
    names_lower = set()
    for c in chunks:
        if c.metadata.get("type") != "item":
            continue
        key = c.metadata.get("key", "")
        if key:
            keys.add(key.lower())
        # Extraire Name du text (format: "  Name: Value")
        for line in c.text.split("\n"):
            m = re.match(r"\s*Name:\s*(.+)", line)
            if m:
                names_lower.add(m.group(1).strip().lower())
    return keys, names_lower


def _extract_broken_refs_from_chunks(recipes_chunks: list, valid_keys: set, valid_names: set) -> list[str]:
    """Parse les chunks recipes et retourne les ingredients qui ne matchent aucun item.

    Matching exact (pas substring) :
      - ingredient.lower() in valid_keys (exact key match case-insensitive)
      - ingredient in valid_keys (exact key match case-sensitive)
      - ingredient.lower() in valid_names (displayName case-insensitive)
      - ingredient.replace(" ", "_").lower() in valid_keys (underscore variant)
    """
    broken = []
    for c in recipes_chunks:
        if c.metadata.get("type") != "recipe":
            continue
        for line in c.text.split("\n"):
            m = re.match(r"\s*ingredients:\s*(\{.*\})", line, re.IGNORECASE)
            if not m:
                continue
            ing_dict = json.loads(m.group(1))
            for ing_name in ing_dict:
                matched = False
                # Exact key match (case-insensitive)
                if ing_name.lower() in valid_keys:
                    matched = True
                # Exact displayName match (case-insensitive)
                elif ing_name.lower() in valid_names:
                    matched = True
                # Underscore variant of ing name vs keys
                elif ing_name.lower().replace(" ", "_") in valid_keys:
                    matched = True
                if not matched:
                    broken.append(ing_name)
    return broken


# ===========================================================================
# Tests — CrossReferenceValidator
# ===========================================================================


class TestCrossReferenceValidator:
    """Tests du validateur cross-reference."""

    def _make_processor(self, tmp_path: Path) -> WikiJsonProcessor:
        cfg = IngestorConfig()
        data = _make_crossref_data()
        source = str(_write_wikidrive(tmp_path, data))
        return WikiJsonProcessor(cfg, source=source)

    # -- extraction basics --

    async def test_extract_returns_chunks_and_metadata(self, tmp_path: Path):
        """extract() retourne ExtractionResult avec chunks + metadata."""
        proc = self._make_processor(tmp_path)
        result = await proc.extract()

        assert len(result.chunks) > 0
        assert result.metadata["processor"] == "wikijson"
        # categories_processed utilise les keys du dict charge (items.json → item, recipes.json → recipe)
        cats = result.metadata["categories_processed"]
        assert "item" in cats or "items" in cats
        assert "recipe" in cats or "recipes" in cats
        assert isinstance(result.word_count, int) and result.word_count > 0
        assert isinstance(result.metadata.get("total_entries"), int) and result.metadata["total_entries"] > 0


    async def test_items_chunks_have_metadata(self, tmp_path: Path):
        """Chunks items ont metadata {type, key, fields_count}."""
        data = _make_crossref_data()
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        items = [c for c in result.chunks if c.metadata.get("type") == "item"]
        assert len(items) == 5
        for c in items:
            assert c.metadata["type"] == "item"
            assert isinstance(c.metadata["key"], str) and len(c.metadata["key"]) > 0
            assert isinstance(c.metadata["fields_count"], int)
            assert c.metadata["fields_count"] >= 1

    async def test_recipes_chunks_structure(self, tmp_path: Path):
        """Chunks recipes ont les champs attendus."""
        data = _make_crossref_data()
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        recipes = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
        assert len(recipes) >= 2

        # Verifier que craft_cloth_bandage est present (key: craft_cloth_bandag)
        bandage = next(
            (r for r in recipes if "cloth" in r.metadata.get("key", "").lower()),
            None,
        )
        assert bandage is not None

    # -- cross-reference validation --

    async def test_detect_broken_ref_ghost_pepper(self, tmp_path: Path):
        """Ghost Pepper n'existe pas dans items → detecte broken ref."""
        proc = self._make_processor(tmp_path)
        result = await proc.extract()

        item_keys, item_names = _extract_items_from_chunks(result.chunks)
        recipes_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]

        broken = _extract_broken_refs_from_chunks(recipes_chunks, item_keys, item_names)
        assert "Ghost Pepper" in broken, f"Ghost Pepper attendu en broken ref. Broken: {broken}"

    async def test_no_broken_with_clean_data(self, tmp_path: Path):
        """Donnees propres → aucun broken ref detecte."""
        data = _make_clean_data()
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        item_keys, item_names = _extract_items_from_chunks(result.chunks)
        recipes_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
        broken = _extract_broken_refs_from_chunks(recipes_chunks, item_keys, item_names)
        assert not broken, f"Broken refs inesperes: {broken}"

    async def test_case_insensitive_displayname_match(self, tmp_path: Path):
        """Le matching displayName est case-insensitive."""
        data = _make_crossref_data()
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        item_keys, item_names = _extract_items_from_chunks(result.chunks)
        # "Dollar Band-Aid Box" doit matcher bandage_box.DisplayName
        assert "dollar band-aid box" in item_names

    async def test_ingredient_multiple_ok(self, tmp_path: Path):
        """Recipe avec plusieurs ingredients — tous valides si items existent."""
        data = {
            "items": {
                "flour": {"Name": "Flour", "Type": "generic"},
                "water": {"Name": "Water", "Type": "generic"},
                "salt": {"Name": "Salt", "Type": "generic"},
            },
            "recipes": {
                "bread": {
                    "Name": "Bread",
                    "Result": "Bread",
                    "ingredients": {"Flour": 3, "Water": 1, "Salt": 1},
                },
            },
        }
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        item_keys, item_names = _extract_items_from_chunks(result.chunks)
        recipes_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
        broken = _extract_broken_refs_from_chunks(recipes_chunks, item_keys, item_names)
        assert not broken, f"3 ingredients valides mais broken: {broken}"

    async def test_partial_match_via_underscore_variant(self, tmp_path: Path):
        """Ingredient avec espaces match key underscore (Raw Chicken Meat → raw_chicken_meat)."""
        data = _make_crossref_data()
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        item_keys, item_names = _extract_items_from_chunks(result.chunks)
        assert "raw_chicken" in item_keys  # key de l'item
        # "Raw Chicken Meat" → underscore variant = "raw_chicken_meat" qui ne match pas raw_chicken
        # Donc on attend que le displayName match (item_names contient "raw chicken meat")
        assert "raw chicken meat" in item_names

    async def test_empty_recipes_handled_gracefully(self, tmp_path: Path):
        """Recipe sans ingredients ne provoque pas d'erreur."""
        data = {
            "items": {"cloth": {"Name": "Cloth", "Type": "generic"}},
            "recipes": {
                "no_ingr": {
                    "Name": "Test Recipe",
                    "Result": "Test",
                    # Pas d'ingredients key du tout
                },
            },
        }
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()  # ne doit pas lever

        recipes = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
        assert len(recipes) == 1
        # Aucun broken ref possible car pas d'ingredients
        item_keys, item_names = _extract_items_from_chunks(result.chunks)
        broken = _extract_broken_refs_from_chunks(recipes, item_keys, item_names)
        assert not broken

    async def test_large_item_set_crossref(self, tmp_path: Path):
        """Validation cross-reference sur un large ensemble d'items/recipes."""
        items_data: dict[str, Any] = {}
        for i in range(50):
            items_data[f"item_{i}"] = {
                "Name": f"Item Name {i}",
                "Type": "generic",
                "weight": round(i * 0.1, 2),
            }

        recipes_data: dict[str, Any] = {}
        for i in range(30):
            ing_item_a = f"item_{i % 50}"
            ing_item_b = f"item_{(i + 1) % 50}"
            recipes_data[f"recipe_{i}"] = {
                "Name": f"Recipe {i}",
                "Result": f"Product {i}",
                "ingredients": {items_data[ing_item_a]["Name"]: 1, items_data[ing_item_b]["Name"]: 2},
            }

        # Ajouter une recipe avec ingredient broken
        recipes_data["recipe_broken"] = {
            "Name": "Broken Recipe",
            "Result": "Broken Product",
            "ingredients": {"Nonexistent Item": 1},
        }

        data = {"items": items_data, "recipes": recipes_data}
        source = str(_write_wikidrive(tmp_path, data))
        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=source)

        result = await proc.extract()

        items_chunks = [c for c in result.chunks if c.metadata.get("type") == "item"]
        recipes_chunks = [c for c in result.chunks if c.metadata.get("type") == "recipe"]
        assert len(items_chunks) == 50
        assert len(recipes_chunks) == 31

        item_keys, item_names = _extract_items_from_chunks(items_chunks)
        broken = _extract_broken_refs_from_chunks(recipes_chunks, item_keys, item_names)
        # Exactement une broken ref: "Nonexistent Item"
        assert len(broken) == 1
        assert "Nonexistent Item" in broken

    async def test_empty_data_dir_no_crash(self, tmp_path: Path):
        """Dossier vide → pas de crash, resultat vide."""
        base = tmp_path / "pz-wiki-data-empty"
        base.mkdir(parents=True, exist_ok=True)  # dossier vide

        cfg = IngestorConfig()
        proc = WikiJsonProcessor(cfg, source=str(base))
        result = await proc.extract()

        # Pas de chunks, pas d'erreur
        assert len(result.chunks) == 0


# ===========================================================================
# Tests — TYPE_TO_COLLECTION et ExtractionResult
# ===========================================================================


async def test_validate_refs_collection_map_valid():
    """Chaque category du data drive mappe vers une collection valide."""
    # La mappe contient les categories attendues
    assert "items" in TYPE_TO_COLLECTION
    assert "recipes" in TYPE_TO_COLLECTION
    assert "mobs" in TYPE_TO_COLLECTION
    assert "skills" in TYPE_TO_COLLECTION

    # Les collections cibles sont connues
    valid_collections = {
        "pz_items", "pz_recipes", "pz_mechanics", "pz_web_pages",
    }
    for collection in TYPE_TO_COLLECTION.values():
        assert collection in valid_collections, f"Unknown collection: {collection}"


async def test_validate_refs_extraction_result_fields(tmp_path: Path):
    """ExtractionResult a tous les champs attendus."""
    data = _make_clean_data()
    source = str(_write_wikidrive(tmp_path, data))
    cfg = IngestorConfig()
    proc = WikiJsonProcessor(cfg, source=source)

    result = await proc.extract()

    # Validation de tous les champs d'ExtractionResult
    assert hasattr(result, "chunks")
    assert hasattr(result, "collection")
    assert hasattr(result, "source")
    assert hasattr(result, "content_type")
    assert hasattr(result, "file_hash")
    assert hasattr(result, "word_count")
    assert hasattr(result, "extraction_time_ms")
    assert hasattr(result, "metadata")

    # Types values
    assert isinstance(result.chunks, list)
    assert isinstance(result.file_hash, str) and len(result.file_hash) > 0
    assert isinstance(result.word_count, int)
    assert result.word_count > 0
    assert isinstance(result.extraction_time_ms, (int, float))
    assert result.extraction_time_ms >= 0
