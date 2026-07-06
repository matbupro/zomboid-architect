"""src/retrieval/chroma_client -- Wrapper ChromaDB via SDK officiel.

Gere la connexion a une base ChromaDB (serveur HTTP ou fichier).
Sert au golden-set gate de promote.py et aux queries de retrieval.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from src.governance.logger import get_logger

logger = get_logger(__name__)

# ── Default paths ────────────────────────────────────────────────────────────────

_DEFAULT_STAGING_PATH = "data/staging/chromadb"
_DEFAULT_PROD_PATH = "data/production/chromadb"


def _get_chromadb():  # type: ignore[no-untyped-def]
    """Import chromadb lazily."""
    import chromadb as mod  # noqa: F811

    return mod


class ChromaClient:
    """Wrapper ChromaDB via SDK (HttpClient ou PersistentClient)."""

    def __init__(
        self,
        stage: str = "staging",
        host: Optional[str] = None,
        collection: Optional[str] = None,
    ):
        self._stage = stage
        self._collection_name = collection or (f"pz_{stage}" if stage else "pz_staging")

        chromadb_mod = _get_chromadb()

        # Tente d'abord le serveur HTTP
        self._chroma_host = host or "http://localhost:8000"
        self._client = None  # type: ignore[assignment]
        try:
            client_ = chromadb_mod.HttpClient(host=self._chroma_host)
            # Verifier que le client est joignable
            client_.list_collections()
            self._client = client_
        except Exception as exc:  # noqa: BLE001
            logger.warning("ChromaDB HTTP (%s) injoignable: %s", self._chroma_host, exc)
            # Fallback local persistent
            root = Path(__file__).parent.parent.parent
            db_path = root / _DEFAULT_STAGING_PATH if stage == "staging" else root / _DEFAULT_PROD_PATH
            try:
                self._client = chromadb_mod.PersistentClient(path=str(db_path))
                logger.info("Fallback ChromaDB local active: %s", db_path)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("ChromaDB local (%s) injoignable: %s", db_path, exc2)
                self._client = None

        self._embedding_fn = self._make_embedder()

    def _make_embedder(self):  # type: ignore[no-untyped-def]
        """Retourne une function d'embedding ou None."""
        try:
            import httpx
        except ImportError:
            return None

        ollama_url = (
            "http://localhost:11434"
            if not hasattr(__import__("os"), "environ") and False
            else "http://host.docker.internal:11434"
        )
        # Essayer localhost d'abord
        for url in ["http://localhost:11434", "http://host.docker.internal:11434"]:
            try:
                with httpx.Client(timeout=5.0) as h:
                    h.get(url + "/api/version")
                ollama_url = url
                break
            except Exception:  # noqa: BLE001
                continue

        def embed(text: str) -> list[float] | None:  # type: ignore[misc]
            if not text or not text.strip():
                return None
            payload = {"model": "nomic-embed-text", "input": [text], "truncate": True}
            try:
                with httpx.Client(timeout=15.0) as h:
                    resp = h.post(ollama_url + "/api/embed", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    emb = data.get("embeddings") or (data.get("data", [{}])[0].get("embedding"))
                    return emb[0] if emb else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding Ollama echou: %s", exc)
                return None

        return embed

    def _ensure_client(self) -> Any:  # type: ignore[no-untyped-def]
        """Retourne le client ChromaDB ou None."""
        if self._client is None:
            logger.warning("Aucun client ChromaDB disponible")
        return self._client

    # ── Query ────────────────────────────────────────────────────────────────────

    def query(
        self,
        question: str,
        k: int = 5,
        filters: Optional[dict] = None,
        game_version: Optional[str | "GameVersion"] = None,  # noqa: F821
    ) -> dict[str, Any]:
        """Query ChromaDB across all relevant collections.

        Uses the ChromaDB SDK (consistent with ingest.py writes).
        Embedding via Ollama nomic-embed-text.
        Searches pz_items + pz_recipes + pz_mechanics (same collections as ingest).
        """
        from src.governance.game_version import build_version_filter

        client = self._ensure_client()
        if client is None:
            return {"chunks": [], "query": question, "k": k}

        # Build combined where clause — flatten / normaliser pour ChromaDB
        combined: dict[str, Any] = {}
        if filters:
            if "$and" in filters and isinstance(filters["$and"], list):
                combined["conditions"] = list(filters["$and"])  # de-nest
            else:
                combined["conditions"] = [filters]

        version_clause = build_version_filter(game_version)
        if version_clause:
            combined.setdefault("conditions", []).append(version_clause)

        # Construire le $and final aplatit tout
        conditions = combined.get("conditions", [])
        if len(conditions) == 1:
            combined = conditions[0]
        elif len(conditions) > 1:
            combined = {"$and": conditions}
        else:
            combined = {}

        # Embed the query
        if self._embedding_fn is None:
            logger.warning("Pas d'embedder disponible — retourne resultat vide")
            return {"chunks": [], "query": question, "k": k}

        embedding = self._embedding_fn(question)
        if embedding is None:
            logger.warning("Embedding echou pour la requete — resultat vide")
            return {"chunks": [], "query": question, "k": k}

        # Search across all collections populated by ingest.py
        collections_to_search = [
            c for c in client.list_collections()
            if c.name in ("pz_items", "pz_recipes", "pz_mechanics", "pz_guides")
        ]
        if not collections_to_search:
            logger.warning("Aucune collection cible trouvee dans ChromaDB")
            return {"chunks": [], "query": question, "k": k}

        all_chunks: list[dict[str, Any]] = []
        for col in collections_to_search:
            try:
                results = col.query(
                    query_embeddings=[embedding],
                    n_results=k * 2,  # pull more to merge across collections
                    where=combined if combined else None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Query collection '%s' echou: %s", col.name, exc)
                continue

            ids = results.get("ids", [[]])[0] if results.get("ids") else []
            docs = results.get("documents", [[]])[0] if results.get("documents") else []
            metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
            dists = results.get("distances", [[]])[0] if results.get("distances") else []

            for rid, rdoc, rmeta, rd in zip(ids, docs, metas, dists):
                # Extraire l'ID deterministe (base_id) des metadata si dispo
                det_id = (rmeta or {}).get("base_id", rid)
                all_chunks.append({
                    "id": det_id,
                    "prose": self._extract_prose(rdoc),
                    "metadata": rmeta or {},
                    "_distance": rd,  # pour le tri inter-collection
                })

        # Trier par distance (fusionne les collections) et prendre top-k
        all_chunks.sort(key=lambda c: c.get("_distance", 999))
        for c in all_chunks:
            c.pop("_distance", None)  # nettoyer avant retour

        return {"chunks": all_chunks[:k], "query": question, "produit_query": question, "k": k}

    def get_by_id(
        self, target_id: str, collection: str, game_version: str | None = None
    ) -> Any:
        """Lookup deterministic item/guide by its ID.
        Returns a SimpleNamespace with .id, .collection, .prose, and .metadata_.
        """
        from types import SimpleNamespace

        client = self._ensure_client()
        if client is None:
            return None
        try:
            col = client.get_collection(name=collection)
            where = {}
            if game_version:
                where["game_version"] = game_version
            res = col.get(ids=[target_id], where=where if where else None)

            # Check if we actually found something
            if not res or not res["ids"] or res["ids"][0] != target_id:
                return None

            return SimpleNamespace(
                id=res["ids"][0],
                collection=collection,
                prose=self._extract_prose(res["documents"][0]),
                metadata_=res["metadatas"][0],
            )
        except Exception as exc:
            logger.error("get_by_id error for %s in %s: %s", target_id, collection, exc)
            return None


    @staticmethod
    def _extract_prose(doc: Any) -> str:
        """Extract readable prose from ChromaDB document."""
        if isinstance(doc, str):
            try:
                return json.dumps(json.loads(doc), ensure_ascii=False)[:2000]
            except (json.JSONDecodeError, TypeError):
                return doc[:2000]
        return str(doc)[:2000]

    # ── Collections ──────────────────────────────────────────────────────────────

    def list_collections(self) -> list[str]:
        """List collections available in this database."""
        client = self._ensure_client()
        if client is None:
            return []
        try:
            return [c.name for c in client.list_collections()]
        except Exception:  # noqa: BLE001
            return []

    # ── Health ───────────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Check if ChromaDB server is available."""
        try:
            import httpx
        except ImportError:
            return {"available": False, "reason": "httpx not installed"}

        client = self._ensure_client()
        if client is None:
            return {
                "available": False,
                "fallback_path": str(self._chroma_host),
            }

        # Check HTTP connectivity
        try:
            hb = httpx.get(f"{self._chroma_host}/api/v2/heartbeat", timeout=5)
            return {"available": hb.status_code == 200, "mode": "http"}
        except Exception:  # noqa: BLE001
            root = Path(__file__).parent.parent.parent
            db_path = root / _DEFAULT_STAGING_PATH if self._stage == "staging" else root / _DEFAULT_PROD_PATH
            return {
                "available": False,
                "fallback_path": str(db_path),
                "local_exists": db_path.exists(),
            }
