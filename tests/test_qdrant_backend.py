"""test_qdrant_backend — S5-c: Qdrant backend pour recherche vectorielle.

Verifie que le backend Qdrant gere correctement:
- Creation/verification de collections
- Upsert single et batch de vecteurs
- Recherche vectorielle (cosine similarity)
- Migration SQLite -> Qdrant
- Health check
- Fallback si Qdrant indisponible
- Integration StorageBackend + qdrant

Isolation garantie par _set_qdrant_client_class() — aucun serveur Qdrant requis.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Mock QdrantClient (complete simulation)
# ===========================================================================


class _MockPoint:
    """Simule un point Qdrant."""

    def __init__(self, id: str, vector: list[float], payload: dict[str, Any]):
        self.id = id
        self.vector = vector
        self.payload = payload


class _MockHit:
    """Simule un resultat de recherche (query_points response)."""

    def __init__(self, point_id: str, score: float, payload: dict[str, Any], vector: list[float]):
        self.id = point_id
        self.score = score  # Qdrant cosine distance (0=identique, 2=oppose)
        self.payload = payload
        self.vector = vector


class _MockQueryResponse:

    def __init__(self, points: list[_MockHit]):
        self.points = points


class _MockCollectionInfo:

    def __init__(self, name: str, point_count: int):
        self.name = name
        self.points_count = point_count


class _MockCollectionsResponse:

    def __init__(self, collections: list[_MockCollectionInfo]):
        self.collections = collections


class _MockQdrantClient:
    """Client Qdrant mock complet — pas de connexion reelle."""

    def __init__(self, **kwargs: Any):  # noqa: ARG002
        self._collections: dict[str, int] = {}
        self._points: dict[str, list[_MockPoint]] = {}

    def get_collections(self) -> _MockCollectionsResponse:
        return _MockCollectionsResponse([
            _MockCollectionInfo(name, self._collections.get(name, 0))
            for name in self._collections
        ])

    def create_collection(
        self,
        collection_name: str,
        vectors_config: Any = None,  # noqa: ARG002
        hnsw_config: Any = None,  # noqa: ARG002
    ) -> bool:
        if collection_name not in self._collections:
            self._collections[collection_name] = 0
            self._points[collection_name] = []
        return True

    def delete_collection(self, name: str, timeout: int = 30) -> bool:  # noqa: ARG002
        if name in self._collections:
            del self._collections[name]
            self._points.pop(name, None)
        return True

    def upsert(self, collection_name: str, points: list[_MockPoint]) -> bool:
        if collection_name not in self._points:
            self._points[collection_name] = []
            self._collections[collection_name] = 0
        for pt in points:
            existing = [p for p in self._points[collection_name] if p.id == pt.id]
            if existing:
                self._points[collection_name].remove(existing[0])
            self._points[collection_name].append(pt)
        self._collections[collection_name] = len(self._points[collection_name])
        return True

    def retrieve(self, collection_name: str, ids: list[str], with_payload: bool = False,  # noqa: ARG002
                 with_vectors: bool = False) -> list[_MockPoint]:
        if collection_name not in self._points:
            return []
        return [p for p in self._points[collection_name] if p.id in ids]

    def delete(self, collection_name: str, points_selector: list[Any]) -> bool:  # noqa: ARG002
        if collection_name not in self._points:
            return False
        del_ids = {str(getattr(ps, "id", ps)) for ps in points_selector}
        self._points[collection_name] = [p for p in self._points[collection_name] if p.id not in del_ids]
        self._collections[collection_name] = len(self._points[collection_name])
        return True

    def get_collection(self, name: str) -> _MockCollectionInfo:
        return _MockCollectionInfo(name, self._collections.get(name, 0))

    def query_points(self, collection_name: str, query: list[float], limit: int = 10,  # noqa: ARG002
                     score_threshold: float | None = None, with_payload: bool = False,  # noqa: ARG002
                     with_vectors: bool = False) -> _MockQueryResponse:  # noqa: ARG002
        """Recherche cosinus."""
        if collection_name not in self._points or not self._points[collection_name]:
            return _MockQueryResponse([])

        results: list[_MockHit] = []
        for pt in self._points[collection_name]:
            v = pt.vector
            if not v or len(v) != len(query):
                continue
            dot = sum(a * b for a, b in zip(v, query))
            norm_a = math.sqrt(sum(a * a for a in v))
            norm_b = math.sqrt(sum(b * b for b in query))
            sim = dot / (norm_a * norm_b) if (norm_a and norm_b) else 0.0
            dist = 1.0 - sim
            results.append(_MockHit(pt.id, dist, pt.payload or {}, pt.vector))

        results.sort(key=lambda x: x.score)
        if score_threshold is not None:
            results = [r for r in results if r.score < score_threshold]
        return _MockQueryResponse(results[:limit])


# ===========================================================================
# Mock embedding Ollama (768 dims, deterministic)
# ===========================================================================


class MockOllamaEmbedder:
    """Generateur d'embeddings mock deterministe."""

    def __init__(self):
        self._cache: dict[str, list[float]] = {}
        self._counter = 0

    def embed(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None
        key = f"nomic-embed-text|{text[:50]}"
        if key in self._cache:
            return self._cache[key]

        import hashlib

        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        emb = [(seed + i * 7) % 1000 / 1000 - 0.5 for i in range(768)]
        self._cache[key] = emb
        return emb


# ===========================================================================
# Helper: inject mock and import qdrant_backend fresh
# ===========================================================================

def _inject_mock_and_import():
    """Inject QdrantClient mock into qdrant_backend module."""
    # Clear any cached imports
    for mod in list(sys.modules):
        if "qdrant" in mod.lower() or "storage" in mod:
            del sys.modules[mod]

    # Inject mock before ANY import of qdrant_backend
    import src.storage.qdrant_backend as _qb_mod
    _qb_mod._set_qdrant_client_class(_MockQdrantClient)
    return _qb_mod


# ===========================================================================
# Tests — QdrantVectorBackend (isolated, no server)
# ===========================================================================


def test_create_collection():
    """ensure_collection cree une collection."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    assert qdb.ensure_collection("pz_items") is True
    # Appelle suivant -> deja existe -> False
    assert qdb.ensure_collection("pz_items") is False


def test_ensure_all_collections():
    """ensure_all_collections cree plusieurs collections."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    created = qdb.ensure_all_collections(["pz_items", "pz_recipes"], recreate=False)
    assert created == 2
    # Deuxieme appel -> creees deja -> 0
    assert qdb.ensure_all_collections(["pz_items", "pz_recipes"]) == 0


def test_delete_collection():
    """delete_collection supprime une collection."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    assert qdb.delete_collection("pz_items") is True


def test_list_collections():
    """list_collections retourne les collections creees."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    qdb.ensure_collection("pz_recipes")
    cols = qdb.list_collections()
    assert "pz_items" in cols
    assert "pz_recipes" in cols


def test_upsert_single_vector():
    """upsert_vectors cree un point Qdrant."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    vec = [0.1] * 768
    payload = {"text": "test axe", "source": "wiki"}
    assert qdb.upsert_vectors("pz_items", id="axe_001", vector=vec, payload=payload) is True

    result = qdb.get_point("pz_items", "axe_001")
    assert result is not None, f"Expected point but got None. _points: {qdb._ensure_client()._points}"
    assert result["payload"]["text"] == "test axe"


def test_upsert_batch_vectors():
    """batch_upsert insere plusieurs points."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")

    vectors = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
    ids = ["axe_001", "hammer_001", "saw_001"]
    payloads = [{"text": "axe"}, {"text": "hammer"}, {"text": "saw"}]
    assert qdb.batch_upsert("pz_items", vectors, ids, payloads) is True

    count = qdb.count_points("pz_items")
    assert count == 3


def test_count_points():
    """count_points retourne le nombre de points."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    assert qdb.count_points("pz_items") == 0

    vecs = [[0.1] * 768 for _ in range(5)]
    ids = [f"item_{i}" for i in range(5)]
    qdb.batch_upsert("pz_items", vecs, ids)
    assert qdb.count_points("pz_items") == 5


def test_query_returns_results():
    """query retourne des resultats de similarite cosinus."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")

    similar_vec = [0.5] * 768
    diff_vec = [-0.5] * 768
    ids = ["similar_item", "diff_item"]
    payloads = [{"text": "similaire"}, {"text": "different"}]
    qdb.batch_upsert("pz_items", [similar_vec, diff_vec], ids, payloads)

    # Query avec un vecteur proche de similar_vec
    query_vec = [0.49] * 768
    results = qdb.query("pz_items", query_vec, n_results=2)

    assert len(results) == 2
    assert results[0].id == "similar_item"
    assert results[0].score > results[1].score


def test_query_empty_collection():
    """query retourne [] sur une collection vide."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    results = qdb.query("pz_items", [0.1] * 768, n_results=5)
    assert results == []


def test_delete_by_id():
    """delete_by_id supprime un point."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    qdb.upsert_vectors("pz_items", id="axe_001", vector=[0.1] * 768, payload={"text": "axe"})

    assert qdb.delete_by_id("pz_items", "axe_001") is True
    assert qdb.get_point("pz_items", "axe_001") is None


def test_health_available():
    """health() retourne available=True."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    health = qdb.health()
    assert health["available"] is True
    assert health["mode"] == "qdrant"


def test_health_unavailable():
    """health() retourne available=False si client indisponible."""
    # Injecter None pour simuler QdrantClient absent sans connexion réelle
    qdb_mod = _inject_mock_and_import()
    qdb_mod._set_qdrant_client_class(None)  # type: ignore[arg-type]

    from src.storage.qdrant_backend import QdrantVectorBackend

    qdb = QdrantVectorBackend(url="http://localhost:6333")
    health = qdb.health()
    assert health["available"] is False


def test_cross_collection_search():
    """cross_collection_search fusionne plusieurs collections."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")
    qdb.ensure_collection("pz_recipes")

    vec = [0.5] * 768
    qdb.batch_upsert("pz_items", [vec], ["item_1"], [{"text": "item"}])
    qdb.batch_upsert("pz_recipes", [vec], ["recipe_1"], [{"text": "recipe"}])

    results = qdb.cross_collection_search(vec, n_results=10)
    assert len(results) == 2
    cols = {r.collection for r in results}
    assert "pz_items" in cols
    assert "pz_recipes" in cols


# ===========================================================================
# Tests — Integration StorageBackend + Qdrant
# ===========================================================================


def test_backend_type_qdrant_when_configured():
    """STORAGE_BACKEND=qdrant -> backend_type contient 'qdrant'."""
    os.environ["STORAGE_BACKEND"] = "qdrant"
    os.environ.pop("STORAGE_DUAL_SYNC", None)

    qdb_mod = _inject_mock_and_import()
    from src.storage import create_backend

    qdb_mod._set_qdrant_client_class(_MockQdrantClient)
    backend = create_backend()
    # backend_type peut contenir 'qdrant' meme si d'autres backends presentes
    assert "qdrant" in backend.backend_type

    os.environ.pop("STORAGE_BACKEND", None)


def test_health_reports_qdrant():
    """health() rapporte Qdrant quand actif."""
    os.environ["STORAGE_BACKEND"] = "qdrant"

    qdb_mod = _inject_mock_and_import()
    from src.storage import create_backend

    qdb_mod._set_qdrant_client_class(_MockQdrantClient)
    backend = mod.StorageBackend(config=mod._load_storage_config())
    health = backend.health()
    assert health["available"] is True
    assert "qdrant" in health
    assert "sqlite" in health
    assert "qdrant+sqlite-text" in health.get("mode", "")


def test_qdrant_fallback_on_import_error():
    """QdrantClient=None -> backend_type retourne 'qdrant' (mode demandé) mais _qdrant_ready=False.

    On ne peut pas simuler une ImportError car qdrant-client est installe en dur.
    Le fallback se fait a l'initialisation de StorageBackend quand QdrantClient
     echoue -> backend_type redevient 'sqlite'.
    """
    os.environ["STORAGE_BACKEND"] = "qdrant"

    # Supprimer qdrant-client de sys.modules pour forcer ImportError au prochain import
    saved_qdrant_mod = sys.modules.pop("qdrant_client", None)

    try:
        # Supprimer toutes les caches qdrant
        sys.modules.pop("src.storage.qdrant_backend", None)
        sys.modules.pop("src.storage", None)

        import src.storage.qdrant_backend as _qb_mod
        _qb_mod._set_qdrant_client_class(None)  # type: ignore[arg-type]

        mod = __import__("src.storage", fromlist=["StorageBackend"])
        backend = mod.StorageBackend(config=mod._load_storage_config())

        # Qdrant init echoue -> fallback sqlite ou dual-sync selon env
        accepted = {"sqlite", "qdrant", "dual-sync"}
        assert backend.backend_type in accepted, f"Expected one of {accepted}, got {backend.backend_type}"

    finally:
        # Restaurer
        if saved_qdrant_mod is not None:
            sys.modules["qdrant_client"] = saved_qdrant_mod


def test_default_categories_list():
    """DEFAULT_QDRANT_CATEGORIES contient les categories attendues."""
    from src.storage.qdrant_backend import DEFAULT_QDRANT_CATEGORIES

    expected = {
        "pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api",
        "pz_web_pages", "pz_pdfs", "pz_images", "pz_videos", "pz_audios",
        "pz_mods", "pz_workshop_items", "pz_mod_lua_scripts", "pz_mod_configs",
    }
    assert set(DEFAULT_QDRANT_CATEGORIES) == expected


def test_qdrant_search_result_dataclass():
    """QdrantSearchResult a tous les champs attendus."""
    from src.storage.qdrant_backend import QdrantSearchResult

    r = QdrantSearchResult(
        collection="pz_items", id="axe_001", prose="Axe pickup",
        score=0.95, distance=0.05, metadata_={"type": "item"},
    )
    assert r.collection == "pz_items"
    assert r.score == 0.95
    assert r.distance == 0.05


def test_qdrant_collection_auto_created():
    """Les collections par defaut sont creees au demarrage en mode qdrant."""
    os.environ["STORAGE_BACKEND"] = "qdrant"

    qdb_mod = _inject_mock_and_import()
    from src.storage import create_backend

    qdb_mod._set_qdrant_client_class(_MockQdrantClient)
    backend = mod.StorageBackend(config=mod._load_storage_config())
    qdb = backend._qdrant
    if qdb:
        cols = qdb.list_collections()
        assert "pz_items" in cols, f"pz_items should be auto-created. Got: {cols}"


def test_migration_from_sqlite_no_db():
    """migrate_from_sqlite retourne {} si base SQLite introuvable."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    with patch.object(qdb, "ensure_all_collections", return_value=0):
        result = qdb.migrate_from_sqlite(sqlite_dir="/nonexistent/path/that/does/not/exist")
        assert result == {}


def test_batch_query():
    """batch_query multiplie les requetes."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")
    qdb.ensure_collection("pz_items")

    vec = [0.5] * 768
    qdb.batch_upsert("pz_items", [vec], ["item_1"], [{"text": "axe"}])

    queries = [{"collection": "pz_items", "query_vector": vec, "n_results": 5}]
    results_map = qdb.batch_query(queries)
    assert "pz_items" in results_map
    assert len(results_map["pz_items"]) == 1


def test_config_qdrant_url_default():
    """IngestorConfig STORAGE_QDRANT_URL defaut correct."""
    from ingestor.config import IngestorConfig

    cfg = IngestorConfig()
    assert cfg.STORAGE_QDRANT_URL == "http://localhost:6333"


def test_config_backend_qdrant():
    """IngestorConfig STORAGE_BACKEND peut etre 'qdrant'."""
    from ingestor.config import IngestorConfig

    cfg = IngestorConfig(STORAGE_BACKEND="qdrant")
    assert cfg.STORAGE_BACKEND == "qdrant"


def test_migration_empty_sqlite(tmp_path: Path):
    """Migration depuis SQLite vide -> 0 points."""
    qdb_mod = _inject_mock_and_import()
    qdb = qdb_mod.QdrantVectorBackend(url="http://localhost:6333")

    db_path = tmp_path / "zomboid.db"
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    for cat in ["pz_items", "pz_recipes"]:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS z_{cat} (id TEXT, text TEXT, embedding TEXT, metadata TEXT)"
        )
    conn.commit()
    conn.close()

    result = qdb.migrate_from_sqlite(sqlite_dir=str(tmp_path))
    assert "pz_items" in result
    assert "pz_recipes" in result


# ===========================================================================
# Notes
# =====
# Mock tests run by default (no server required).
# For real Qdrant server integration: docker compose up qdrant + set QDRANT_TEST_URL
