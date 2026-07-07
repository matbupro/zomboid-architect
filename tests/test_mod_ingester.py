"""test_mod_ingester — Tests du module mod_ingester.

Focus : gestion dossiers inexistants, fichiers manquants, structure retour.
Tous les appels [storage vectoriel] sont mockes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestor.steam.mod_ingester import ModIngestionResult, ingest_mods_from_directory


# ===========================================================================
# Tests : ingest_mods_from_directory
# ===========================================================================


def test_invalid_directory_returns_empty():
    """Dossier inexistant → liste vide (pas d'exception)."""
    result = _run_async(ingest_mods_from_directory("/nonexistent/path/that/does/not/exist"))
    assert len(result) == 0


@pytest.mark.asyncio
async def test_ingest_non_numeric_dir():
    """Dossier avec sous-dossier non-numerique → ignoré."""
    with tempfile.TemporaryDirectory() as tmp:
        mods_dir = Path(tmp) / "mods"
        mods_dir.mkdir()
        # Un seul dossier non-numeric (doit etre ignore par ingest_mods_from_directory)
        bad = mods_dir / "not_numeric"
        bad.mkdir()

        with patch("ingestor.steam.mod_ingester.WorkshopScanner") as Mock:
            Mock.return_value.scan = MagicMock(return_value=[])
            results = await ingest_mods_from_directory(mods_dir)
            # 0 mod numeric → liste vide
            assert len(results) == 0


@pytest.mark.asyncio
async def test_ingest_single_numeric_mod():
    """Dossier avec un sous-dossier numeric → appelle ingest_single_mod."""
    with tempfile.TemporaryDirectory() as tmp:
        mods_dir = Path(tmp) / "mods"
        mods_dir.mkdir()

        mod_dir = mods_dir / "1000001"
        mod_dir.mkdir()
        (mod_dir / "addoninfo.txt").write_text(
            'name "Mod Test"\nauthor "Auth"\ndescription "Desc"\n',
            encoding="utf-8",
        )

        with patch("ingestor.steam.mod_ingester.WorkshopScanner") as Mock:
            # Scanner qui retourne 1 mod pour que le scan fonctionne
            mock_scanner = MagicMock()
            mock_mod = MagicMock(mod_id=1000001, name="Mod Test", author="Auth", description="Desc", file_count=1)
            async def _scan():
                return [mock_mod]
            mock_scanner.scan = _scan
            Mock.return_value = mock_scanner

            # Mock StorageWriter pour eviter connexion reale
            with patch("ingestor.steam.mod_ingester.StorageWriter") as MockWriter:
                MockWriter.return_value.write_chunks = MagicMock(return_value=0)
                results = await ingest_mods_from_directory(mods_dir)

                assert len(results) >= 1
                # Le mod numeric devrait etre detecte
                assert any(r.mod_id == 1000001 for r in results)


# ===========================================================================
# Tests : ModIngestionResult dataclass
# ===========================================================================


def test_ingestion_result_defaults():
    """ModIngestionResult avec ses valeurs par defaut."""
    r = ModIngestionResult()
    assert r.mod_id is None
    assert r.success is False
    assert r.chunks_written == 0
    assert r.collection == "pz_mods"
    assert r.errors == []
    assert r.metadata_ == {}


def test_ingestion_result_with_values():
    """ModIngestionResult avec valeurs personnalisées."""
    r = ModIngestionResult(
        mod_id=12345, success=True, chunks_written=10, collection="pz_mods", errors=["err1"],
    )
    assert r.mod_id == 12345
    assert r.success is True
    assert r.chunks_written == 10
    assert r.errors == ["err1"]


# ===========================================================================
# Tests : MOD_COLLECTION_MAP (routing)
# ===========================================================================


def test_collection_map_has_expected_keys():
    """MOD_COLLECTION_MAP contient les extensions attendues."""
    from ingestor.steam.mod_ingester import MOD_COLLECTION_MAP

    assert ".lua" in MOD_COLLECTION_MAP
    assert ".pbo" in MOD_COLLECTION_MAP
    assert MOD_COLLECTION_MAP[".pbo"] == "pz_mod_configs"


def test_collection_map_excludes_text():
    """Les fichiers texte (.txt) ne doivent pas aller dans pz_mod_configs."""
    from ingestor.steam.mod_ingester import MOD_COLLECTION_MAP

    # .txt n'est pas dans le map → reste dans la collection par defaut (pz_mods)
    assert ".txt" not in MOD_COLLECTION_MAP


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
