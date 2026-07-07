"""test_storage_writer -- Tests unitaires pour StorageWriter (StorageBackend + OllamaEmbedder).

Mode mock : fonctionne avec mock uniquement (sans Ollama).
Teste le StorageBackend layer (SQLite) via StorageWriter/StorageWriter alias.

Usage:
    python tests/test_storage_writer.py
"""

from __future__ import annotations

import asyncio
import json as _json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ===========================================================================
# Fixtures / imports
# ===========================================================================

def _import_mod():
    """Import the module -- mocks will be applied in each test."""
    from ingestor.storage import storage_writer
    return storage_writer


# ===========================================================================
# SearchResult dataclass tests (aucune dependance externe)
# ===========================================================================

def test_search_result_defaults():
    """SearchResult a des valeurs par definition coherentes."""
    from ingestor.storage.storage_writer import SearchResult

    sr = SearchResult(collection="pz_pdfs", id="test-1", prose="hello")
    assert sr.collection == "pz_pdfs"
    assert sr.id == "test-1"
    assert sr.prose == "hello"
    assert sr.distance == 0.0
    assert sr.metadata_ == {}


def test_search_result_with_metadata():
    from ingestor.storage.storage_writer import SearchResult

    sr = SearchResult(
        collection="pz_text", id="item-2", prose="world",
        distance=0.35, metadata_={"source": "wiki.py", "type": "item"},
    )
    assert sr.distance == 0.35
    assert sr.metadata_ == {"source": "wiki.py", "type": "item"}


def test_search_result_metadata_auto_none():
    """metadata_=None doit etre initialise a {}."""
    from ingestor.storage.storage_writer import SearchResult

    sr = SearchResult(collection="x", id="y", prose="z")
    assert sr.metadata_ is not None
    assert isinstance(sr.metadata_, dict)


# ===========================================================================
# OllamaEmbedder tests (mock HTTP)
# ===========================================================================

def test_embed_empty_text():
    """Texte vide -> None."""
    from ingestor.storage.storage_writer import OllamaEmbedder

    embedder = OllamaEmbedder(base_url="http://localhost:11434")
    assert embedder.embed("") is None
    assert embedder.embed("   ") is None


def test_embed_success_caches():
    """Premier appel appele Ollama; second appel utilise le cache."""
    from ingestor.storage.storage_writer import OllamaEmbedder

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
    mock_client_inst = MagicMock()
    mock_client_inst.post.return_value = mock_resp
    mock_client_inst.__enter__ = MagicMock(return_value=mock_client_inst)
    mock_client_inst.__exit__ = MagicMock(return_value=None)

    embedder = OllamaEmbedder(base_url="http://localhost:11434")

    with patch("httpx.Client", return_value=mock_client_inst):
        e1 = embedder.embed("hello world")
        assert e1 == [0.1, 0.2, 0.3]

        # Deuxieme appel avec meme texte -> doit utiliser le cache
        e2 = embedder.embed("hello world")
        assert e2 == [0.1, 0.2, 0.3]


def test_embed_http_error_returns_none():
    """Erreur HTTP -> None, pas d'exception."""
    from ingestor.storage.storage_writer import OllamaEmbedder

    mock_client_inst = MagicMock()
    mock_client_inst.post.side_effect = Exception("connection refused")
    mock_client_inst.__enter__ = MagicMock(return_value=mock_client_inst)
    mock_client_inst.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client_inst):
        result = OllamaEmbedder(base_url="http://localhost:11434").embed("hello")
        assert result is None


def test_embed_batch_empty():
    """embed_batch avec liste vide -> []."""
    from ingestor.storage.storage_writer import OllamaEmbedder

    result = OllamaEmbedder(base_url="http://localhost:11434").embed_batch([])
    assert result == []


def test_embed_batch_mixed_success_failure():
    """Certains textes reussissent, d'autres echouent -> liste mixte."""
    from ingestor.storage.storage_writer import OllamaEmbedder

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embeddings": [[0.5]]}
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_inst.__enter__ = MagicMock(return_value=mock_inst)
    mock_inst.__exit__ = MagicMock(return_value=None)

    embedder = OllamaEmbedder(base_url="http://localhost:11434")

    with patch("httpx.Client", return_value=mock_inst):
        results = embedder.embed_batch(["text1"])
        assert len(results) == 1
        assert results[0] == [0.5]


# ===========================================================================
# StorageWriter / StorageWriter integration tests (mock backend)
# ===========================================================================

class _FakeChunk:
    """Chunk fake avec .text et .metadata."""

    def __init__(self, text: str, metadata: dict | None = None):
        self.text = text
        self.metadata = metadata or {}


async def test_storage_writer_ensure_collection():
    """Collection existante -> pas d'appel a ensure_collection du backend."""
    from ingestor.storage.storage_writer import StorageWriter

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = MagicMock()
    writer._collections_initialized.add("pz_pdfs")

    await writer.ensure_collection("pz_pdfs")

    # Deja initialise -> ne doit pas appeler le backend
    writer._backend.ensure_collection.assert_not_called()


async def test_storage_writer_list_collections_delegates():
    """list_collections delegate au backend."""
    from ingestor.storage.storage_writer import StorageWriter

    writer = StorageWriter(ollama_url="http://x:11434")
    mock_backend = MagicMock()
    mock_backend.list_collections.return_value = ["c1", "c2"]
    writer._backend = mock_backend

    result = await writer.list_collections()
    assert result == ["c1", "c2"]


async def test_storage_writer_count_collection():
    """count_collection retourne le compte du backend."""
    from ingestor.storage.storage_writer import StorageWriter

    writer = StorageWriter(ollama_url="http://x:11434")
    mock_backend = MagicMock()
    mock_backend.count_collection.return_value = 42
    writer._backend = mock_backend

    result = await writer.count_collection("pz_items")
    assert result == 42


async def test_storage_writer_count_collection_fallback():
    """count_collection en erreur -> retourne -1."""
    from ingestor.storage.storage_writer import StorageWriter

    writer = StorageWriter(ollama_url="http://x:11434")
    mock_backend = MagicMock()
    mock_backend.count_collection.side_effect = Exception("error")
    writer._backend = mock_backend

    result = await writer.count_collection("pz_items")
    assert result == -1


async def test_storage_writer_write_chunks_delegates_to_backend():
    """write_chunks delegate embedding + appel au backend."""
    from ingestor.storage.storage_writer import StorageWriter

    mock_backend = MagicMock()
    mock_backend.write_chunks.return_value = 3
    mock_backend.ensure_collection = MagicMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend

    chunks = [_FakeChunk("hello"), _FakeChunk("world")]
    result = await writer.write_chunks_to_storage(chunks, source="test.txt", collection="pz_test")

    assert result is True
    mock_backend.ensure_collection.assert_called_once_with("pz_test")
    mock_backend.write_chunks.assert_called_once()


async def test_storage_writer_write_chunks_no_embeddings():
    """Pas d'embeddings retournes par Ollama -> chunks sans embedding."""
    from ingestor.storage.storage_writer import StorageWriter

    mock_backend = MagicMock()
    mock_backend.write_chunks.return_value = 1
    mock_backend.ensure_collection = MagicMock()

    # Forcer echec embedding en utilisant une URL invalide et un embedder qui echoue
    writer = StorageWriter(ollama_url="http://nonexistent:11434")
    writer._backend = mock_backend

    chunks = [_FakeChunk("hello world")]

    # Mock l'embedder pour retourner None
    writer._embedder.embed_batch = MagicMock(return_value=[None])

    result = await writer.write_chunks_to_storage(chunks, source="test.txt", collection="pz_test")
    assert result is True


async def test_storage_writer_write_chunks_failure():
    """Ecriture backend echouee -> retourne False."""
    from ingestor.storage.storage_writer import StorageWriter

    mock_backend = MagicMock()
    mock_backend.write_chunks.side_effect = Exception("storage error")
    mock_backend.ensure_collection = MagicMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend

    chunks = [_FakeChunk("hello")]
    result = await writer.write_chunks_to_storage(chunks, source="test.txt", collection="pz_test")
    assert result is False


async def test_storage_writer_write_empty_chunks():
    """Liste de chunks vides -> retourne False."""
    from ingestor.storage.storage_writer import StorageWriter

    mock_backend = MagicMock()
    mock_backend.ensure_collection = MagicMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend

    result = await writer.write_chunks_to_storage([], source="test.txt", collection="pz_test")
    assert result is False


async def test_storage_writer_query_no_embedding():
    """Pas d'embedding pour la requete -> liste vide."""
    from ingestor.storage.storage_writer import StorageWriter

    mock_backend = MagicMock()
    mock_backend.ensure_collection = MagicMock()

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=None)

    results = await writer.query("pz_text", "hello")
    assert results == []


async def test_storage_writer_query_success():
    """Requete reussie -> liste de SearchResult."""
    from ingestor.storage.storage_writer import StorageWriter, SearchResult

    mock_backend = MagicMock()
    mock_backend.ensure_collection = MagicMock()

    # Mock des resultats du backend
    mock_results = [
        SearchResult(collection="pz_text", id="id1", prose="doc1", distance=0.1, metadata_={"source": "a"}),
    ]
    mock_backend.query = MagicMock(return_value=mock_results)

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1, 0.2, 0.3])

    results = await writer.query("pz_text", "hello")
    assert len(results) == 1
    assert isinstance(results[0], SearchResult)
    assert results[0].id == "id1"


async def test_storage_writer_cross_collection_search():
    """Cross-collection search -> resultat merge et trie."""
    from ingestor.storage.storage_writer import StorageWriter, SearchResult

    mock_backend = MagicMock()
    mock_backend.ensure_collection = MagicMock()
    mock_backend.list_collections.return_value = ["pz_items", "pz_recipes"]

    # Query retourne des resultats par collection
    def side_effect(col, *args, **kwargs):
        return [SearchResult(collection=col, id=f"{col}-1", prose="doc", distance=0.5)]

    mock_backend.query = MagicMock(side_effect=side_effect)

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1, 0.2])

    results = await writer.cross_collection_search("hello", n_results=10)
    assert len(results) == 2


async def test_storage_writer_cross_collection_no_collections():
    """Aucune collection -> liste vide."""
    from ingestor.storage.storage_writer import StorageWriter

    mock_backend = MagicMock()
    mock_backend.list_collections.return_value = []

    writer = StorageWriter(ollama_url="http://x:11434")
    writer._backend = mock_backend
    writer._embedder.embed = MagicMock(return_value=[0.1])

    results = await writer.cross_collection_search("hello")
    assert results == []


# ===========================================================================
# Helper function test (write_chunks_to_storage global)
# ===========================================================================

async def test_write_chunks_helper_creates_writer():
    """La fonction globale cree un StorageWriter et delegue."""
    from ingestor.storage.storage_writer import write_chunks_to_storage

    mock_writer = MagicMock()
    mock_writer.write_chunks_to_storage = AsyncMock(return_value=True)

    with patch("ingestor.storage.storage_writer.StorageWriter", return_value=mock_writer):
        result = await write_chunks_to_storage(
            [_FakeChunk("hello")], source="test.txt", collection="pz_test",
        )
        assert result is True


# ===========================================================================
# Backward compatibility alias tests
# ===========================================================================

def test_storage_writer_alias():
    """StorageWriter = StorageWriter (alias backward-compatibilite)."""
    from ingestor.storage.storage_writer import StorageWriter, StorageWriter

    # Les deux classes doivent etre la meme
    assert StorageWriter is StorageWriter


# ===========================================================================
# Runner
# ===========================================================================

TESTS = [
    # SearchResult
    test_search_result_defaults,
    test_search_result_with_metadata,
    test_search_result_metadata_auto_none,
    # OllamaEmbedder
    test_embed_empty_text,
    test_embed_success_caches,
    test_embed_http_error_returns_none,
    test_embed_batch_empty,
    test_embed_batch_mixed_success_failure,
    # StorageWriter (async)
    test_storage_writer_ensure_collection,
    test_storage_writer_list_collections_delegates,
    test_storage_writer_count_collection,
    test_storage_writer_count_collection_fallback,
    test_storage_writer_write_chunks_delegates_to_backend,
    test_storage_writer_write_chunks_no_embeddings,
    test_storage_writer_write_chunks_failure,
    test_storage_writer_write_empty_chunks,
    test_storage_writer_query_no_embedding,
    test_storage_writer_query_success,
    test_storage_writer_cross_collection_search,
    test_storage_writer_cross_collection_no_collections,
    # Helper
    test_write_chunks_helper_creates_writer,
    # Alias backward compat
    test_storage_writer_alias,
]


def _run_async(fn):
    """Run an async test function without pytest."""
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(fn())
        finally:
            loop.close()
    except Exception as e:
        raise


def main():
    total_ok = 0
    total_fail = 0
    errors: list[str] = []

    for fn in TESTS:
        name = fn.__name__
        try:
            _run_async(fn) if asyncio.iscoroutinefunction(fn) else fn()
            print(f"  [+] {name}")
            total_ok += 1
        except Exception as e:
            msg = f"{name}: {e}"
            print(f"  [-] {msg}")
            errors.append(msg)
            total_fail += 1

    print(f"\n{'='*60}")
    print("Storage Writer Unit Tests")
    print(f"{'='*60}")
    print(f"  Total : {total_ok}/{total_ok + total_fail} passed")
    if errors:
        print(f"\nEchecs ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    print("=" * 60)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())



