"""
engine_client — Client du Knowledge Engine Zomboid.
Gère la connexion à ChromaDB et les requêtes multi-collection.
Fournit un wrapper unique devant le moteur (MCP, Chroma direct, ou fallback).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Résultat d'une requête de connaissance Zomboid."""
    collection: str           # pz_items, pz_mechanics, pz_recipes...
    id: str                   # Identifiant déterministe (ex: Base.Axe)
    prose: str                # Description vectorisée
    metadata_: dict[str, Any] = field(default_factory=dict)  # JSON brut non modifié


# --- Abstraction ChromaDB ---

class _ChromaClient:
    """Client léger vers un serveur ChromaDB distant."""

    def __init__(self, host: str):
        self._host = host.rstrip("/")
        try:
            import httpx
        except ImportError:
            httpx = None  # type: ignore[name-defined]
        self._http = httpx or None

    # pylint: disable=import-outside-toplevel
    def _get_http(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(timeout=30.0)
        return self._http

    def query(
        self,
        collection: str,
        query_text: str,
        embedding: list[float] | None = None,
        where: dict[str, Any] | None = None,
        n_results: int = 5,
    ) -> list[SearchResult]:
        """Requête vectorielle vers ChromaDB."""
        http = self._get_http()
        url = f"{self._host}/api/v1/query"
        payload: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
            "where": where or {},
        }
        if embedding is not None:
            payload["queries"] = [embedding]

        resp = http.post(url, json={"namespace": collection, **payload})
        resp.raise_for_status()
        data = resp.json()

        results: list[SearchResult] = []
        for ids, documents, metadatas, distances in zip(
            data.get("ids", [[]])[0],
            data.get("documents", [[]])[0],
            data.get("metadatas", [[]])[0],
            data.get("distances", [[]])[0],
        ):
            doc_data = {}
            if isinstance(documents, str):
                try:
                    doc_data = json.loads(documents)
                except (json.JSONDecodeError, TypeError):
                    doc_data = {"text": documents}
            results.append(SearchResult(
                collection=collection,
                id=ids,
                prose=document_or_text(documents),
                metadata_=metadatas or {},
            ))
        return results

    def list_collections(self) -> list[str]:
        """Retourne les collections disponibles."""
        http = self._get_http()
        resp = http.get(f"{self._host}/api/v1/collections")
        resp.raise_for_status()
        return [c["name"] for c in resp.json().get("names", [])]


# --- Pipeline de fallback local (sans ChromaDB) ---

class _LocalFallback:
    """Fallback quand ChromaDB n'est pas disponible : recherche textuelle brute sur JSON."""

    # Fournit les mêmes méthodes que _ChromaClient pour transparent fallback.
    def query(
        self, collection: str, query_text: str,
        embedding: list[float] | None = None,
        where: dict[str, Any] | None = None,
        n_results: int = 5,
    ) -> list[SearchResult]:
        logger.warning("ChromaDB indisponible → fallback local activé pour '%s'", collection)
        return []

    def list_collections(self) -> list[str]:
        return ["pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api"]


# --- Helper ---

def document_or_text(doc: Any) -> str:
    """Extrait une prose lisible depuis un document Chroma (JSON string ou texte brut)."""
    if isinstance(doc, str):
        try:
            return json.dumps(json.loads(doc), ensure_ascii=False)[:2000]
        except (json.JSONDecodeError, TypeError):
            return doc[:2000]
    if isinstance(doc, dict):
        return json.dumps(doc, ensure_ascii=False)[:2000]
    return str(doc)[:2000]


# --- API publique ---

class KnowledgeEngineClient:
    """Wrapper unifié devant le knowledge engine.

    Cherche d'abord ChromaDB → fallback local.
    Supporte lookup déterministe par ID (pz_get_item) sans vectoriel.
    """

    # Collections prioritaires pour le routage automatique de requêtes
    COLLECTIONS = [
        "pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api",
    ]

    def __init__(self, chroma_host: str | None = None):
        if chroma_host:
            self._backend = _ChromaClient(chroma_host)
        else:
            logger.warning("Aucun host ChromaDB fourni → fallback local")
            self._backend = _LocalFallback()

    # -- Recherche sémantique multi-collection --

    def search(self, queries: list[tuple[str, str]], n_results: int = 5) -> list[SearchResult]:
        """Exécute des recherches dans chaque collection pertinente.

        Args:
            queries: liste de (collection, query_text)
            n_results: résultats par requête
        """
        all_results: list[SearchResult] = []
        for collection, query_text in queries:
            if collection not in self.COLLECTIONS:
                logger.warning("Collection inconnue: %s", collection)
                continue
            results = self._backend.query(collection, query_text, n_results=n_results)
            all_results.extend(results)
            logger.debug("Recherche '%s' dans %s → %d résultats", query_text, collection, len(results))
        return sorted(all_results, key=lambda r: getattr(r, "distance", 0))

    # -- Lookup déterministe par ID (pz_get_item) --

    def get_by_id(self, item_id: str, collection: str = "pz_items") -> SearchResult | None:
        """Récupère une entité exacte par son identifiant. Jamais de vectoriel."""
        http = self._backend._get_http()  # pylint: disable=protected-access
        try:
            resp = http.get(
                f"{self._backend._host}/api/v1/collections/{collection}/query",  # type: ignore[attr-defined]
                json={"namespace": collection, "where": {"id": item_id}, "n_results": 1},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_by_id(%s) échoué — %s", item_id, exc)
            return None

        ids = data.get("ids", [[]])[0]
        if not ids or item_id not in ids:
            return None

        docs = data.get("documents", [[]])[0]
        metas = data.get("metadatas", [[]])[0]
        idx = ids.index(item_id)
        doc = docs[idx] if isinstance(docs, (list, tuple)) else docs
        meta = metas[idx] if isinstance(metas, (list, tuple)) else metas or {}

        return SearchResult(
            collection=collection, id=item_id,
            prose=document_or_text(doc), metadata_=meta or {},
        )

    # -- Helpers --

    def discover_collections(self) -> list[str]:
        """Retourne les collections disponibles (diagnostic)."""
        try:
            return self._backend.list_collections()
        except Exception:  # noqa: BLE001
            return self.COLLECTIONS

    # -- Golden set gate — utilisé par promote.py --

    def query_staging(
        self,
        question: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Interroge ChromaDB staging pour le golden set gate.

        Utilisé par promote.py pour calculer le recall@5.
        Fallback local si ChromaDB injoignable.
        """
        chunks: list[dict[str, Any]] = []

        # Essaie d'abord via l'API HTTP ChromaDB
        if hasattr(self._backend, "_http") and self._backend._http is not None:  # type: ignore[attr-defined]
            http = self._backend._http
            try:
                resp = http.post(
                    f"{self._backend._host}/api/v1/query",  # type: ignore[attr-defined]
                    json={
                        "namespace": "pz_staging",
                        "queries": [question],
                        "n_results": k,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                for ids, docs, metas in zip(
                    data.get("ids", [[]])[0],
                    data.get("documents", [[]])[0],
                    data.get("metadatas", [[]])[0],
                ):
                    chunks.append({"id": ids, "prose": docs if isinstance(docs, str) else "", "metadata": metas or {}})
            except Exception:  # noqa: BLE001
                pass

        return {"chunks": chunks, "query": question, "k": k}
