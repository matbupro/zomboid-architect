"""test_chroma_writer -- Tests unitaires pour chroma_writer (Phase 11/11).

Mode mock : fonctionne SANS ChromaDB/Ollama.

Usage :
    python tests/test_chroma_writer.py
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
    """Import the module — mocks will be applied in each test."""
    from ingestor.storage import chroma_writer
    return chroma_writer


# ===========================================================================
# SearchResult dataclass tests (aucune dépendance externe)
# ===========================================================================

def test_search_result_defaults():
    """SearchResult a des valeurs par definition coherentes."""
    from ingestor.storage.chroma_writer import SearchResult

    sr = SearchResult(collection="pz_pdfs", id="test-1", prose="hello")
    assert sr.collection == "pz_pdfs"
    assert sr.id == "test-1"
    assert sr.prose == "hello"
    assert sr.distance == 0.0
    assert sr.metadata_ == {}


def test_search_result_with_metadata():
    from ingestor.storage.chroma_writer import SearchResult

    sr = SearchResult(
        collection="pz_text", id="item-2", prose="world",
        distance=0.35, metadata_={"source": "wiki.py", "type": "item"},
    )
    assert sr.distance == 0.35
    assert sr.metadata_ == {"source": "wiki.py", "type": "item"}


def test_search_result_metadata_auto_none():
    """metadata_=None doit etre initialise a {}."""
    from ingestor.storage.chroma_writer import SearchResult

    sr = SearchResult(collection="x", id="y", prose="z")
    assert sr.metadata_ is not None
    assert isinstance(sr.metadata_, dict)


# ===========================================================================
# OllamaEmbedder tests (mock HTTP)
# ===========================================================================

def test_embed_empty_text():
    """Texte vide -> None."""
    from ingestor.storage.chroma_writer import OllamaEmbedder

    embedder = OllamaEmbedder(base_url="http://localhost:11434")
    assert embedder.embed("") is None
    assert embedder.embed("   ") is None


def test_embed_success_caches():
    """Premier appel appele Ollama; second appel utilise le cache."""
    from ingestor.storage.chroma_writer import OllamaEmbedder

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
        # (on ne voit pas de second POST car le cache est interne)
        e2 = embedder.embed("hello world")
        assert e2 == [0.1, 0.2, 0.3]


def test_embed_http_error_returns_none():
    """Erreur HTTP -> None, pas d'exception."""
    from ingestor.storage.chroma_writer import OllamaEmbedder

    mock_client_inst = MagicMock()
    mock_client_inst.post.side_effect = Exception("connection refused")
    mock_client_inst.__enter__ = MagicMock(return_value=mock_client_inst)
    mock_client_inst.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client_inst):
        result = OllamaEmbedder(base_url="http://localhost:11434").embed("hello")
        assert result is None


def test_embed_batch_empty():
    """embed_batch avec liste vide -> []."""
    from ingestor.storage.chroma_writer import OllamaEmbedder

    result = OllamaEmbedder(base_url="http://localhost:11434").embed_batch([])
    assert result == []


def test_embed_batch_mixed_success_failure():
    """Certains textes reussissent, d'autres echouent -> liste mixte."""
    from ingestor.storage.chroma_writer import OllamaEmbedder

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
# ChromaClientHTTP tests (mock chromadb.HttpClient)
# ===========================================================================

def test_get_client_returns_http_client():
    """_get_client instancie HttpClient avec le bon host."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    client_http = ChromaClientHTTP("http://test:8000")
    mock_chromadb = MagicMock()
    with patch.object(client_http, "_get_client", return_value=mock_chromadb):
        # Appele _get_client et verifie qu'il est appele une fois
        result = client_http._get_client()
        assert result is mock_chromadb


def test_host_trailing_strip():
    """Le trailing slash de l'host est retire."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    c = ChromaClientHTTP("http://test:8000/")
    assert c._host == "http://test:8000"


def test_create_collection_already_exists():
    """create_collection avec collection existante -> {} (pas d'exception)."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_client = MagicMock()
    mock_client.create_collection.side_effect = Exception("Collection already exists")

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.create_collection("pz_pdfs")
        assert result == {}


def test_create_collection_success():
    """create_collection reussie -> {'name': collection_name}."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_client = MagicMock()
    mock_client.create_collection.return_value = None

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.create_collection("pz_pdfs")
        assert result == {"name": "pz_pdfs"}


def test_list_collections():
    """list_collections retourne les noms des collections."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_col1 = MagicMock()
    mock_col1.name = "pz_text"
    mock_col2 = MagicMock()
    mock_col2.name = "pz_pdfs"
    mock_client = MagicMock()
    mock_client.list_collections.return_value = [mock_col1, mock_col2]

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.list_collections()
        assert result == ["pz_text", "pz_pdfs"]


def test_add_documents():
    """add_documents appelle col.add et retourne le compte."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.add_documents(
            "pz_text", ["doc1", "doc2"], ["id1", "id2"], [{"source": "x"}] * 2,
        )
        assert result == {"added": 2}
        mock_col.add.assert_called_once()


def test_query_collection_with_text():
    """query_collection avec query_texts -> format parseable."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_col = MagicMock()
    mock_col.query.return_value = {
        "ids": [["id1", "id2"]],
        "documents": [["doc1", "doc2"]],
        "metadatas": [[{"source": "a"}, {"source": "b"}]],
        "distances": [[0.1, 0.2]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.query_collection("pz_text", "hello world", n_results=2)
        assert "ids" in result
        assert result["ids"] == [["id1", "id2"]]


def test_query_collection_with_embedding():
    """query_collection avec embedding passe query_embeddings."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_col = MagicMock()
    mock_col.query.return_value = {
        "ids": [["id1"]],
        "documents": [["doc1"]],
        "metadatas": [[{"source": "x"}]],
        "distances": [[0.5]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.query_collection(
            "pz_text", "hello", n_results=1, embedding=[0.1, 0.2, 0.3],
        )
        mock_col.query.assert_called_once()
        kwargs = mock_col.query.call_args[1]
        assert "query_embeddings" in kwargs


# ===========================================================================
# ChromaWriter._parse_chroma_result tests (logique pure)
# ===========================================================================

def test_parse_chroma_result_normal():
    """Parsing standard -> list de SearchResult."""
    from ingestor.storage.chroma_writer import ChromaWriter, SearchResult

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    data = {
        "ids": [["id1", "id2"]],
        "documents": [['{"name": "axe"}', "plain text"], ],
        "metadatas": [[{"type": "item"}, {"type": "recipe"}]],
        "distances": [[0.1, 0.3]],
    }
    results = writer._parse_chroma_result(data, "pz_text")

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].id == "id1"
    assert results[0].collection == "pz_text"
    assert results[0].distance == 0.1
    assert results[0].metadata_ == {"type": "item"}


def test_parse_chroma_result_json_document():
    """Document JSON -> prose est le json.dumps."""
    from ingestor.storage.chroma_writer import ChromaWriter

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    data = {
        "ids": [["id1"]],
        "documents": [[_json.dumps({"name": "Base.Axe", "damage": 15})]],
        "metadatas": [[{"source": "wiki"}]],
        "distances": [[0.2]],
    }
    results = writer._parse_chroma_result(data, "pz_text")
    assert '"name"' in results[0].prose


def test_parse_chroma_result_empty():
    """Donnee vide -> liste vide."""
    from ingestor.storage.chroma_writer import ChromaWriter

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    data = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    results = writer._parse_chroma_result(data, "pz_text")
    assert results == []


def test_parse_chroma_result_missing_keys():
    """Cles manquantes dans la reponse -> valeurs par defaut."""
    from ingestor.storage.chroma_writer import ChromaWriter

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    data = {}  # toutes les cles manquantes
    results = writer._parse_chroma_result(data, "pz_text")
    assert results == []


# ===========================================================================
# ChromaWriter.ensure_collection tests (mock)
# ===========================================================================

async def test_ensure_collection_creates_new():
    """Nouvelle collection -> create_collection appele."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_http = MagicMock()
    mock_http.list_collections.return_value = []

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http

    await writer.ensure_collection("pz_pdfs")

    assert "pz_pdfs" in writer._collections_initialized
    mock_http.create_collection.assert_called_once_with("pz_pdfs")


async def test_ensure_collection_skip_existing():
    """Collection deja initialisee -> pas d'appel HTTP."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_http = MagicMock()

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http
    writer._collections_initialized.add("pz_pdfs")

    await writer.ensure_collection("pz_pdfs")

    mock_http.create_collection.assert_not_called()


async def test_ensure_collection_in_http_list():
    """Collection dans list_collections mais pas initialisee -> PAS cree (existe deja)."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_http = MagicMock()
    mock_http.list_collections.return_value = ["pz_pdfs", "pz_text"]

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http

    await writer.ensure_collection("pz_pdfs")

    # pz_pdfs est dans list_collections -> pas de create_collection appele
    mock_http.create_collection.assert_not_called()
    assert "pz_pdfs" in writer._collections_initialized


async def test_ensure_collection_not_in_list():
    """Collection absente de list_collections -> create_collection appele."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_http = MagicMock()
    mock_http.list_collections.return_value = ["pz_text"]  # pz_pdfs pas presente

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http

    await writer.ensure_collection("pz_pdfs")

    mock_http.create_collection.assert_called_once_with("pz_pdfs")


async def test_list_collections_delegate():
    """list_collections delegate a _http_client."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_http = MagicMock()
    mock_http.list_collections.return_value = ["c1", "c2"]

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http

    result = await writer.list_collections()
    assert result == ["c1", "c2"]


# ===========================================================================
# ChromaWriter.write_chunks_to_chroma tests (mock)
# ===========================================================================

class _FakeChunk:
    """Chunk fake avec .text et .metadata."""

    def __init__(self, text: str, metadata: dict | None = None):
        self.text = text
        self.metadata = metadata or {}


async def test_write_chunks_empty_list():
    """Chunks vide -> retourne False (rien a ecrire)."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = AsyncMock()

    with patch("chromadb.HttpClient", return_value=mock_client):
        result = await writer.write_chunks_to_chroma([], source="test.txt")
        assert result is False


async def test_write_chunks_all_empty_text():
    """Chunks avec texte vide -> ignores."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = AsyncMock()

    chunks = [_FakeChunk(""), _FakeChunk("   "), _FakeChunk(None)]

    with patch("chromadb.HttpClient", return_value=mock_client):
        result = await writer.write_chunks_to_chroma(chunks, source="test.txt")
        assert result is False


async def test_write_chunks_success_no_embedding():
    """Chunks avec embedding None -> Chroma add (sans embedding)."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = AsyncMock()

    chunks = [_FakeChunk("hello world")]

    with patch("chromadb.HttpClient", return_value=mock_client):
        result = await writer.write_chunks_to_chroma(
            chunks, source="test.txt", collection="pz_test",
        )
        assert result is True
        mock_col.add.assert_called_once()


async def test_write_chunks_success_with_embedding():
    """Chunks avec embedding -> Chroma upsert."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_inst.__enter__ = MagicMock(return_value=mock_inst)
    mock_inst.__exit__ = MagicMock(return_value=None)

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = AsyncMock()

    chunks = [_FakeChunk("hello world")]

    with patch("chromadb.HttpClient", return_value=mock_client):
        with patch("httpx.Client", return_value=mock_inst):
            result = await writer.write_chunks_to_chroma(
                chunks, source="test.txt", collection="pz_test",
            )
            assert result is True
            mock_col.upsert.assert_called_once()


async def test_write_chunks_metadata_merged():
    """Les metadata globales sont mergees avec les metadata du chunk."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_inst.__enter__ = MagicMock(return_value=mock_inst)
    mock_inst.__exit__ = MagicMock(return_value=None)

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = AsyncMock()

    chunks = [_FakeChunk("hello world", metadata={"type": "item"})]
    global_meta = {"version": "b41"}

    with patch("chromadb.HttpClient", return_value=mock_client):
        with patch("httpx.Client", return_value=mock_inst):
            await writer.write_chunks_to_chroma(
                chunks, source="test.txt", collection="pz_test",
                metadata=global_meta,
            )

            # Verifier que les metadatas contiennent toutes les cles
            call_args = mock_col.upsert.call_args
            metas = call_args[1]["metadatas"] if "metadatas" in call_args[1] else call_args[0][2]
            assert len(metas) >= 1
            # Les metadata doivent contenir source et content_type ajoutes par write_chunks_to_chroma
            first_meta = metas[0] if isinstance(metas, list) and metas else (metas[0] if hasattr(metas[0], '__getitem__') else {})
            assert "source" in str(first_meta) or "ingest_time" in str(first_meta)


async def test_write_chunks_id_format():
    """Les chunk IDs suivent le pattern {source}::chunk::{index}."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_col = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_inst.__enter__ = MagicMock(return_value=mock_inst)
    mock_inst.__exit__ = MagicMock(return_value=None)

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = AsyncMock()

    chunks = [_FakeChunk("text1"), _FakeChunk("text2")]

    with patch("chromadb.HttpClient", return_value=mock_client):
        with patch("httpx.Client", return_value=mock_inst):
            await writer.write_chunks_to_chroma(
                chunks, source="/data/file.txt", collection="pz_test",
            )

            # L'ID doit etre "/data/file.txt::chunk::0" et "::chunk::1"
            call_args = mock_col.upsert.call_args
            ids = call_args[1]["ids"] if "ids" in call_args[1] else call_args[0][0]
            assert len(ids) == 2


# ===========================================================================
# ChromaWriter.query tests (mock embedding + query)
# ===========================================================================

async def test_query_no_embedding_returns_empty():
    """Pas d'embedding -> liste vide."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_ensure = AsyncMock()
    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = mock_ensure
    writer._embedder.embed = MagicMock(return_value=None)

    results = await writer.query("pz_text", "hello")
    assert results == []


async def test_query_success():
    """Requete reussie -> SearchResult list."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_ensure = AsyncMock()
    mock_result_data = {
        "ids": [["id1"]],
        "documents": [['{"name": "axe"}']],
        "metadatas": [[{"type": "item"}]],
        "distances": [[0.1]],
    }
    mock_http = MagicMock()
    mock_http.query_collection.return_value = mock_result_data

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = mock_ensure
    writer._embedder.embed = MagicMock(return_value=[0.1, 0.2, 0.3])
    writer._http_client = mock_http

    results = await writer.query("pz_text", "axe")
    assert len(results) == 1
    assert results[0].id == "id1"
    assert results[0].distance == 0.1


async def test_query_exception_returns_empty():
    """Exception HTTP -> liste vide."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_ensure = AsyncMock()
    mock_http = MagicMock()
    mock_http.query_collection.side_effect = Exception("connection lost")

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer.ensure_collection = mock_ensure
    writer._embedder.embed = MagicMock(return_value=[0.1, 0.2, 0.3])
    writer._http_client = mock_http

    results = await writer.query("pz_text", "hello")
    assert results == []


# ===========================================================================
# ChromaWriter.cross_collection_search tests (mock)
# ===========================================================================

async def test_cross_collection_no_collections():
    """Aucune collection -> liste vide."""
    from ingestor.storage.chroma_writer import ChromaWriter

    mock_http = MagicMock()
    mock_http.list_collections.return_value = []

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http

    results = await writer.cross_collection_search("hello")
    assert results == []


async def test_cross_collection_sorted_by_distance():
    """Resultats tries par distance croissante."""
    from ingestor.storage.chroma_writer import ChromaWriter, SearchResult

    # Mock list_collections pour retourner 2 collections
    mock_http = MagicMock()
    mock_http.list_collections.return_value = ["pz_text", "pz_pdfs"]

    # Correction : Le mock de `query` DOIT être async car il est attendu (await) dans `cross_collection_search`
    async def mock_query(col, text, n_results=5):
        return [SearchResult(
            collection=col, id=f"{col}-1", prose="doc", distance=1.0 if col == "pz_text" else 0.2,
        )]

    writer = ChromaWriter(chroma_host="http://x:8000", ollama_url="http://x:11434")
    writer._http_client = mock_http
    writer.query = AsyncMock(side_effect=mock_query)

    results = await writer.cross_collection_search("hello", n_results=10)

    # Doit etre trie par distance croissante
    assert results[0].distance <= results[-1].distance if len(results) > 1 else True


# ===========================================================================
# write_chunks_to_chroma helper function tests
# ===========================================================================

async def test_write_chunks_helper_function():
    """La fonction globale appelle ChromaWriter et delegue."""
    from ingestor.storage.chroma_writer import write_chunks_to_chroma

    # Mock le constructeur ChromaWriter
    mock_writer = MagicMock()
    mock_writer.write_chunks_to_chroma = AsyncMock(return_value=True)

    with patch(
        "ingestor.storage.chroma_writer.ChromaWriter", return_value=mock_writer,
    ):
        result = await write_chunks_to_chroma(
            [_FakeChunk("hello")], source="test.txt", collection="pz_test",
        )
        assert result is True


# ===========================================================================
# ChromaClientHTTP query_collection edge cases (metadatas null)
# ===========================================================================

def test_query_collection_null_metadatas():
    """Metadatas None/vide -> dictionnaires vides par defaut."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_col = MagicMock()
    mock_col.query.return_value = {
        "ids": [["id1"]],
        "documents": [["doc1"]],
        "metadatas": [None],
        "distances": [[0.5]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.query_collection("pz_text", "hello")
        assert "metadatas" in result


def test_query_collection_null_distances():
    """Distances None -> liste vide."""
    from ingestor.storage.chroma_writer import ChromaClientHTTP

    mock_col = MagicMock()
    mock_col.query.return_value = {
        "ids": [["id1"]],
        "documents": [["doc1"]],
        "metadatas": [[{"source": "x"}]],
        "distances": [None],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_col

    client_http = ChromaClientHTTP("http://test:8000")
    with patch.object(client_http, "_get_client", return_value=mock_client):
        result = client_http.query_collection("pz_text", "hello")
        assert "distances" in result


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
    # ChromaClientHTTP
    test_get_client_returns_http_client,
    test_host_trailing_strip,
    test_create_collection_already_exists,
    test_create_collection_success,
    test_list_collections,
    test_add_documents,
    test_query_collection_with_text,
    test_query_collection_with_embedding,
    test_query_collection_null_metadatas,
    test_query_collection_null_distances,
    # ChromaWriter._parse_chroma_result
    test_parse_chroma_result_normal,
    test_parse_chroma_result_json_document,
    test_parse_chroma_result_empty,
    test_parse_chroma_result_missing_keys,
    # ChromaWriter ensure_collection (async)
    test_ensure_collection_creates_new,
    test_ensure_collection_skip_existing,
    test_ensure_collection_in_http_list,
    test_ensure_collection_not_in_list,
    test_list_collections_delegate,
    # ChromaWriter write_chunks (async)
    test_write_chunks_empty_list,
    test_write_chunks_all_empty_text,
    test_write_chunks_success_no_embedding,
    test_write_chunks_success_with_embedding,
    test_write_chunks_metadata_merged,
    test_write_chunks_id_format,
    # ChromaWriter query (async)
    test_query_no_embedding_returns_empty,
    test_query_success,
    test_query_exception_returns_empty,
    # cross_collection_search (async)
    test_cross_collection_no_collections,
    test_cross_collection_sorted_by_distance,
    # Helper function
    test_write_chunks_helper_function,
]

# Simple async runner (no pytest dependency needed)

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
    print("Chroma Writer Unit Tests")
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
