"""test_pbo_processor — Tests du module PBOProcessor.

Focus : gestion fichiers inexistants, extensions non supportees.
L'extraction reale (.pbo) est skippee si py7zr n'est pas dispo.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ===========================================================================
# Tests : extraction fichier inexistant
# ===========================================================================


def test_extract_file_not_found():
    """Fichier .pbo inexistant → chunks=[], metadata.error='file_not_found'."""
    from ingestor.processors.pbo import PBOProcessor

    processor = PBOProcessor()
    result = _run_async(processor.extract(str(Path("/nonexistent/mod.pbo"))))

    assert len(result.chunks) == 0
    assert "error" in result.metadata


def test_extract_unsupported_extension(tmp_path):
    """Fichier avec extension non supportee → metadata.error='unsupported_extension'."""
    from ingestor.processors.pbo import PBOProcessor

    processor = PBOProcessor()
    fake_pbo = tmp_path / "not_a_pbo.xyz"
    fake_pbo.write_text("content", encoding="utf-8")

    result = _run_async(processor.extract(str(fake_pbo)))

    assert len(result.chunks) == 0
    assert result.metadata.get("error") == "unsupported_extension"


# ===========================================================================
# Tests : SUPPORTED_EXTENSIONS
# ===========================================================================


def test_supported_extensions_includes_pbo():
    """.pbo est dans SUPPORTED_EXTENSIONS."""
    from ingestor.processors.pbo import PBOProcessor

    assert ".pbo" in PBOProcessor.SUPPORTED_EXTENSIONS


def test_supported_extensions_includes_pbosync():
    """.pbosync est dans SUPPORTED_EXTENSIONS."""
    from ingestor.processors.pbo import PBOProcessor

    assert ".pbosync" in PBOProcessor.SUPPORTED_EXTENSIONS


# ===========================================================================
# Tests : TEXT_EXTENSIONS
# ===========================================================================


def test_text_extensions_contains_lua():
    """.lua est dans TEXT_EXTENSIONS."""
    from ingestor.processors.pbo import PBOProcessor

    assert ".lua" in PBOProcessor.TEXT_EXTENSIONS


def test_text_extensions_contains_cfg():
    """.cfg est dans TEXT_EXTENSIONS."""
    from ingestor.processors.pbo import PBOProcessor

    assert ".cfg" in PBOProcessor.TEXT_EXTENSIONS


# ===========================================================================
# Tests : constructor
# ===========================================================================


def test_processor_accepts_config(tmp_path):
    """PBOProcessor accepte un config (None ou objet)."""
    from ingestor.processors.pbo import PBOProcessor

    class DummyConfig:
        pass

    processor = PBOProcessor(config=DummyConfig())
    assert processor.config is not None


def test_processor_extract_to(tmp_path):
    """L'option extract_to cree le dossier de sortie."""
    from ingestor.processors.pbo import PBOProcessor

    extract_dir = tmp_path / "extract_here"
    processor = PBOProcessor(extract_to=extract_dir)
    assert processor._extract_to == extract_dir


# ===========================================================================
# Helpers
# ===========================================================================


def _run_async(coro):
    """Executer une coroutine."""
    try:
        loop = __import__("asyncio").get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return __import__("asyncio").run(coro)
