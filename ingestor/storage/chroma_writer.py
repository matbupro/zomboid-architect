"""
chroma_writer — Écrivain ChromaDB pour le Knowledge Engine Zomboid.

Gère :
- Connexion au serveur ChromaDB (via HTTP ou SDK local)
- Création/initialisation des collections par défaut
- Écriture de chunks avec embedding (Ollama nomic-embed-text)
- Requête vectorielle multi-collection
- Cross-collection search (une requête sur toutes les collections)

Schéma de données : chaque document Chroma stocke :
  - id      : SHA-256(chunk_index + source_hash) — unique par chunk
  - prose   : Le texte du chunk (vectorisé via embedding)
  - metadata: Dict[str, Any] avec source, type, encoding, etc.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schéma de résultat (compatible avec bot/engine_client.py SearchResult)
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Résultat d'une requête ChromaDB — compatible avec le moteur existant."""
    collection: str
    id: str
    prose: str
    distance: float = 0.0
    metadata_: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata_ is None:
            self.metadata_ = {}


# ---------------------------------------------------------------------------
# Client ChromaDB via le SDK Python officiel (gère les versions d'API)
# ---------------------------------------------------------------------------

class ChromaClientHTTP:
    """Client ChromaDB via le SDK Python (http://host.docker.internal:8000)."""

    def __init__(self, host: str):
        self._host = host.rstrip("/")

    def _get_client(self):
        import chromadb
        return chromadb.HttpClient(host=self._host)

    def list_collections(self) -> list[str]:
        """Liste les collections existantes."""
        client = self._get_client()
        return [c.name for c in client.list_collections()]

    def create_collection(self, name: str) -> dict:
        """Crée une collection ChromaDB. Renvoie {'name': name} si créée ou existe déjà."""
        client = self._get_client()
        try:
            client.create_collection(name)
            logger.info("Collection '%s' créée.", name)
            return {"name": name}
        except Exception as exc:  # noqa: BLE001
            if "already exists" in str(exc).lower():
                logger.warning("Collection '%s' existe déjà.", name)
                return {}
            raise

    def query_collection(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        embedding: list[float] | None = None,
        where: dict[str, Any] | None = None,
    ) -> dict:
        """Requête vectorielle vers une collection (renvoie au format brut pour compatibilité)."""
        client = self._get_client()
        col = client.get_or_create_collection(collection_name)
        kwargs: dict[str, Any] = {"n_results": n_results}
        if embedding is not None:
            kwargs["query_embeddings"] = [embedding]
        elif query_text:
            kwargs["query_texts"] = [query_text]
        if where:
            kwargs["where"] = where
        result = col.query(**kwargs)
        # Convertir au format brut attendu par _parse_chroma_result
        return {
            "ids": [[result["ids"][0][i] for i in range(len(result["ids"][0]))]],
            "documents": [[result["documents"][0][i] for i in range(len(result["documents"][0]))]],
            "metadatas": [[result["metadatas"][0][i] if result["metadatas"] and result["metadatas"][0] else {}
                           for i in range(len(result["metadatas"][0]))] if result["metadatas"] and result["metadatas"][0] else [{}]],
            "distances": [[result["distances"][0][i] for i in range(len(result["distances"][0]))]] if result["distances"] and result["distances"][0] else [[]],
        }

    def add_documents(self, collection_name: str, documents: list[str], ids: list[str], metadatas: list[dict]) -> dict:
        """Ajoute des documents à une collection."""
        client = self._get_client()
        col = client.get_or_create_collection(collection_name)
        col.add(ids=ids, documents=documents, metadatas=metadatas)
        return {"added": len(ids)}


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
# Writer principal — orchestre embedding + ChromaDB
# ---------------------------------------------------------------------------

class ChromaWriter:
    """Orchestre l'écriture dans ChromaDB : embedding → storage → indexation."""

    def __init__(self, chroma_host: str | None = None, ollama_url: str | None = None):
        self.chroma_host = chroma_host or "http://host.docker.internal:8000"
        self.ollama_url = ollama_url or "http://host.docker.internal:11434"

        self._http_client = ChromaClientHTTP(self.chroma_host)
        self._embedder = OllamaEmbedder(self.ollama_url, model="nomic-embed-text")
        self._collections_initialized: set[str] = set()

    # -- Initialisation --

    async def ensure_collection(self, name: str) -> None:
        """S'assure qu'une collection existe (la crée si nécessaire)."""
        if name in self._collections_initialized:
            return

        http_client = self._http_client
        collections = http_client.list_collections()

        if name not in collections:
            logger.info("Création de la collection ChromaDB : '%s'", name)
            http_client.create_collection(name)

        self._collections_initialized.add(name)
        logger.debug("Collection '%s' prête.", name)

    async def list_collections(self) -> list[str]:
        """Liste les collections existantes."""
        return self._http_client.list_collections()

    async def count_collection(self, collection: str) -> int:
        """Compte de documents dans une collection."""
        import chromadb
        client = chromadb.HttpClient(host=self.chroma_host)
        col = client.get_or_create_collection(collection)
        return col.count() if hasattr(col, "count") else -1

    # -- Écriture de chunks --

    async def write_chunks_to_chroma(
        self,
        chunks: list[Any],  # Chunk objects from processors
        source: str,
        content_type: str = "text/plain",
        collection: str = "pz_pdfs",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Écrit des chunks dans ChromaDB (embedding + storage).

        Args:
            chunks: Liste de Chunk objects avec .text et .metadata.
            source: URL ou chemin du fichier source.
            content_type: Type MIME du contenu.
            collection: Collection ChromaDB cible.
            metadata: Metadata globales à ajouter à chaque chunk.

        Returns:
            True si au moins un chunk a été écrit avec succès.
        """
        await self.ensure_collection(collection)

        all_documents = []
        all_ids = []
        all_metadatas = []
        all_texts_for_embedding = []
        embeddings_cache = {}  # embedding par chunk index (batch embed)
        written_count = 0

        # Collecter tous les chunks
        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue

            chunk_id = f"{source}::chunk::{i}"  # ID unique par chunk
            chunk_meta = {}
            if hasattr(chunk, "metadata"):
                chunk_meta = dict(getattr(chunk, "metadata", {}))
            chunk_meta.update(metadata or {})
            chunk_meta["source"] = source
            chunk_meta["content_type"] = content_type
            chunk_meta["chunk_index"] = i
            chunk_meta["ingest_time"] = str(time.time())

            all_documents.append(text)
            all_ids.append(chunk_id)
            all_metadatas.append(chunk_meta)
            all_texts_for_embedding.append(text)

        # Embedding batch (si Ollama supporte le batch)
        embeddings_list = []
        try:
            embeddings_batch = self._embedder.embed_batch(all_texts_for_embedding)
            embeddings_list = [e for e in embeddings_batch if e is not None]  # filtrer les None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Batch embedding échoué : %s — fallback chunk par chunk", exc)

        # Écrire dans ChromaDB via le SDK Python
        import chromadb
        client = chromadb.HttpClient(host=self.chroma_host)
        col = client.get_or_create_collection(collection)
        written_count = 0

        # Regrouper les chunks par batch (Chroma préfère les bulk ops)
        ids_batch, docs_batch, metas_batch, vecs_batch = [], [], [], []
        for i, text in enumerate(all_texts_for_embedding):
            if not text.strip():
                continue
            chunk_id = f"{source}::chunk::{i}"
            chunk_meta = all_metadatas[i] if i < len(all_metadatas) else {}
            embedding = embeddings_list[i] if i < len(embeddings_list) and embeddings_list[i] else None

            ids_batch.append(chunk_id)
            docs_batch.append(text)
            metas_batch.append(chunk_meta)
            vecs_batch.append(embedding)

        # Séparer les chunks avec/sans embedding
        with_embed = [(i, ids_batch[i], docs_batch[i], metas_batch[i], vecs_batch[i])
                      for i in range(len(ids_batch)) if vecs_batch[i]]
        without_embed = [(i, ids_batch[i], docs_batch[i], metas_batch[i])
                         for i in range(len(ids_batch)) if not vecs_batch[i]]

        # Batch avec embedding (upsert) — les 4 colonnes du batch
        if with_embed:
            try:
                ids_w = [x[1] for x in with_embed]
                vecs_w = [x[4] or [0.0]*768 for x in with_embed]
                docs_w = [x[2] for x in with_embed]
                metas_w = [x[3] for x in with_embed]
                col.upsert(ids=ids_w, embeddings=vecs_w, documents=docs_w, metadatas=metas_w)
                written_count += len(with_embed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Échec upsert embedding : %s", exc)

        # Batch sans embedding (add — Chroma calculera l'embedding)
        if without_embed:
            try:
                col.add(
                    ids=[x[1] for x in without_embed],
                    documents=[x[2] for x in without_embed],
                    metadatas=[x[3] for x in without_embed],
                )
                written_count += len(without_embed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Échec add : %s", exc)

        if written_count > 0:
            logger.info("Écriture ChromaDB : %d/%d chunks dans '%s'", written_count, len(all_texts_for_embedding), collection)
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

        # Générer l'embedding de la requête
        embedding = self._embedder.embed(query_text)
        if not embedding:
            logger.warning("Pas d'embedding pour la requête : '%s'", query_text[:50])
            return []

        try:
            result_data = self._http_client.query_collection(
                collection, query_text, n_results=n_results, embedding=embedding,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Requête ChromaDB échouée (%s) : %s", collection, exc)
            return []

        results: list[SearchResult] = self._parse_chroma_result(result_data, collection)
        return results

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
            logger.warning("Aucune collection ChromaDB trouvée.")
            return []

        logger.info("Recherche cross-collection (%d collections) : '%s'", len(collections), query_text[:50])

        for col in collections:
            try:
                results = await self.query(col, query_text, n_results=n_results // max(len(collections), 1))
                all_results.extend(results)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Recherche dans %s échouée : %s", col, exc)

        # Trier par distance de similarité (plus petit = plus pertinent)
        all_results.sort(key=lambda r: r.distance)
        return all_results[:n_results]

    # -- Helpers internes --

    def _parse_chroma_result(self, data: dict, collection: str) -> list[SearchResult]:
        """Parse la réponse brute ChromaDB en SearchResult objects."""
        results = []
        ids = data.get("ids", [[]])[0]
        documents = data.get("documents", [[]])[0]
        metadatas = data.get("metadatas", [[]])[0]
        distances = data.get("distances", [[]])[0]

        for i in range(len(ids)):
            doc_str = documents[i] if isinstance(documents, (list, tuple)) else documents
            meta = metadatas[i] if isinstance(metadatas, (list, tuple)) else metadatas

            prose = ""
            try:
                import json as _json
                parsed = _json.loads(doc_str)
                prose = _json.dumps(parsed, ensure_ascii=False)[:3000]
            except (TypeError, _json.JSONDecodeError):
                prose = doc_str[:3000] if isinstance(doc_str, str) else ""

            dist = float(distances[i]) if i < len(distances) else 0.0
            id_val = ids[i] if isinstance(ids, (list, tuple)) else ids

            results.append(SearchResult(
                collection=collection,
                id=str(id_val),
                prose=prose,
                distance=dist,
                metadata_=meta if isinstance(meta, dict) else {},
            ))

        return results


# ---------------------------------------------------------------------------
# Helpers globaux
# ---------------------------------------------------------------------------

async def write_chunks_to_chroma(
    chunks: list[Any],
    source: str,
    content_type: str = "text/plain",
    collection: str = "pz_pdfs",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Fonction utilitaire rapide pour écrire des chunks dans ChromaDB."""
    writer = ChromaWriter()
    return await writer.write_chunks_to_chroma(
        chunks, source, content_type, collection, metadata or {},
    )
