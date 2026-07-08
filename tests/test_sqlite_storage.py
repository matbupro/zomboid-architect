"""Tests unitaires pour src/storage/sqlite_storage (SQLite + Ollama embedding).

Couverture :
- CRUD chunks (write, read, delete)
- Collections (create, list, count, delete)
- Cosine similarity (calcul pur Python)
- Metadata filtering ($and, $eq, version)
- get_by_id deterministe
- cross_collection_search
- StorageBackend avec fallback local
- OllamaEmbedder (mocké)

Lancer : pytest tests/test_sqlite_storage.py -v
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from src.storage.sqlite_storage import SQLiteStorage, SearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """ cree une base SQLite temporaire pour chaque test."""
    tmp = tempfile.mkdtemp()
    return SQLiteStorage(data_dir=tmp)


@pytest.fixture()
def sample_chunks():
    """Liste de chunks factices pour les tests."""
    class Chunk:
        def __init__(self, text, metadata=None):
            self.text = text
            self.metadata = metadata or {}

    return [
        Chunk("Base.Axe : hache en metal et bois, dommages 50", {"base_id": "Base.Axe", "item_type": "weapon", "version": "b41"}),
        Chunk("Base.Crowbar : pied de biche, dommage 38", {"base_id": "Base.Crowbar", "item_type": "weapon", "version": "b41"}),
        Chunk("Recipe.Hatchet : necessite Metal Sheet x2 + Wood x1", {"base_id": "Recipe.Hatchet", "item_type": "recipe", "version": "b42"}),
        Chunk("Panic Mechanic : les zombies entendent le bruit", {"item_type": "mechanic", "version": "b41"}),
        Chunk("Calories : 3500 kcal/jour en hiver, 2500 en ete", {"item_type": "mechanic", "version": "b42"}),
    ]


# ---------------------------------------------------------------------------
# Fixtures avec embeddings mocks (pour tests vectoriels)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_with_mock_embedder():
    """Base SQLite avec embedder mocké pour tests vectoriels."""
    tmp = tempfile.mkdtemp()
    from unittest.mock import MagicMock

    sqlite = SQLiteStorage(data_dir=tmp, ollama_url="http://localhost:11434")
    # Mock l'embedder
    sqlite._embedder = MagicMock()
    # Retourne un embedding unit vector de dimension 768 (nomic-embed-text)
    mock_emb_768 = [0.0] * 768

    def gen_id(text):
        """Genere un embedding deterministe basé sur le texte."""
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        return [float(int(h[i:i+8], 16) % 1000 - 500) / 1000.0 for i in range(0, len(h), 8)]

    sqlite._embedder.embed.side_effect = lambda text: gen_id(text) if text else None
    return sqlite


# ---------------------------------------------------------------------------
# Tests : Collections (CRUD)
# ---------------------------------------------------------------------------

class TestCollections:
    """Test de creation/liste/comptage/suppression des collections."""

    def test_ensure_collection_creates_table(self, db):
        assert db.ensure_collection("pz_items") is True  # creee
        assert db.ensure_collection("pz_items") is False  # deja existante

    def test_list_collections_empty(self, db):
        assert db.list_collections() == []

    def test_list_collections_after_create(self, db):
        db.ensure_collection("pz_items")
        db.ensure_collection("pz_recipes")
        assert sorted(db.list_collections()) == ["pz_items", "pz_recipes"]

    def test_count_collection(self, db):
        db.ensure_collection("pz_items")
        # Pas de chunks
        assert db.count_collection("pz_items") == 0

    def test_delete_collection(self, db):
        db.ensure_collection("pz_items")
        db.delete_collection("pz_items")
        assert "pz_items" not in db.list_collections()


# ---------------------------------------------------------------------------
# Tests : Ecriture de chunks
# ---------------------------------------------------------------------------

class TestWriteChunks:
    """Test d'insertion de chunks avec metadata."""

    def test_write_single_chunk(self, db):
        chunk = type("Chunk", (), {"text": "Test text", "metadata": {"base_id": "Test"}})()
        result = db.write_chunk(
            collection="pz_items",
            chunk_id="test::1",
            text=chunk.text,
            metadata=chunk.metadata,
            source="test",
        )
        assert result is True
        assert db.count_collection("pz_items") == 1

    def test_write_chunks_batch(self, db, sample_chunks):
        written = db.write_chunks(sample_chunks, collection="pz_items", source="test_ingest.py")
        assert written == len(sample_chunks)
        assert db.count_collection("pz_items") == len(sample_chunks)

    def test_empty_text_skipped(self, db):
        class Chunk:
            text = ""
            metadata = {}
        written = db.write_chunks([Chunk()], collection="pz_items", source="test")
        assert written == 0

    def test_upsert_behavior(self, db):
        """Ecrire le meme chunk_id deux fois → update, pas duplicate."""
        db.write_chunk("pz_items", "u::1", "version 1", {"ver": 1}, source="upsert_test")
        db.write_chunk("pz_items", "u::1", "version 2", {"ver": 2}, source="upsert_test")
        assert db.count_collection("pz_items") == 1

    def test_metadata_stored_as_json(self, db):
        meta = {"base_id": "Base.Axe", "item_type": "weapon", "count": 42}
        db.write_chunk("pz_items", "m::1", "test", meta)
        with db._conn() as conn:
            row = conn.execute("SELECT metadata FROM z_pz_items").fetchone()
            parsed = json.loads(row["metadata"])
            assert parsed["base_id"] == "Base.Axe"
            assert parsed["item_type"] == "weapon"
            assert parsed["count"] == 42


# ---------------------------------------------------------------------------
# Tests : Cosine similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    """Test du calcul de similarité cosinus."""

    def test_identical_vectors(self, db):
        v = [1.0, 0.0, 0.0]
        assert db._cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self, db):
        assert db._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self, db):
        assert db._cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_diagonal_vectors(self, db):
        sim = db._cosine_similarity([3.0, 4.0], [6.0, 8.0])
        assert abs(sim - 1.0) < 1e-10  # meme direction

    def test_cosine_distance(self, db):
        v = [1.0, 0.0]
        assert db.cosine_distance(v, v) == pytest.approx(0.0)
        assert db.cosine_distance(v, [-1.0, 0.0]) == pytest.approx(2.0)

    def test_different_dimensions(self, db):
        assert db._cosine_similarity([1.0], [1.0, 2.0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests : Recherche vectorielle
# ---------------------------------------------------------------------------

class TestVectorSearch:
    """Test de la recherche vectorielle avec embeddings mocks."""

    def test_search_returns_results(self, db_with_mock_embedder):
        chunks = [
            type("Chunk", (), {"text": "Base.Axe : hache metal bois", "metadata": {"base_id": "Base.Axe"}})(),
            type("Chunk", (), {"text": "Recipe.Hatchet : craft recipe", "metadata": {"base_id": "Recipe.Hatchet"}})(),
        ]
        db_with_mock_embedder.write_chunks(chunks, collection="pz_items", source="test")

        results = db_with_mock_embedder.query("pz_items", "axe pickup", n_results=5)
        assert len(results) == 2

    def test_search_empty_collection(self, db_with_mock_embedder):
        results = db_with_mock_embedder.query("pz_items", "anything", n_results=5)

        assert results == []

    def test_search_respects_n_results(self, db_with_mock_embedder):
        chunks = [
            type("Chunk", (), {"text": f"Document {i}", "metadata": {"index": i}})()
            for i in range(10)
        ]
        db_with_mock_embedder.write_chunks(chunks, collection="pz_items", source="test")

        results = db_with_mock_embedder.query("pz_items", "document search", n_results=3)
        assert len(results) == 3

    def test_search_sorted_by_distance(self, db_with_mock_embedder):
        """Les resultats doivent etre classes par distance croissante."""
        chunks = [
            type("Chunk", (), {"text": "Similar text here", "metadata": {}})(),
            type("Chunk", (), {"text": "Dissimilar content far away", "metadata": {}})(),
        ]
        db_with_mock_embedder.write_chunks(chunks, collection="pz_items", source="test")

        results = db_with_mock_embedder.query("pz_items", "similar text query", n_results=5)
        assert results[0].distance <= results[1].distance

    def test_search_no_embedding_available(self):
        """Sans embedder (None) → retourne []."""
        import tempfile
        tmp = tempfile.mkdtemp()
        db = SQLiteStorage(data_dir=tmp, ollama_url=None)  # pas d'embedder
        chunks = [type("Chunk", (), {"text": "Base.Axe", "metadata": {}})()]
        db.write_chunks(chunks, collection="pz_items", source="test")
        assert db.query("pz_items", "anything") == []


# ---------------------------------------------------------------------------
# Tests : Metadata filtering ($and, $eq, version)
# ---------------------------------------------------------------------------

class TestFiltering:
    """Test du filtrage metadata en recherche."""

    def test_filter_by_version(self, db_with_mock_embedder):
        chunks = [
            type("Chunk", (), {"text": "B41 axe weapon", "metadata": {"base_id": "Base.Axe", "version": "b41"}})(),
            type("Chunk", (), {"text": "B42 axe weapon", "metadata": {"base_id": "Base.Axe", "version": "b42"}})(),
        ]
        db_with_mock_embedder.write_chunks(chunks, collection="pz_items", source="test")

        results = db_with_mock_embedder.query(
            "pz_items", "axe", n_results=5, filters={"$and": [{"version": {"$eq": "b41"}}]},
        )
        assert len(results) == 1
        assert results[0].metadata_["version"] == "b41"

    def test_filter_by_item_type(self, db_with_mock_embedder):
        chunks = [
            type("Chunk", (), {"text": "Weapon text", "metadata": {"item_type": "weapon"}})(),
            type("Chunk", (), {"text": "Recipe text", "metadata": {"item_type": "recipe"}})(),
        ]
        db_with_mock_embedder.write_chunks(chunks, collection="pz_items", source="test")

        results = db_with_mock_embedder.query(
            "pz_items", "search", n_results=5, filters={"$and": [{"item_type": {"$eq": "recipe"}}]},
        )
        assert len(results) == 1
        assert results[0].metadata_["item_type"] == "recipe"

    def test_no_filter_returns_all(self, db_with_mock_embedder):
        chunks = [
            type("Chunk", (), {"text": f"Doc {i}", "metadata": {"id": i}})()
            for i in range(3)
        ]
        db_with_mock_embedder.write_chunks(chunks, collection="pz_items", source="test")

        results = db_with_mock_embedder.query("pz_items", "search", n_results=10)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Tests : get_by_id (lookup deterministe)
# ---------------------------------------------------------------------------

class TestGetById:
    """Test de la recherche par ID deterministe."""

    def test_get_by_id_found(self, db):
        chunks = [
            type("Chunk", (), {"text": "Base.Axe description", "metadata": {"base_id": "Base.Axe"}})(),
        ]
        db.write_chunks(chunks, collection="pz_items", source="test")

        result = db.get_by_id("pz_items", "test::chunk::0")
        assert result is not None
        assert result.collection == "pz_items"
        assert result.distance == 0.0

    def test_get_by_id_not_found(self, db):
        result = db.get_by_id("pz_items", "nonexistent_id")
        assert result is None


# ---------------------------------------------------------------------------
# Tests : Cross-collection search
# ---------------------------------------------------------------------------

class TestCrossCollectionSearch:
    """Test de la recherche multi-collection."""

    def test_cross_collection_returns_fused(self, db_with_mock_embedder):
        chunks_items = [type("Chunk", (), {"text": "Weapon text", "metadata": {}})()]
        chunks_recipes = [type("Chunk", (), {"text": "Crafting text", "metadata": {}})()]

        db_with_mock_embedder.write_chunks(chunks_items, collection="pz_items", source="test")
        db_with_mock_embedder.ensure_collection("pz_recipes")
        # Ecrire directement (sans write_chunks pour pz_recipes)
        db_with_mock_embedder.write_chunk(
            "pz_recipes", "r::1", "Crafting text", {"base_id": "Recipe.Hatchet"}, source="test"
        )

        results = db_with_mock_embedder.cross_collection_search("search query", n_results=10)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Tests : StorageBackend (StorageBackend uniquement)
# ---------------------------------------------------------------------------

class TestStorageBackend:
    """Test du backend unifie avec fallback."""

    def test_backend_health(self):
        backend = type("SQLiteStorage", (), {})()
        from src.storage.sqlite_storage import StorageBackend

        tmp = tempfile.mkdtemp()
        backend = StorageBackend(data_dir=tmp)  # SQLite local
        health = backend.health()
        # Le mode peut etre "sqlite", "qdrant+sqlite-text" ou "dual-sync" selon l'environnement
        assert health["available"] is True
        assert "sqlite" in health

    def test_backend_sqlite_always_available(self):
        from src.storage.sqlite_storage import StorageBackend

        tmp = tempfile.mkdtemp()
        backend = StorageBackend(data_dir=tmp)
        backend.ensure_collection("test_col")
        assert backend.count_collection("test_col") == 0


# ---------------------------------------------------------------------------
# Tests : OllamaEmbedder (mocké)
# ---------------------------------------------------------------------------

class TestOllamaEmbedder:
    """Test du generateur d'embeddings."""

    def test_embed_empty_string(self):
        from src.storage.sqlite_storage import OllamaEmbedder

        e = OllamaEmbedder()
        assert e.embed("") is None
        assert e.embed("  ") is None

    def test_cache_reuse(self):
        from unittest.mock import MagicMock, patch

        from src.storage.sqlite_storage import OllamaEmbedder

        mock_resp = {"embeddings": [[0.1] * 768]}
        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_resp
            mock_response.raise_for_status = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post = MagicMock(return_value=mock_response)
            MockClient.return_value = mock_client

            embedder = OllamaEmbedder()
            e1 = embedder.embed("hello")
            e2 = embedder.embed("hello")  # doit etre cache

            assert e1 is not None
            assert e2 is e1  # meme objet (cache)
            assert mock_client.post.call_count == 1  # appele une seule fois


# ---------------------------------------------------------------------------
# Tests : Edge cases & robustesse
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test de cas limites et robustesse."""

    def test_write_chunk_unicode(self, db):
        chunks = [type("Chunk", (), {"text": "Café zombie français!", "metadata": {"lang": "fra"}})()]
        written = db.write_chunks(chunks, collection="pz_items", source="test")
        assert written == 1

    def test_delete_by_id(self, db):
        db.write_chunk("pz_items", "d::1", "text", {})
        assert db.delete_by_id("pz_items", "d::1") is True
        assert db.count_collection("pz_items") == 0
        assert db.delete_by_id("pz_items", "nonexistent") is False

    def test_empty_where_clause(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        db = SQLiteStorage(data_dir=tmp)
        where, params = db._build_sql_where({}, None, {})
        assert where is None or len(where) == 0

    def test_game_version_where_clause(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        db = SQLiteStorage(data_dir=tmp)
        where, params = db._build_sql_where({}, "b41", None)
        assert where is not None
        assert params[0] == "b41"  # game_version passe dans params

    def test_metadata_json_escape(self, db):
        """Metadata avec quotes simples ne doit pas casser SQL."""
        meta = {"name": "O'Brien's Axe"}
        db.write_chunk("pz_items", "e::1", "test", meta)
        assert db.count_collection("pz_items") == 1
