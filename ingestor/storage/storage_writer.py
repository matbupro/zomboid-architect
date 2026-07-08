"""
storage_writer — Écrivain de chunks vectoriels pour le Knowledge Engine Zomboid.

Gère :
- Écriture de chunks avec embedding (Ollama nomic-embed-text)
- Requête vectorielle multi-collection via StorageBackend (SQLite/PostgreSQL)
- Cross-collection search (une requête sur toutes les collections)

Schéma de données par chunk :
  - id       : hash chunk_id unique
  - text     : Le texte du chunk (vectorisé via embedding)
  - embedding: JSON array [0.1, -0.2, ...] (768 dims, NULL = non vectorisé)
  - metadata : Dict[str, Any] avec source, type, encoding, etc.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schéma de résultat (compatible avec bot/engine_client.py SearchResult)
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Résultat d'une requête vectorielle (SQLite/pgvector) — compatible avec le moteur existant."""
    collection: str
    id: str
    prose: str
    distance: float = 0.0
    metadata_: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata_ is None:
            self.metadata_ = {}


# ---------------------------------------------------------------------------
# Embedding via Ollama
# ---------------------------------------------------------------------------

class OllamaEmbedder:
    """Génère des embeddings via Ollama (nomic-embed-text)."""

    def __init__(self, base_url: str = "http://host.docker.internal:11434", model: str = "nomic-embed-text"):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float] | None:
        """Génère l'embedding d'un texte."""
        if not text or not text.strip():
            return None

        # Cache pour éviter de régénérer le même embedding
        cache_key = self._model + "|" + text[:50]  # truncate for cache key
        if cache_key in self._cache:
            return self._cache[cache_key]

        import httpx
        payload = {
            "model": self._model,
            "input": [text],
            "truncate": True,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{self._base_url}/api/embed", json=payload)
                resp.raise_for_status()
                data = resp.json()

                # Ollama embedding API retourne embeddings[] ou data[].embeddings
                embeddings = data.get("embeddings") or data.get("data", [{}])[0].get("embedding")
                if embeddings:
                    self._cache[cache_key] = embeddings[0]
                    return embeddings[0]

            logger.warning("Embedding vide retourné pour : %s", text[:50])
            return None

        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur embedding Ollama : %s", exc)
            return None

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Génère des embeddings en batch (plus efficace)."""
        if not texts:
            return []

        # Ombler via la même API avec un seul texte à la fois pour compatibilité
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Writer principal — orchestre embedding + storage vectoriel
# ---------------------------------------------------------------------------

class StorageWriter:
    """Orchestre l'écriture dans le storage vectoriel : embedding → storage → indexation.

    Utilise src.storage.StorageBackend (SQLite par defaut, PostgreSQL optionnel).
    Les embeddings sont generes via Ollama nomic-embed-text.
    """

    def __init__(self, ollama_url: str | None = None):
        self.ollama_url = ollama_url or "http://host.docker.internal:11434"

        self._embedder = OllamaEmbedder(self.ollama_url, model="nomic-embed-text")
        self._backend = self._get_backend()
        self._collections_initialized: set[str] = set()

    def _get_backend(self) -> Any:
        """Retourne le backend StorageBackend (lazy import)."""
        from src.storage.sqlite_storage import StorageBackend, _load_storage_config

        cfg = _load_storage_config()
        if hasattr(cfg, 'data_dir') and cfg.data_dir:
            return StorageBackend(data_dir=cfg.data_dir, ollama_url=self.ollama_url, config=cfg)
        return StorageBackend(ollama_url=self.ollama_url, config=cfg)

    # -- Initialisation --

    async def ensure_collection(self, name: str) -> None:
        """S'assure qu'une collection existe (la crée si nécessaire)."""
        if name in self._collections_initialized:
            return
        result = self._backend.ensure_collection(name)
        # Le backend est sync en production mais les tests utilisent AsyncMock → vérifier si coroutine
        if asyncio.iscoroutine(result):  # type: ignore[arg-type]
            await result  # type: ignore[misc]
        self._collections_initialized.add(name)
        logger.debug("Collection '%s' prête.", name)

    async def list_collections(self) -> list[str]:
        """Liste les collections existantes."""
        return self._backend.list_collections()

    async def count_collection(self, collection: str) -> int:
        """Compte de documents dans une collection."""
        try:
            return self._backend.count_collection(collection)
        except Exception:  # noqa: BLE001
            return -1

    # -- Écriture de chunks --

    async def write_chunks_to_storage(
        self,
        chunks: list[Any],  # Chunk objects from processors
        source: str,
        content_type: str = "text/plain",
        collection: str = "pz_pdfs",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Ecrit des chunks dans le storage vectoriel (embedding + stockage).

        Alias backward-compat : ecrit via StorageBackend (SQLite par defaut).

        Args:
            chunks: Liste de Chunk objects avec .text et .metadata.
            source: URL ou chemin du fichier source.
            content_type: Type MIME du contenu.
            collection: Collection cible.
            metadata: Metadata globales a ajouter a chaque chunk.

        Returns:
            True si au moins un chunk a ete ecrit avec succes.
        """
        await self.ensure_collection(collection)

        all_texts_for_embedding = []
        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue
            all_texts_for_embedding.append(text)

        # Embedding batch (si Ollama supporte le batch)
        embeddings_list = []
        try:
            embeddings_batch = self._embedder.embed_batch(all_texts_for_embedding)
            embeddings_list = [e for e in embeddings_batch if e is not None]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Batch embedding échoué : %s — fallback chunk par chunk", exc)

        # Ajouter l'embedding au chunk object avant écriture
        written_count = 0
        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue

            # Stocker l'embedding sur le chunk (attribute temporaire)
            emb = embeddings_list[i] if i < len(embeddings_list) and embeddings_list[i] else None
            setattr(chunk, "embedding", emb)

        # Ecrire via StorageBackend.write_chunks() qui gere embedding + storage
        try:
            written_count = self._backend.write_chunks(
                chunks=chunks,
                collection=collection,
                source=source,
                extra_meta=metadata or {},
                content_type=content_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ecritura storage echouee : %s", exc)

        if written_count > 0:
            logger.info("Ecritura storage : %d/%d chunks dans '%s'", written_count, len(all_texts_for_embedding), collection)
        else:
            logger.warning("Aucun chunk écrit (tous échoués ou vides).")

        return written_count > 0

    # -- Requête et recherche cross-collection --

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
    ) -> list[SearchResult]:
        """Recherche vectorielle dans une collection."""
        await self.ensure_collection(collection)

        # Generer l'embedding de la requête
        embedding = self._embedder.embed(query_text)
        if not embedding:
            logger.warning("Pas d'embedding pour la requête : '%s'", query_text[:50])
            return []

        results = await self._backend.query(
            collection, query_text, n_results=n_results, filters=None,
        )
        return [SearchResult(
            collection=r.collection, id=r.id, prose=r.prose,
            distance=r.distance, metadata_=r.metadata_ or {},
        ) for r in results]

    async def cross_collection_search(
        self,
        query_text: str,
        n_results: int = 10,
    ) -> list[SearchResult]:
        """Recherche sur TOUTES les collections (cross-collection)."""
        all_results: list[SearchResult] = []

        # Obtenir toutes les collections existantes
        collections = await self.list_collections()
        if not collections:
            logger.warning("Aucune collection storage trouvée.")
            return []

        logger.info("Recherche cross-collection (%d collections) : '%s'", len(collections), query_text[:50])

        for col in collections:
            try:
                # Garantir au moins 1 resultat par collection (evite n_results=0)
                per_col = max(1, n_results // len(collections))
                results = await self.query(col, query_text, n_results=per_col)
                all_results.extend(results)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Recherche dans %s échouée : %s", col, exc)

        # Trier par distance de similarité (plus petit = plus pertinent)
        all_results.sort(key=lambda r: r.distance)
        return all_results[:n_results]


# ---------------------------------------------------------------------------
# Helpers globaux — utilise StorageBackend
# ---------------------------------------------------------------------------

async def write_chunks_to_storage(
    chunks: list[Any],
    source: str,
    content_type: str = "text/plain",
    collection: str = "pz_pdfs",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Fonction utilitaire rapide pour écrire des chunks dans le storage vectoriel."""
    writer = StorageWriter()
    return await writer.write_chunks_to_storage(
        chunks, source, content_type, collection, metadata or {},
    )


# ---------------------------------------------------------------------------
# Aliases backward-compatibilite (pour les imports existants)
# ---------------------------------------------------------------------------

StorageWriter = StorageWriter  # self-alias pour compatibilite globale
ChromaWriter = StorageWriter  # ancien nom — maintien des imports existants
# StorageWriter (was StorageWriter alias — removed)

# Aliases vers noms actuels pour compatibilite backward
write_chunks_to_chroma = write_chunks_to_storage  # ancien nom ChromaDB → storage vectoriel
