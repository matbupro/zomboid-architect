"""src/retrieval/chroma_client -- Wrapper ChromaDB persistant avec fallback JSON.

Gère la connexion à une base ChromaDB locale (serveur ou fichier).
Si le serveur est injoignable, fallback sur dump JSON si disponible.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from src.governance.logger import get_logger

logger = get_logger(__name__)

# ── Default paths ────────────────────────────────────────────────────────────────

_DEFAULT_STAGING_PATH   = "data/staging/chromadb"
_DEFAULT_PROD_PATH      = "data/production/chromadb"


class ChromaClient:
    """Wrapper léger pour ChromaDB persistant.

    Tente d'abord le serveur HTTP (default port 8000).
    Si injoignable, utilise le dump JSON local si disponible.
    """

    def __init__(
        self,
        stage: str = "staging",
        host: Optional[str] = None,
        collection: Optional[str] = None,
    ):
        self._stage = stage
        self._collection = collection or (f"pz_{stage}" if stage else "pz_staging")

        # ChromaDB HTTP server (port 8000 default)
        self._chroma_host = host or f"http://localhost:8000"
        try:
            import httpx
        except ImportError:
            httpx = None  # type: ignore
        self._http = httpx

        # Local persistent path (fallback)
        root = Path(__file__).parent.parent.parent
        self._local_path = root / _DEFAULT_STAGING_PATH if stage == "staging" else root / _DEFAULT_PROD_PATH

    def query(
        self,
        question: str,
        k: int = 5,
        filters: Optional[dict] = None,
        game_version: Optional[str | "GameVersion"] = None,
    ) -> dict[str, Any]:
        """Query ChromaDB and return results.

        Args:
            question: Query text for vector search.
            k: Number of results to return.
            filters: Additional ChromaDB ``where`` filter conditions.
            game_version: Optional game-version constraint (B41/B42). When
                provided the query automatically adds a ``$and`` clause that
                isolates the specified version.

        Note:
            Filters are composed via :func:`src.governance.game_version.build_version_and`
            so both *filters* and *game_version* can coexist in a single $and.
        """
        # Import here to avoid circular imports (game_version ↔ chroma_client)
        from src.governance.game_version import build_version_filter

        combined: dict[str, Any] = {}
        if filters:
            combined.update(filters)

        version_clause = build_version_filter(game_version)
        if version_clause and combined:
            combined = {"$and": [version_clause, combined]}
        elif version_clause:
            combined = version_clause

        # Try HTTP first
        if self._http is not None:
            result = self._query_http(question, k, combined or None)
            if result.get("chunks"):
                return result

        # Fallback to local JSON dump
        logger.warning("ChromaDB server unreachable — using JSON fallback for '%s'", question[:50])
        return self._query_json(k)

    def _query_http(self, question: str, k: int, filters: Optional[dict]) -> dict[str, Any]:
        """Query via ChromaDB HTTP API."""
        try:
            http = self._http(timeout=30.0)
            url = f"{self._chroma_host}/api/v1/query"
            payload = {
                "namespace": self._collection,
                "queries": [question],
                "n_results": k,
            }
            if filters:
                payload["where"] = filters

            resp = http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("HTTP query failed: %s", exc)
            return {"chunks": [], "query": question, "k": k}

        chunks = []
        for ids, docs, metas in zip(
            data.get("ids", [[]])[0],
            data.get("documents", [[]])[0],
            data.get("metadatas", [[]])[0],
        ):
            chunks.append({
                "id": ids,
                "prose": self._extract_prose(docs),
                "metadata": metas or {},
            })

        return {"chunks": chunks, "query": question, "k": k}

    def _query_json(self, k: int) -> dict[str, Any]:
        """Fallback query from local JSON dump."""
        json_path = self._local_path / "dump.json"
        if not json_path.exists():
            logger.warning("No local ChromaDB data found at %s", str(json_path))
            return {"chunks": [], "query": "", "k": k}

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read JSON dump: %s", exc)
            return {"chunks": [], "query": "", "k": k}

        chunks = data.get("_chunks", [])
        # Simple text search fallback (since we don't have embedding here)
        # In a real system, you'd use an actual vector search
        results = []
        for chunk in chunks[:k]:
            if isinstance(chunk, dict):
                results.append({
                    "id": chunk.get("id", ""),
                    "prose": chunk.get("text", str(chunk)),
                    "metadata": chunk.get("metadata", {}),
                })

        return {"chunks": results, "query": "", "k": k}

    @staticmethod
    def _extract_prose(doc: Any) -> str:
        """Extract readable prose from ChromaDB document."""
        if isinstance(doc, str):
            try:
                return json.dumps(json.loads(doc), ensure_ascii=False)[:2000]
            except (json.JSONDecodeError, TypeError):
                return doc[:2000]
        return str(doc)[:2000]

    def list_collections(self) -> list[str]:
        """List collections available in this database."""
        if self._http is None:
            return ["pz_staging", "pz_production"]

        try:
            http = self._http(timeout=10.0)
            resp = http.get(f"{self._chroma_host}/api/v1/collections")
            resp.raise_for_status()
            return [c["name"] for c in resp.json().get("names", [])]
        except Exception:
            return ["pz_staging", "pz_production"]

    def health(self) -> dict[str, Any]:
        """Check if ChromaDB server is available."""
        if self._http is None:
            return {"available": False, "reason": "httpx not installed"}
        try:
            http = self._http(timeout=5.0)
            resp = http.get(f"{self._chroma_host}/api/v2/heartbeat")
            return {"available": resp.status_code == 200, "version": resp.text[:10]}
        except Exception:
            return {
                "available": False,
                "fallback_path": str(self._local_path),
                "local_exists": self._local_path.exists(),
            }
