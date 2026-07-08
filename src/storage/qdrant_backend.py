"""src/storage/qdrant_backend — Backend Qdrant pour recherche vectorielle.

Backend Qdrant distant pour recherche vectorielle d'embeddings (docker-compose.pz-agent.yml).

Schema Qdrant (collection per category) :
  collection_name = <pz_items, pz_recipes, ...>
  point id        = chunk_id hash
  vector          = embedding (float32, 768 dims for nomic-embed-text)
  payload         = { text, metadata, source, ingest_time }

Usage :
    from src.storage.qdrant_backend import QdrantVectorBackend
    qdb = QdrantVectorBackend(url="http://localhost:6333")
    qdb.init_collections(["pz_items", "pz_recipes"])
    qdb.upsert_vectors("pz_items", id="abc123", vector=[...], payload={...})
    results = qdb.query("axe pickup", collection="pz_items", n=5)

Backend selection via env :
  STORAGE_BACKEND=qdrant  → Qdrant distant (vecteurs d'embedding)

Created on 2026-07-07 — S5-c: Backend Qdrant vectoriel.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)

# Module-level injection point for testing.
# Before importing qdrant_backend, set: qdrant_backend.QdrantClient = MockClass
_QdrantClient_cls: Any | None = None


def _get_qdrant_client_class() -> Any:
    """Return QdrantClient (injected mock or real)."""
    if _QdrantClient_cls is not None:
        return _QdrantClient_cls
    try:
        import qdrant_client  # noqa: F811

        return qdrant_client.QdrantClient
    except ImportError:
        return None


def _set_qdrant_client_class(mock_cls: Any) -> None:
    """Inject a mock QdrantClient class for testing.

    Call BEFORE any import of QdrantVectorBackend to take effect:
        import src.storage.qdrant_backend as qdb
        qdb._set_qdrant_client_class(MockQdrantClient)
    """
    global _QdrantClient_cls  # noqa: PLW0603
    _QdrantClient_cls = mock_cls


# ---------------------------------------------------------------------------
# Resultat unifie (identique a SearchResult PG)
# ---------------------------------------------------------------------------


@dataclass
class QdrantSearchResult:
    """Résultat d'une requête Qdrant — format unifié."""

    collection: str
    id: str
    prose: str
    score: float  # cosine similarity (1.0 = parfait match)
    distance: float = 0.0  # alias pour compatibilité SearchResult
    metadata_: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Collections Qdrant par défaut
# ---------------------------------------------------------------------------

DEFAULT_QDRANT_CATEGORIES: list[str] = [
    "pz_items",
    "pz_recipes",
    "pz_mechanics",
    "pz_lua_api",
    "pz_java_api",
    "pz_web_pages",
    "pz_pdfs",
    "pz_images",
    "pz_videos",
    "pz_audios",
    "pz_mods",
    "pz_workshop_items",
    "pz_mod_lua_scripts",
    "pz_mod_configs",
]


class QdrantVectorBackend:
    """Client Qdrant pour recherche vectorielle d'embeddings.

    Args:
        url: URL du serveur Qdrant (ex: http://localhost:6333).
        api_key: Clé API optionnelle pour Qdrant Cloud.
        vector_size: Taille des vecteurs (768 pour nomic-embed-text).
        distance: Distance de similarité (cosine par défaut).
    """

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        vector_size: int = 768,
        distance: str = "cosine",
    ):
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._vector_size = vector_size
        self._distance = distance
        self._client: Any | None = None
        self._collections_created: set[str] = set()

    def _ensure_client(self) -> Any:
        """Initialise le client Qdrant (lazy import + connexion)."""
        if self._client is not None:
            return self._client

        try:
            # Use module-level ref for test injection
            QC = _get_qdrant_client_class()
            if QC is None:
                raise ImportError("qdrant-client non installe")
            self._client = QC(url=self._url, api_key=self._api_key)  # type: ignore[arg-type]
        except ImportError:
            logger.error("qdrant-client non installe. pip install qdrant-client")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Connexion Qdrant echou (%s): %s", self._url, exc)
            return None

        return self._client

    # ------------------------------------------------------------------
    # Gestion des collections (une par catégorie PZ)
    # ------------------------------------------------------------------

    def ensure_collection(self, name: str, recreate: bool = False) -> bool:
        """Crée une collection Qdrant pour une catégorie donnée.

        Args:
            name: Nom de la collection (ex: pz_items).
            recreate: Si True, recrée la collection (supprime + recrée).

        Returns:
            True si la collection a été créée/recrée, False sinon.
        """
        client = self._ensure_client()
        if client is None:
            logger.warning("Impossible d'assurer la collection '%s' — Qdrant indisponible", name)
            return False

        from qdrant_client.models import (  # noqa: F811
            CollectionStatus,
            Distance,
            VectorParams,
        )

        # Verifier si la collection existe déjà
        collections = client.get_collections().collections
        existing_names = [c.name for c in collections]

        if name in existing_names:
            if not recreate:
                logger.debug("Collection Qdrant '%s' existe deja.", name)
                self._collections_created.add(name)
                return False
            # Recreate: supprimer l'ancienne
            client.delete_collection(name, timeout=30)

        # Créer la nouvelle collection
        distance_map = {"cosine": Distance.COSINE, "dot": Distance.DOT, "euclid": Distance.EUCLID}
        dist = distance_map.get(self._distance, Distance.COSINE)

        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=self._vector_size, distance=dist),
            # HNSW index params pour recherche rapide
            hnsw_config=None,  # utiliser les defauts: m=16, ef_construct=64
        )

        self._collections_created.add(name)
        logger.info("Collection Qdrant creee : %s (%d vecteurs)", name, self.count_points(name))
        return True

    def ensure_all_collections(self, categories: list[str] | None = None, recreate: bool = False) -> int:
        """Assure que toutes les collections PZ existent sur Qdrant.

        Returns:
            Nombre de collections creees.
        """
        cats = categories or DEFAULT_QDRANT_CATEGORIES
        created = 0
        for cat in cats:
            if self.ensure_collection(cat, recreate=recreate):
                created += 1
        return created

    def delete_collection(self, name: str) -> bool:
        """Supprime une collection Qdrant."""
        client = self._ensure_client()
        if client is None:
            return False
        try:
            client.delete_collection(name, timeout=30)
            self._collections_created.discard(name)
            logger.info("Collection Qdrant supprimee : %s", name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur suppression collection '%s': %s", name, exc)
            return False

    def list_collections(self) -> list[str]:
        """Liste toutes les collections Qdrant."""
        client = self._ensure_client()
        if client is None:
            return []
        return [c.name for c in client.get_collections().collections]

    # ------------------------------------------------------------------
    # Operations sur les points (embeddings)
    # ------------------------------------------------------------------

    def upsert_vectors(
        self,
        collection: str,
        points: list[dict[str, Any]] | None = None,
        id: str | None = None,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Ajoute ou met à jour un ou plusieurs points Qdrant.

        Args:
            collection: Nom de la collection cible.
            points: Liste brute de points (dict avec id, vector, payload).
            id: ID unique du point (si pas dans points).
            vector: Vecteur d'embedding (si pas dans points).
            payload: Metadata du point (si pas dans points).

        Returns:
            True si l'operation a réussi.
        """
        client = self._ensure_client()
        if client is None:
            return False

        from qdrant_client.models import PointStruct  # noqa: F811

        try:
            if points is not None:
                # Upsert batch de points
                formatted_points = []
                for p in points:
                    pid = str(p.get("id", ""))
                    pvect = p.get("vector")
                    ppayload = p.get("payload", {})
                    if pvect and isinstance(pvect, list):
                        formatted_points.append(
                            PointStruct(id=pid, vector=pvect, payload=ppayload)
                        )
                if formatted_points:
                    client.upsert(collection_name=collection, points=formatted_points)
            elif id is not None and vector is not None:
                # Upsert singleton
                pt = PointStruct(
                    id=str(id),
                    vector=vector,
                    payload=payload or {},
                )
                client.upsert(collection_name=collection, points=[pt])

            logger.debug("Upsert Qdrant OK (%d vecteurs dans '%s')", len(points if points else [1]), collection)
            return True

        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur upsert Qdrant sur '%s': %s", collection, exc)
            return False

    def batch_upsert(
        self,
        collection: str,
        vectors: list[list[float]],
        ids: list[str],
        payloads: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Upsert batch rapide (optimisé pour ingest).

        Args:
            collection: Nom de la collection.
            vectors: Liste de vecteurs d'embedding.
            ids: Liste correspondante d'IDs.
            payloads: Liste optionnelle de metadata par point.

        Returns:
            True si tous les points ont été upsertés.
        """
        if not vectors or not ids:
            return False
        if len(vectors) != len(ids):
            logger.error("batch_upsert: vectors (%d) et ids (%d) tailles incompatibles", len(vectors), len(ids))
            return False

        client = self._ensure_client()
        if client is None:
            return False

        from qdrant_client.models import PointStruct  # noqa: F811

        points = []
        payloads = payloads or [{} for _ in vectors]
        for vid, pid, ppay in zip(vectors, ids, payloads):
            points.append(PointStruct(id=str(pid), vector=vid, payload=ppay))

        try:
            client.upsert(collection_name=collection, points=points)
            logger.info("Batch upsert Qdrant OK : %d vecteurs dans '%s'", len(points), collection)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur batch upsert Qdrant sur '%s': %s", collection, exc)
            return False

    def get_point(self, collection: str, point_id: str) -> dict[str, Any] | None:
        """Récupère un point Qdrant par son ID."""
        client = self._ensure_client()
        if client is None:
            return None

        try:
            result = client.retrieve(
                collection_name=collection,
                ids=[str(point_id)],
                with_payload=True,
                with_vectors=True,
            )
            if result:
                point = result[0]
                # Handle both real PointStruct (has .id/.vector/.payload) and mock dicts
                pt_id = getattr(point, "id", None) or (point.get("id") if isinstance(point, dict) else str(point_id))
                pt_vec = getattr(point, "vector", None) or (point.get("vector") if isinstance(point, dict) else None)
                pt_pay = getattr(point, "payload", None) or (point.get("payload", {}) if isinstance(point, dict) else None)
                return {
                    "id": pt_id,
                    "vector": pt_vec,
                    "payload": pt_pay or {},
                }
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_point Qdrant echou (%s): %s", point_id, exc)
            return None

    def delete_by_id(self, collection: str, point_id: str) -> bool:
        """Supprime un point Qdrant par son ID."""
        client = self._ensure_client()
        if client is None:
            return False

        try:
            client.delete(
                collection_name=collection,
                points_selector=[str(point_id)],
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_by_id Qdrant echou (%s): %s", point_id, exc)
            return False

    def count_points(self, collection: str) -> int:
        """Renvoie le nombre de points dans une collection Qdrant."""
        client = self._ensure_client()
        if client is None:
            return -1
        try:
            info = client.get_collection(collection)
            return info.points_count or 0  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return -1

    # ------------------------------------------------------------------
    # Recherche vectorielle (cosine similarity)
    # ------------------------------------------------------------------

    def query(
        self,
        collection: str,
        query_vector: list[float],
        n_results: int = 5,
        score_threshold: float | None = None,
    ) -> list[QdrantSearchResult]:
        """Recherche les vecteurs les plus similaires.

        Args:
            collection: Nom de la collection.
            query_vector: Vecteur de requête (embedding).
            n_results: Nombre maximal de résultats.
            score_threshold: Similarité minimale (0.0-1.0 pour cosine).

        Returns:
            Liste de QdrantSearchResult triée par similarité décroissante.
        """
        client = self._ensure_client()
        if client is None:
            return []

        try:
            results = client.query_points(
                collection_name=collection,
                query=query_vector,
                limit=n_results,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=True,
            )

            hit_list = results.points if hasattr(results, "points") else []

            scored: list[QdrantSearchResult] = []
            for hit in hit_list:
                payload = hit.payload or {}
                score = hit.score if hasattr(hit, "score") else 1.0
                # Qdrant returns cosine distance (0=identique, 2=opposé)
                # Convert to similarity (0=different, 1=identique)
                sim = 1.0 - (score if self._distance == "cosine" else score)

                scored.append(QdrantSearchResult(
                    collection=collection,
                    id=str(hit.id),
                    prose=payload.get("text", ""),
                    score=sim,
                    distance=round(1.0 - sim, 6) if self._distance == "cosine" else round(sim, 6),
                    metadata_=payload,
                ))

            return scored

        except Exception as exc:  # noqa: BLE001
            logger.warning("Recherche Qdrant echou sur '%s': %s", collection, exc)
            return []

    def batch_query(
        self,
        queries: list[dict[str, Any]],
    ) -> dict[str, list[QdrantSearchResult]]:
        """Recherche multiple (plusieurs collections en parallel).

        Args:
            queries: Liste de dicts {collection, query_vector, n_results}.

        Returns:
            Dict {collection_name: [results]}
        """
        results_map: dict[str, list[QdrantSearchResult]] = {}
        for q in queries:
            col = q["collection"]
            vec = q["query_vector"]
            n = q.get("n_results", 5)
            results_map[col] = self.query(col, vec, n)
        return results_map

    def cross_collection_search(
        self,
        query_vector: list[float],
        collections: list[str] | None = None,
        n_results: int = 10,
    ) -> list[QdrantSearchResult]:
        """Recherche sur plusieurs collections Qdrant.

        Fusionne les résultats et trie par score décroissant.
        """
        if not collections:
            collections = self.list_collections()

        all_results: list[tuple[float, QdrantSearchResult]] = []

        for col in collections:
            client = self._ensure_client()
            if client is None:
                continue

            try:
                hit_list = client.query_points(
                    collection_name=col,
                    query=query_vector,
                    limit=n_results,
                    with_payload=True,
                    with_vectors=True,
                )
                hits = hit_list.points if hasattr(hit_list, "points") else []

                for hit in hits:
                    payload = hit.payload or {}
                    score = hit.score if hasattr(hit, "score") else 1.0
                    sim = 1.0 - score
                    all_results.append((sim, QdrantSearchResult(
                        collection=col,
                        id=str(hit.id),
                        prose=payload.get("text", ""),
                        score=sim,
                        distance=round(1.0 - sim, 6),
                        metadata_=payload,
                    )))
            except Exception:  # noqa: BLE001
                continue

        all_results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in all_results[:n_results]]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Verifie la sante du serveur Qdrant."""
        client = self._ensure_client()
        if client is None:
            return {"available": False, "mode": "qdrant", "error": "Client non initialise"}

        try:
            collections = client.get_collections()
            col_count = len(collections.collections) if hasattr(collections, "collections") else -1
            return {
                "available": True,
                "mode": "qdrant",
                "url": self._url,
                "collections": col_count,
                "created": list(self._collections_created),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "mode": "qdrant",
                "error": str(exc),
            }
