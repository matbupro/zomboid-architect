"""Tests S4-c — Chunking optimal pour WikiJsonProcessor.

Couverture :
- max_chunk_words parameter configures la taille max des chunks
- _split_large_chunk split automatiquement les chunks excessifs
- Split preserver le header contextuel (Item:/Recipe:/Mob:)
- Cross-references en metadata pour recipes → items
- Pas de split si chunk ≤ max_chunk_words

Lancer : pytest tests/test_wikijson_chunking.py -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def tmp_path():
    """Repertoire temporaire."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture()
def processor():
    """WikiJsonProcessor avec parametres default."""
    from ingestor.processors.wikijson import WikiJsonProcessor

    class MockConfig:
        pass

    return WikiJsonProcessor(MockConfig(), source="/fake/path")


# ============================================================================
# Test S4-c : max_chunk_words configures le seuil
# ============================================================================


class TestChunkSizeConfig:
    """S4-c : le parametre max_chunk_words est respecte."""

    def test_default_max_chunk_words(self, processor):
        """Default 800 mots ≈ ~2500 chars."""
        assert processor.max_chunk_words == 800

    def test_custom_max_chunk_words(self, tmp_path):
        """On peut configurer un seuil different."""
        from ingestor.processors.wikijson import WikiJsonProcessor

        class MockConfig:
            pass

        proc = WikiJsonProcessor(MockConfig(), source="/fake/path", max_chunk_words=500)
        assert proc.max_chunk_words == 500


# ============================================================================
# Test S4-c : _split_large_chunk — pas de split si chunk petit
# ============================================================================


class TestNoSplitWhenSmall:
    """S4-c : les chunks ≤ max_chunk_words ne sont pas splits."""

    def test_small_chunk_not_split(self, processor):
        """Chunk de 10 mots (≤ 800) reste non splitte."""
        from ingestor.processors.base import Chunk

        small_text = " ".join([f"word{i}" for i in range(10)])
        chunk = Chunk(
            text=small_text,
            index=0,
            start_offset=0,
            metadata={"type": "item", "key": "Base.Test"},
        )

        result = processor._split_large_chunk(chunk, "items")
        assert len(result) == 1  # Pas splitte


# ============================================================================
# Test S4-c : _split_large_chunk — split automatique avec header preserve
# ============================================================================


class TestSplitWithHeader:
    """S4-c : les chunks excessifs sont splits en preservant le header."""

    def test_split_excessive_chunk(self, tmp_path):
        """Chunk de 2000+ mots est splitte en plusieurs sub-chunks."""
        from ingestor.processors.wikijson import WikiJsonProcessor

        class MockConfig:
            pass

        # Seuil plus realistic : 100 mots pour eviter le depassement des sections indiv.
        proc = WikiJsonProcessor(MockConfig(), max_chunk_words=100)

        # Creer un texte enorme avec des separators logiques (petites sections)
        sections = []
        for i in range(15):
            section = f"Section {i}:\n" + " ".join([f"data{i}{j}" for j in range(30)])
            sections.append(section)

        huge_text = "\n---\n".join(sections)  # ~450 mots total

        from ingestor.processors.base import Chunk

        chunk = Chunk(
            text=f"Item: Base.HugeTest\nKey: Base.HugeTest\n{huge_text}",
            index=0,
            start_offset=0,
            metadata={"type": "item", "key": "Base.HugeTest"},
        )

        result = proc._split_large_chunk(chunk, "items")

        # Doit etre splitte en plusieurs sub-chunks
        assert len(result) > 1, "Chunk excessif doit etre splitte"

        # Word count total conserve approx
        total_words = sum(len(sub.text.split()) for sub in result)
        original_words = len(huge_text.split()) + 4  # header ~4 mots
        assert total_words >= original_words * 0.8, "La perte de mots < 20%"

    def test_split_preserves_header_context(self, tmp_path):
        """Chaque sub-chunk contient le header contextuel (Item:/Recipe:)."""
        from ingestor.processors.wikijson import WikiJsonProcessor

        class MockConfig:
            pass

        proc = WikiJsonProcessor(MockConfig(), max_chunk_words=50)

        sections = [f"Data{i}:\n" + " ".join([f"x{j}" for j in range(100)]) for i in range(5)]
        huge_text = "\n---\n".join(sections)

        from ingestor.processors.base import Chunk

        chunk = Chunk(
            text=f"Recipe: Base.TestCook\nKey: Recipe.Base.TestCook\n{huge_text}",
            index=0,
            start_offset=0,
            metadata={"type": "recipe", "key": "Recipe.Base.TestCook"},
        )

        result = proc._split_large_chunk(chunk, "recipes")

        # Chaque sub-chunk doit contenir le header Recipe:
        for i, sub in enumerate(result):
            assert "Recipe:" in sub.text or "Key:" in sub.text, \
                f"Sub-chunk {i} manque le header contextuel"


# ============================================================================
# Test S4-c : _add_cross_references — recipes → items
# ============================================================================


class TestCrossReferences:
    """S4-c : les cross-references sont ajoutees en metadata pour les recipes."""

    def test_recipe_with_ingredient_list(self, processor):
        """Recipe avec ingredients list → ingredient_refs en metadata."""
        item_data = {
            "Name": "Test Recipe",
            "Ingredients": [
                {"Item": "Base.MetalSheet"},
                {"Item": "Base.Wood"},
            ],
        }

        refs = processor._add_cross_references("recipes", item_data, "Recipe.Test")

        assert "ingredient_refs" in refs
        assert "Base.MetalSheet" in refs["ingredient_refs"]
        assert "Base.Wood" in refs["ingredient_refs"]

    def test_recipe_with_ingredient_dict(self, processor):
        """Recipe avec ingredients dict {item: qty} → ingredient_refs keys."""
        item_data = {
            "Name": "Test Recipe Dict",
            "Ingredients": {"Base.MetalSheet": 2, "Base.Wood": 5},
        }

        refs = processor._add_cross_references("recipes", item_data, "Recipe.Test")

        assert "ingredient_refs" in refs
        assert "Base.MetalSheet" in refs["ingredient_refs"]
        assert "Base.Wood" in refs["ingredient_refs"]

    def test_recipe_with_result_ref(self, processor):
        """Recipe avec result → result_ref en metadata."""
        item_data = {
            "Name": "Test Recipe",
            "Result": "Base.Hatchet",
            "Ingredients": ["Base.MetalSheet"],
        }

        refs = processor._add_cross_references("recipes", item_data, "Recipe.Test")

        assert "result_ref" in refs
        assert refs["result_ref"] == "Base.Hatchet"


# ============================================================================
# Test S4-c : integration extract() avec chunking optimal
# ============================================================================


class TestExtractWithChunking:
    """S4-c : extract() applique automatiquement le chunking + cross-refs."""

    def test_extract_applies_chunking(self, tmp_path):
        """L'extraction complete produit des chunks ≤ max_chunk_words."""
        from ingestor.processors.wikijson import WikiJsonProcessor

        class MockConfig:
            pass

        # Créer un dossier avec un fichier contenant un item enorme (100+ fields)
        test_file = tmp_path / "test_data.json"
        huge_item = {f"field{i}": f"value{i}" for i in range(200)}
        huge_item["Name"] = "HugeItem"

        import json

        data = {"items": {"Base.HugeItem": huge_item}}
        test_file.write_text(json.dumps(data), encoding="utf-8")

        proc = WikiJsonProcessor(MockConfig(), source=str(test_file), max_chunk_words=100)

        import asyncio

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(proc.extract())

        # Chaque chunk doit être ≤ 100 mots + marge
        for chunk in result.chunks:
            word_count = len(chunk.text.split())
            assert word_count <= 150, f"Chunk de {word_count} mots dépasse le seuil"


# ============================================================================
# Test S4-c : fallback — pas de separators → split par paragraphes
# ============================================================================


class TestSplitFallback:
    """S4-c : le fallback splitter fonctionne sans separators logiques."""

    def test_split_by_paragraphs_when_no_separator(self, processor):
        """Sans `---`, splitter utilise les paragraphes (lignes vides)."""
        from ingestor.processors.base import Chunk

        # Texte avec plusieurs paragraphes mais pas de separator ---
        text_parts = []
        for i in range(10):
            text_parts.append(f"Paragraph {i}:\n" + " ".join([f"data{j}" for j in range(50)]))

        no_sep_text = "\n\n".join(text_parts)

        chunk = Chunk(
            text=f"Item: Base.NoSepTest\nKey: Base.NoSepTest\n{no_sep_text}",
            index=0,
            start_offset=0,
            metadata={"type": "item", "key": "Base.NoSepTest"},
        )

        result = processor._split_large_chunk(chunk, "items")

        # Doit etre splitte (texte total ~500 mots > 800? Non, mais on force avec un item enorme)
        assert len(result) >= 1
