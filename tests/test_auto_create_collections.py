"""Tests S4-i — Auto-create collections sur tous les backends.

Couverture :
- StorageBackend.ensure_collection cree la collection SQLite par defaut
- StorageWriter.write_chunks_to_storage appelle ensure_collection avant écriture
- Qdrant ensure_collection appele quand backend=qdrant + qdrant_ready=True
- _sync_embeddings_qdrant auto-create avant batch_upsert

Lancer : pytest tests/test_auto_create_collections.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clean_env():
    """Desactiver STORAGE_BACKEND pour eviter la connexion Qdrant reelle."""
    old = os.environ.pop("STORAGE_BACKEND", None)
    yield
    if old is not None:
        os.environ["STORAGE_BACKEND"] = old


@pytest.fixture()
def tmp_path():
    """Repertoire temporaire."""
    td = tempfile.TemporaryDirectory()
    yield Path(td.name)
    gc = __import__("gc")
    gc.collect()


# ============================================================================
# Test S4-i : ensure_collection auto-create (SQLite via StorageBackend)
# ============================================================================


class TestAutoCreateSQLite:
    """Auto-create collections sur StorageBackend."""

    def test_ensure_collection_creates_table(self, tmp_path):
        """ensure_collection cree la table si elle n'existe pas."""
        from src.storage.sqlite_storage import StorageBackend, _load_storage_config

        cfg = _load_storage_config()
        cfg.data_dir = str(tmp_path)
        backend = StorageBackend(data_dir=str(tmp_path), config=cfg)

        result = backend.ensure_collection("pz_test_items")
        assert result is True

    def test_ensure_collection_no_double_create(self, tmp_path):
        """Deux appels ne recréent pas la table."""
        from src.storage.sqlite_storage import StorageBackend, _load_storage_config

        cfg = _load_storage_config()
        cfg.data_dir = str(tmp_path)
        backend = StorageBackend(data_dir=str(tmp_path), config=cfg)

        backend.ensure_collection("pz_test_dupe")
        result = backend.ensure_collection("pz_test_dupe")
        assert result is False


# ============================================================================
# Test S4-i : StorageWriter ensure_collection + write_chunks_to_storage
# ============================================================================


class TestAutoCreateStorageWriter:
    """StorageWriter ensure_collection et write_chunks_to_storage auto-create."""

    def test_writer_ensure_collection(self, tmp_path):
        """StorageWriter.ensure_collection cree la collection via _backend."""
        from ingestor.storage.storage_writer import StorageWriter

        writer = StorageWriter(ollama_url="http://localhost:11434")

        mock_backend = MagicMock()
        mock_backend.ensure_collection = MagicMock(return_value=True)
        mock_backend.list_collections = MagicMock(return_value=[])
        mock_backend.count_collection = MagicMock(return_value=0)
        mock_backend.write_chunks = MagicMock(return_value=1)
        mock_backend.query = MagicMock(return_value=[])
        writer._backend = mock_backend

        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(writer.ensure_collection("pz_test_writer"))
        mock_backend.ensure_collection.assert_called_once_with("pz_test_writer")

    def test_writer_write_chunks_auto_create(self, tmp_path):
        """write_chunks_to_storage appelle ensure_collection avant écriture."""
        from ingestor.storage.storage_writer import StorageWriter
        from src.governance.logger import get_logger

        logger = get_logger("ingestor.storage.storage_writer")
        logger.setLevel(50)

        writer = StorageWriter(ollama_url="http://localhost:11434")

        mock_backend = MagicMock()
        mock_backend.ensure_collection = MagicMock(return_value=True)
        mock_backend.list_collections = MagicMock(return_value=[])
        mock_backend.count_collection = MagicMock(return_value=0)
        mock_backend.write_chunks = MagicMock(return_value=1)
        mock_backend.query = MagicMock(return_value=[])
        writer._backend = mock_backend

        writer._embedder.embed_batch = MagicMock(return_value=[[0.0] * 768])

        import asyncio

        class Chunk:
            def __init__(self, text, metadata=None):
                self.text = text
                self.metadata = metadata or {}

        chunks = [
            Chunk("test chunk 1", {"source": "test"}),
            Chunk("test chunk 2", {"source": "test"}),
        ]

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            writer.write_chunks_to_storage(
                chunks=chunks, source="test_source", collection="pz_new_collection"
            )
        )

        mock_backend.ensure_collection.assert_called_once_with("pz_new_collection")
        assert result is True


# ============================================================================
# Test S4-i : Qdrant ensure_collection (STORAGE_BACKEND=qdrant)
# ============================================================================


class TestAutoCreateQdrant:
    """S4-i : Qdrant collection auto-create quand backend=qdrant + qdrant_ready=True."""

    def test_ensure_collection_calls_qdrant_when_ready(self, tmp_path):
        """Quand _qdrant_ready=True, ensure_collection propage sur Qdrant."""
        # Forcer le mode qdrant via env (c'est StorageBackend.__init__ qui lit cfg)
        os.environ["STORAGE_BACKEND"] = "qdrant"

        from src.storage.sqlite_storage import StorageBackend, _load_storage_config

        cfg = _load_storage_config()
        cfg.data_dir = str(tmp_path)
        # Pointer vers un port inconnu pour que la connexion echoue silencieusement
        os.environ["STORAGE_QDRANT_URL"] = "http://localhost:19999"  # pas de real serveur

        with patch("src.storage.qdrant_backend.QdrantVectorBackend") as MockQdrant:
            mock_qdb = MagicMock()
            mock_qdb.ensure_collection = MagicMock(return_value=True)
            MockQdrant.return_value = mock_qdb

            backend = StorageBackend(data_dir=str(tmp_path), config=cfg)

            # _qdrant_ready doit etre True car _ensure_qd retourne le mock (connecte)
            assert backend._qdrant_ready, "Qdrant doit etre pret (mock)"
            assert backend._backend_type == "qdrant", f"Type={backend._backend_type}"

            result = backend.ensure_collection("pz_test_qdrant")

            assert mock_qdb.ensure_collection.called, \
                f"Qdrant ensure_collection non appele — _backend_type={backend._backend_type}, _qdrant_ready={backend._qdrant_ready}"
            assert mock_qdb.ensure_collection.call_args[0][0] == "pz_test_qdrant"

    def test_ensure_collection_fallback_no_crash(self, tmp_path):
        """Meme sans Qdrant, ensure_collection fonctionne (SQLite)."""
        from src.storage.sqlite_storage import StorageBackend, _load_storage_config

        cfg = _load_storage_config()
        cfg.data_dir = str(tmp_path)
        backend = StorageBackend(data_dir=str(tmp_path), config=cfg)

        result = backend.ensure_collection("pz_fallback_test")
        assert isinstance(result, bool)


# ============================================================================
# Test S4-i : _sync_embeddings_qdrant auto-create avant batch_upsert
# ============================================================================


class TestAutoCreateQdrantSync:
    """S4-i : _sync_embeddings_qdrant auto-create la collection avant upsert."""

    def test_sync_embeddings_calls_ensure_collection(self, tmp_path):
        """_sync_embeddings_qdrant appelle ensure_collection AVANT batch_upsert."""
        os.environ["STORAGE_BACKEND"] = "qdrant"
        os.environ["STORAGE_QDRANT_URL"] = "http://localhost:19999"

        from src.storage.sqlite_storage import StorageBackend, _load_storage_config

        cfg = _load_storage_config()
        cfg.data_dir = str(tmp_path)

        with patch("src.storage.qdrant_backend.QdrantVectorBackend") as MockQdrant:
            mock_qdb = MagicMock()
            mock_qdb.ensure_collection = MagicMock(return_value=True)
            mock_qdb.batch_upsert = MagicMock(return_value=True)
            MockQdrant.return_value = mock_qdb

            backend = StorageBackend(data_dir=str(tmp_path), config=cfg)

            assert backend._qdrant_ready, "Qdrant doit etre pret"

            class Chunk:
                def __init__(self, text, metadata=None):
                    self.text = text
                    self.metadata = metadata or {}

            chunks = [Chunk("test sync chunk", {"source": "test"})]

            written = backend.write_chunks(chunks, "pz_sync_test", "test_source")

            assert mock_qdb.ensure_collection.called, \
                "_sync_embeddings_qdrant doit appeler ensure_collection avant batch_upsert (S4-i)"
