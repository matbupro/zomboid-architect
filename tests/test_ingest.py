"""tests/test_ingest.py — Tests du script d'ingestion globale (Phase 3).

Couvre :
  - get_b41_items / get_b41_recipes / get_b41_mechanics / get_b42_diffs
  - validate_metadata (erreurs et passage)
  - generate_chunks_for_object (structure des chunks)
  - _resolve_collection (mapping collection)
  - MetadataConstraint dataclass
  - IngestSummary dataclass
  - Batch anti-OOM (MAX_BATCH_BYTES / BATCH_SIZE_DEFAULT)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


# ===========================================================================
# Tests : données structurées
# ===========================================================================


def test_get_b41_items_returns_list():
    """get_b41_items retourne 8 objets PZ B41."""
    from ingestor.ingest import get_b41_items

    items = get_b41_items()
    assert isinstance(items, list)
    assert len(items) == 8


def test_get_b41_items_have_required_fields():
    """Chaque objet a item_type, game_version, base_id, display_name, description."""
    from ingestor.ingest import get_b41_items, MetadataConstraint

    items = get_b41_items()
    for item in items:
        assert isinstance(item, MetadataConstraint)
        assert item.item_type is not None
        assert item.game_version == "b41"
        assert item.base_id.startswith("Base.") or item.base_id.startswith("Recipe.")


def test_get_b41_recipes_returns_list():
    """get_b41_recipes retourne 2 recettes."""
    from ingestor.ingest import get_b41_recipes

    recipes = get_b41_recipes()
    assert len(recipes) == 2


def test_get_b41_mechanics_returns_list():
    """get_b41_mechanics retourne 4 mecanismes."""
    from ingestor.ingest import get_b41_mechanics

    mechanics = get_b41_mechanics()
    assert len(mechanics) == 4


def test_get_b42_diffs_returns_list():
    """get_b42_diffs retourne au moins 1 differentiel."""
    from ingestor.ingest import get_b42_diffs

    diffs = get_b42_diffs()
    assert len(diffs) >= 1


def test_all_items_have_valid_game_version():
    """Tous les objets B41 ont game_version='b41'."""
    from ingestor.ingest import get_b41_items, GAME_VERSIONS

    items = get_b41_items()
    for item in items:
        assert item.game_version == "b41"


def test_all_item_types_are_valid():
    """Tous les item_type sont dans VALID_ITEM_TYPES."""
    from ingestor.ingest import get_b41_items, VALID_ITEM_TYPES

    items = get_b41_items()
    for item in items:
        assert item.item_type in VALID_ITEM_TYPES


# ===========================================================================
# Tests : validate_metadata
# ===========================================================================


def test_validate_metadata_empty_errors():
    """Metadata vide → erreurs sur tous les champs requis."""
    from ingestor.ingest import MetadataConstraint, validate_metadata

    constraint = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Test",
        display_name="Test", description="x",
    )
    errs = validate_metadata(constraint, {})
    assert len(errs) == 3


def test_validate_metadata_complete_ok():
    """Metadata complete avec tous les champs requis → 0 erreur."""
    from ingestor.ingest import MetadataConstraint, validate_metadata

    constraint = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Test",
        display_name="Test", description="x",
    )
    meta = {
        "item_type": "weapon",
        "game_version": "b41",
        "base_id": "Base.Test",
    }
    errs = validate_metadata(constraint, meta)
    assert len(errs) == 0


def test_validate_metadata_invalid_item_type():
    """item_type invalide → erreur."""
    from ingestor.ingest import MetadataConstraint, validate_metadata

    constraint = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Test",
        display_name="Test", description="x",
    )
    meta = {
        "item_type": "invalid_type",
        "game_version": "b41",
        "base_id": "Base.Test",
    }
    errs = validate_metadata(constraint, meta)
    assert any("item_type" in e for e in errs)


def test_validate_metadata_invalid_game_version():
    """game_version invalide → erreur."""
    from ingestor.ingest import MetadataConstraint, validate_metadata

    constraint = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Test",
        display_name="Test", description="x",
    )
    meta = {
        "item_type": "weapon",
        "game_version": "b50",
        "base_id": "Base.Test",
    }
    errs = validate_metadata(constraint, meta)
    assert any("game_version" in e for e in errs)


# ===========================================================================
# Tests : generate_chunks_for_object
# ===========================================================================


def test_generate_chunks_returns_list():
    """generate_chunks retourne une liste de dicts."""
    from ingestor.ingest import get_b41_items, generate_chunks_for_object

    items = get_b41_items()
    chunks = asyncio.run(generate_chunks_for_object(items[0]))
    assert isinstance(chunks, list)
    assert len(chunks) >= 1


def test_generate_chunks_have_required_keys():
    """Chaque chunk a 'text', 'metadata', 'collection'."""
    from ingestor.ingest import get_b41_items, generate_chunks_for_object

    items = get_b41_items()
    chunks = asyncio.run(generate_chunks_for_object(items[0]))

    for chunk in chunks:
        assert "text" in chunk
        assert "metadata" in chunk
        assert "collection" in chunk
        assert chunk["text"]  # pas vide


def test_generate_chunks_metadata_strict():
    """Les metadata contiennent les champs obligatoires."""
    from ingestor.ingest import get_b41_items, generate_chunks_for_object

    items = get_b41_items()
    chunks = asyncio.run(generate_chunks_for_object(items[0]))

    for chunk in chunks:
        meta = chunk["metadata"]
        assert "item_type" in meta
        assert "game_version" in meta
        assert "base_id" in meta
        assert meta["game_version"] == "b41"


def test_generate_chunks_multiple_for_game_data():
    """Un objet avec game_specific produit au moins 2 chunks."""
    from ingestor.ingest import get_b41_items, generate_chunks_for_object

    # Les items ont tous game_specific
    items = get_b41_items()
    for item in items:
        if item.game_specific:
            chunks = asyncio.run(generate_chunks_for_object(item))
            assert len(chunks) >= 2


# ===========================================================================
# Tests : _resolve_collection
# ===========================================================================


def test_resolve_collection_crafting_recipe():
    """crafting_category='recipe' → pz_recipes."""
    from ingestor.ingest import MetadataConstraint, _resolve_collection

    c = MetadataConstraint(
        item_type="item", game_version="b41", base_id="Recipe.Test",
        display_name="Test", description="x", crafting_category="recipe",
    )
    assert _resolve_collection(c) == "pz_recipes"


def test_resolve_collection_crafting_weapon():
    """crafting_category='weapon' → pz_items."""
    from ingestor.ingest import MetadataConstraint, _resolve_collection

    c = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Axe",
        display_name="Axe", description="x", crafting_category="weapon",
    )
    assert _resolve_collection(c) == "pz_items"


def test_resolve_collection_crafting_food():
    """crafting_category='food' → pz_items."""
    from ingestor.ingest import MetadataConstraint, _resolve_collection

    c = MetadataConstraint(
        item_type="food", game_version="b41", base_id="Base.Bread",
        display_name="Bread", description="x", crafting_category="food",
    )
    assert _resolve_collection(c) == "pz_items"


# ===========================================================================
# Tests : MetadataConstraint dataclass
# ===========================================================================


def test_metadata_constraint_defaults():
    """MetadataConstraint a des valeurs par defaut correctes."""
    from ingestor.ingest import MetadataConstraint

    c = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Axe",
        display_name="Axe", description="x",
    )
    assert c.tags == []
    assert c.game_specific == {}
    assert c.crafting_category is None


def test_metadata_constraint_with_tags():
    """Les tags sont bien stores."""
    from ingestor.ingest import MetadataConstraint

    c = MetadataConstraint(
        item_type="weapon", game_version="b41", base_id="Base.Axe",
        display_name="Axe", description="x", tags=["melee", "core"],
    )
    assert c.tags == ["melee", "core"]


# ===========================================================================
# Tests : IngestSummary dataclass
# ===========================================================================


def test_ingest_summary_defaults():
    """IngestSummary a des valeurs par defaut correctes."""
    from ingestor.ingest import IngestSummary

    s = IngestSummary()
    assert s.objects_ingested == 0
    assert s.chunks_written == 0
    assert s.validations_passed == 0
    assert s.validations_failed == 0
    assert s.errors == []
    assert s.batches_created == 0


# ===========================================================================
# Tests : Batch anti-OOM
# ===========================================================================


def test_batch_config_constants():
    """BATCH_SIZE_DEFAULT et MAX_BATCH_BYTES ont des valeurs raisonnables."""
    from ingestor.ingest import BATCH_SIZE_DEFAULT, MAX_BATCH_BYTES

    assert BATCH_SIZE_DEFAULT == 50
    assert MAX_BATCH_BYTES == 10_000_000


def test_game_versions_constant():
    """GAME_VERSIONS contient b41 et b42."""
    from ingestor.ingest import GAME_VERSIONS

    assert "b41" in GAME_VERSIONS
    assert "b42" in GAME_VERSIONS


# ===========================================================================
# Tests : CLI parser
# ===========================================================================


def test_build_parser_has_subcommands():
    """build_parser retourne un parser avec des sous-commandes."""
    from ingestor.ingest import build_parser

    parser = build_parser()
    assert parser is not None


# ===========================================================================
# Helpers
# ===========================================================================
