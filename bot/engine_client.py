"""engine_client — Client du Knowledge Engine Zomboid.

Gère la connexion au stockage vectoriel (PostgreSQL/pgvector).
Fournit un wrapper unique devant le moteur (MCP, storage direct, ou fallback).

Config via .env :
  STORAGE_BACKEND=postgres  → PostgreSQL + pgvector (defaut)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.governance.logger import get_logger
from src.storage import StorageBackend as _StorageBackend, SearchResult, create_backend

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Résultat d'une requête de connaissance Zomboid."""
    collection: str           # pz_items, pz_mechanics, pz_recipes...
    id: str                   # Identifiant déterministe (ex: Base.Axe)
    prose: str                # Description vectorisée
    metadata_: dict[str, Any] = field(default_factory=dict)  # JSON brut non modifié


# --- Abstraction StorageBackend ---

class _StorageWrapper:
    """Wrapper léger autour du StorageBackend pour la compatibilité avec le code existant."""

    def __init__(self, backend: _StorageBackend):
        self._backend = backend

    # ── Helper sync/async interop ────────────────────────────────────────

    @staticmethod
    def _run_sync(coro):
        """Executer un coroutine de manière synchrone (compat event loop actif ou standalone)."""
        import asyncio as _asyncio

        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            return _asyncio.run(coro)
        # Event loop déjà actif (pytest --asyncio=auto, etc.)
        try:
            return loop.run_until_complete(coro)
        except RuntimeError:
            # Loop fermé ou inutilisable — fallback
            return _asyncio.run(coro)

    @staticmethod
    def _maybe_await(result):
        """Retourner le résultat tel quel ou await si c'est un coroutine."""
        import asyncio as _asyncio

        if _asyncio.iscoroutine(result):
            return _StorageWrapper._run_sync(result)
        return result

    # ── Méthodes publiques ───────────────────────────────────────────────

    def query(
        self,
        collection: str,
        query_text: str,
        embedding: list[float] | None = None,
        where: dict[str, Any] | None = None,
        n_results: int = 5,
        game_version: str | None = None,
    ) -> list[SearchResult]:
        """Requête vectorielle via le StorageBackend."""
        # Si embedding fourni (ancien appel HTTP vectoriel), on l'utilise directement
        if embedding:
            return self._query_with_embedding(collection, query_text, embedding, n_results)

        # Sinon on genere l'embedding via Ollama intégré au SQLiteStorage
        results = self._maybe_await(self._backend.query(
            collection, query_text, n_results=n_results,
            filters=where, game_version=game_version,
        ))
        return [SearchResult(
            collection=r.collection,
            id=r.id,
            prose=r.prose,
            metadata_=r.metadata_ or {},
        ) for r in results]

    def _query_with_embedding(
        self,
        collection: str,
        query_text: str,
        embedding: list[float],
        n_results: int,
    ) -> list[SearchResult]:
        """Recherche en utilisant un embedding fourni (ancien appel HTTP)."""
        results = self._maybe_await(self._backend.query(
            collection, query_text, n_results=n_results,
        ))
        return [SearchResult(
            collection=r.collection,
            id=r.id,
            prose=r.prose,
            metadata_=r.metadata_ or {},
        ) for r in results]

    def list_collections(self) -> list[str]:
        """Retourne les collections disponibles."""
        return self._backend.list_collections()

    def get_by_id(
        self,
        collection: str,
        item_id: str,
        game_version: str | None = None,
    ) -> SearchResult | None:
        """Récupère une entité par ID deterministe (delegate au backend)."""
        result = self._maybe_await(self._backend.get_by_id(collection, item_id, game_version))
        if result is None:
            return None
        return SearchResult(
            collection=result.collection,
            id=result.id,
            prose=result.prose,
            metadata_=result.metadata_ or {},
        )


# --- Pipeline de fallback local (sans stockage vectoriel) ---

class _LocalFallback:
    """Fallback quand le stockage vectoriel n'est pas disponible : recherche textuelle brute sur JSON."""

    # Fournit les mêmes méthodes que le client storage pour fallback transparent.
    def query(
        self,
        collection: str,
        query_text: str,
        embedding: list[float] | None = None,
        where: dict[str, Any] | None = None,
        n_results: int = 5,
        game_version: str | None = None,
    ) -> list[SearchResult]:
        logger.warning("Stockage vectoriel indisponible → fallback local activé pour '%s'", collection)
        return []

    def list_collections(self) -> list[str]:
        return ["pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api"]


# --- Helper ---

def document_or_text(doc: Any) -> str:
    """Extrait une prose lisible depuis un document du stockage (JSON string ou texte brut)."""
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

    Utilise StorageBackend (SQLite par defaut, PostgreSQL optionnel).
    Supporte lookup déterministe par ID (pz_get_item) sans vectoriel.
    """

    # Collections prioritaires pour le routage automatique de requêtes
    COLLECTIONS = [
        "pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api",
    ]

    def __init__(self):
        # Utiliser create_backend() — STORAGE_BACKEND env controlle le backend
        try:
            self._backend = _StorageWrapper(create_backend())
            logger.info("Engine initialise avec backend=%s", self._backend._backend.backend_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("StorageBackend initialisation échouée (%s) → fallback local", exc)
            self._backend = _LocalFallback()

    # -- Recherche sémantique multi-collection --

    def search(
        self,
        queries: list[tuple[str, str]],
        n_results: int = 5,
        game_version: str | None = None,
    ) -> list[SearchResult]:
        """Exécute des recherches dans chaque collection pertinente.

        Args:
            queries: liste de (collection, query_text)
            n_results: résultats par requête
            game_version: Optionnel. Si fourni, chaque requête est filtrée
                pour ne retourner que les chunks taggés avec cette version PZ.
        """
        all_results: list[SearchResult] = []
        for collection, query_text in queries:
            if collection not in self.COLLECTIONS:
                logger.warning("Collection inconnue: %s", collection)
                continue
            results = self._backend.query(
                collection, query_text, n_results=n_results, game_version=game_version,
            )
            all_results.extend(results)
            logger.debug("Recherche '%s' dans %s → %d résultats", query_text, collection, len(results))
        return sorted(all_results, key=lambda r: getattr(r, "distance", 0))

    # -- Lookup déterministe par ID (pz_get_item) --

    def get_by_id(
        self,
        item_id: str,
        collection: str = "pz_items",
        game_version: str | None = None,
    ) -> SearchResult | None:
        """Récupère une entité exacte par son identifiant.

        Args:
            item_id: Identifiant déterministe de l'entité (ex: ``Base.Axe``).
            collection: Collection à interroger.
            game_version: Optionnel — filtre la recherche sur une version PZ.
        """
        result = self._backend.get_by_id(collection, item_id, game_version)
        if result is None:
            return None

        return SearchResult(
            collection=result.collection, id=result.id,
            prose=document_or_text(result.prose), metadata_=result.metadata_ or {},
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
        game_version: str | None = None,
    ) -> dict[str, Any]:
        """Interroge le storage staging pour le golden set gate.

        Utilisé par promote.py pour calculer le recall@5.
        Fallback local si le stockage injoignable.

        Args:
            question: Query text for vector search.
            k: Number of results to return.
            filters: Additional where conditions.
            game_version: Optional game-version constraint (B41/B42).
        """
        chunks: list[dict[str, Any]] = []

        # Compose where clause with optional version filter
        if game_version and filters:
            from src.governance.game_version import build_version_filter

            version_clause = build_version_filter(game_version)
            final_where: dict[str, Any] | None = {"$and": [version_clause, filters]} if version_clause else (filters or {})
        elif game_version:
            from src.governance.game_version import build_version_filter

            version_clause = build_version_filter(game_version)
            final_where = version_clause
        else:
            final_where = filters

        try:
            results = self._backend.query(
                "pz_staging", question, n_results=k, where=final_where, game_version=game_version,
            )
            for r in results[:k]:
                chunks.append({
                    "id": r.id,
                    "prose": r.prose if isinstance(r.prose, str) else "",
                    "metadata": r.metadata_ or {},
                })
        except Exception:  # noqa: BLE001
            pass

        return {"chunks": chunks, "query": question, "k": k}


# Need os for STORAGE_BACKEND env var
import os as _os
