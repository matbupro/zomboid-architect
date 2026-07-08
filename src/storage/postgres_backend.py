"""postgres_backend — Backend PostgreSQL/pgvector pour le stockage vectoriel.

V2 : PostgreSQL avec extension pgvector et indexes HNSW pour la recherche
     vectorielle efficace a grande echelle (> 10k items).

Pour activer : STORAGE_BACKEND=postgres dans .env + serveur PG disponible.

Schema SQL (auto-cree par init_db) :
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE z_pz_items (
        chunk_id  TEXT PRIMARY KEY,
        text      TEXT NOT NULL,
        embedding vector(768),     -- nomic-embed-text = 768 dims
        metadata_ jsonb DEFAULT '{}',
        source    TEXT,
        game_version TEXT,
        ingest_time DOUBLE PRECISION
    );
    CREATE INDEX ON z_pz_items USING hnsw (embedding vector_cosine_ops)
                  WITH (m=16, ef_construction=64);

Utilisation :
    pip install asyncpg  # requis pour le backend PostgreSQL
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Résultat d'une requête — format unifié (PG)."""

    collection: str
    id: str
    prose: str
    distance: float = 0.0
    metadata_: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.metadata_ is None:
            self.metadata_ = {}


@dataclass
class PostgresChunk:
    """Chargement chunk depuis PostgreSQL (alias SearchResult)."""

    collection: str
    id: str
    prose: str
    distance: float = 0.0
    metadata_: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.metadata_ is None:
            self.metadata_ = {}


class PostgresStorageBackend:
    """Backend PostgreSQL/pgvector (V2).

    Args:
        host: Hote du serveur PostgreSQL.
        port: Port (defaut 5432).
        db: Nom de la base de donnees.
        user: Utilisateur.
        password: Mot de passe.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        db: str = "zomboid_storage",
        user: str = "postgres",
        password: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._db = db
        self._user = user
        self._password = password
        self._conn = None  # asyncpg connection pool (initialise lazy)

    @property
    def backend_type(self) -> str:
        """Type du backend — expose le meme attribut que les autres backends."""
        return "postgresql"

    def _get_pool(self) -> Any:
        """Retourne le pool de connexions asyncpg (lazy)."""
        if self._conn is None:
            try:
                import asyncpg  # noqa: F811
            except ImportError:
                logger.warning("asyncpg non installe — impossible d'utiliser PostgreSQL")
                return None

            try:
                self._conn = asyncpg.create_pool(
                    host=self._host,
                    port=self._port,
                    database=self._db,
                    user=self._user,
                    password=self._password,
                    min_size=1,
                    max_size=4,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Connexion PostgreSQL echouee (%s:%d/%s) : %s", self._host, self._port, self._db, exc)
                return None
        return self._conn

    async def init_db(self) -> None:
        """Initialiser l'extension pgvector et les schemas."""
        pool = self._get_pool()
        if pool is None:
            raise RuntimeError("Pool PostgreSQL non disponible")

        async with pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            # Les collections (tables) sont creees par ensure_collection() a la demande

    async def ensure_collection(self, name: str) -> None:
        """S'assurer qu'une collection (table) existe."""
        pool = self._get_pool()
        if pool is None:
            return

        table = f"z_{name}"
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = $1", table
            )
            if exists:
                return

            await conn.execute(f"""
                CREATE TABLE {table} (
                    chunk_id      TEXT PRIMARY KEY,
                    text          TEXT NOT NULL,
                    embedding     vector(768),
                    metadata_     jsonb DEFAULT '{{}}',
                    source        TEXT,
                    game_version  TEXT,
                    ingest_time   DOUBLE PRECISION NOT NULL
                )
            """)
            await conn.execute(f"""
                CREATE INDEX ON {table} USING hnsw (embedding vector_cosine_ops)
                              WITH (m=16, ef_construction=64)
            """)
            logger.info("Collection PostgreSQL creee : %s", name)

    # ------------------------------------------------------------------
    # Ecriture (write_chunks) — batch INSERT/UPSERT via asyncpg
    # ------------------------------------------------------------------

    async def write_chunks(
        self,
        chunks: list[Any],
        source: str,
        content_type: str,
        collection: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Ecrire une liste de chunks en mode batch.

        Utilise INSERT ... ON CONFLICT DO UPDATE (UPSERT).
        Les embeddings sont serialises en format pgvector literal '{a,b,c}'::vector.
        """
        pool = self._get_pool()
        if pool is None:
            return False

        table = self._table_name(collection)
        await self.ensure_collection(collection)

        ingest_time = time.time()
        pg_meta = metadata or {}

        rows_to_write: list[tuple[str, str, str | None, str, str | None, str | None]] = []

        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue

            chunk_id = f"{source}::chunk::{i}"

            # Metadata: fusionner globale + par-chunk
            meta: dict[str, Any] = {}
            if hasattr(chunk, "metadata"):
                try:
                    raw_meta = getattr(chunk, "metadata", {}) or {}
                    meta.update(raw_meta)
                except (TypeError, AttributeError):
                    pass
            meta.update(pg_meta)
            meta["source"] = source
            meta["content_type"] = content_type
            meta["chunk_index"] = i

            # Embedding: extraire de chunk.text si c'est un tuple/liste (embedding, text)
            embedding_literal: str | None = None
            if isinstance(chunk, (tuple, list)) and len(chunk) >= 2:
                # Format: (embedding_list, text_str)
                emb = chunk[0]
                if isinstance(emb, list) and len(emb) == 768:
                    embedding_literal = _format_pgvector(emb)

            meta_json = json.dumps(meta, ensure_ascii=False)
            game_version = meta.get("version")

            rows_to_write.append((
                chunk_id,
                text.strip(),
                embedding_literal,
                meta_json,
                source or None,
                game_version,
            ))

        if not rows_to_write:
            return True  # rien a ecrire — pas une erreur

        async with pool.acquire() as conn:
            async with conn.transaction():
                batch = [
                    (
                        row[0],  # chunk_id
                        row[1],  # text
                        row[2],  # embedding literal
                        row[3],  # metadata json
                        row[4],  # source
                        row[5],  # game_version
                        ingest_time,
                    )
                    for row in rows_to_write
                ]

                if not batch:
                    return True

                columns = [
                    "chunk_id", "text", "embedding",
                    "metadata_", "source", "game_version", "ingest_time",
                ]
                stmt = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({', '.join(['$' + str(i+1) for i in range(len(columns))])}) "
                    f"ON CONFLICT (chunk_id) DO UPDATE SET "
                    f"text = EXCLUDED.text, "
                    f"embedding = EXCLUDED.embedding, "
                    f"metadata_ = EXCLUDED.metadata_, "
                    f"source = EXCLUDED.source, "
                    f"game_version = EXCLUDED.game_version, "
                    f"ingest_time = EXCLUDED.ingest_time"
                )

                await conn.executemany(stmt, batch)

        logger.info("PostgreSQL ecriture : %d/%d chunks dans '%s'", len(rows_to_write), len(rows_to_write), collection)
        return True

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        filters: dict[str, Any] | None = None,
        game_version: str | None = None,
    ) -> list[SearchResult]:
        """Recherche vectorielle via pgvector HNSW.

        Utilise la distance cosinus native de pgvector (embedding <=> query_vector).
        Filtres metadata appliques en WHERE via JSONB operators.
        """
        pool = self._get_pool()
        if pool is None:
            return []

        table = self._table_name(collection)

        # 1. Generer embedding de la requete via Ollama
        query_emb = await self._generate_query_embedding(query_text)
        if not query_emb:
            logger.warning("Pas d'embedding pour requete '%s'", query_text[:50])
            return []

        emb_str = _format_pgvector(query_emb)

        # 2. Construire WHERE clause a partir des filtres
        where_parts: list[str] = ["embedding IS NOT NULL"]
        params: list[Any] = [emb_str, n_results]
        param_idx = 2

        if game_version:
            where_parts.append(f"metadata_ ->> 'version' = ${param_idx}")
            params.append(game_version)
            param_idx += 1

        # Appliquer les filtres metadata ($and/$eq pattern MongoDB-style)
        if filters:
            self._apply_filters_to_where(filters, where_parts, params, param_idx)

        where_clause = " AND ".join(where_parts) if where_parts else "embedding IS NOT NULL"

        # 3. Requete pgvector — <=> retourne la distance cosinus (1 - similarite)
        search_sql = f"""
            SELECT chunk_id, text, metadata_, source, game_version,
                   (embedding <=> $1::vector) AS distance
            FROM {table}
            WHERE {where_clause}
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(search_sql, *params[:param_idx + 1] if param_idx > 2 else params)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Requete PostgreSQL echoue (%s) : %s", collection, exc)
            return []

        results: list[SearchResult] = []
        for row in rows:
            meta: dict[str, Any] = {}
            if row["metadata_"]:
                try:
                    meta = json.loads(row["metadata_"])
                except (json.JSONDecodeError, TypeError):
                    pass

            results.append(SearchResult(
                collection=collection,
                id=row["chunk_id"],
                prose=self._extract_prose(row["text"]),
                distance=float(row["distance"]),
                metadata_=meta,
            ))

        return results

    async def cross_collection_search(
        self,
        query_text: str,
        n_results: int = 10,
        collections: list[str] | None = None,
    ) -> list[SearchResult]:
        """Recherche vectorielle sur plusieurs collections PG."""
        if not collections:
            collections = await self.list_collections()

        query_emb = await self._generate_query_embedding(query_text)
        if not query_emb:
            return []

        emb_str = _format_pgvector(query_emb)
        all_results: list[tuple[float, SearchResult]] = []

        for col in collections:
            table = self._table_name(col)
            try:
                pool = self._get_pool()
                if not pool:
                    continue

                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        f"""
                        SELECT chunk_id, text, metadata_,
                               (embedding <=> $1::vector) AS distance
                        FROM {table}
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> $1::vector
                        LIMIT $2
                        """,
                        emb_str, n_results,
                    )

                for row in rows:
                    meta: dict[str, Any] = {}
                    if row["metadata_"]:
                        try:
                            meta = json.loads(row["metadata_"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    all_results.append((
                        float(row["distance"]),
                        SearchResult(
                            collection=col,
                            id=row["chunk_id"],
                            prose=self._extract_prose(row["text"]),
                            distance=float(row["distance"]),
                            metadata_=meta,
                        ),
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cross-collection search echoue (%s) : %s", col, exc)
                continue

        all_results.sort(key=lambda x: x[0])
        return [r for _, r in all_results[:n_results]]

    async def get_by_id(
        self,
        target_id: str,
        collection: str,
        game_version: str | None = None,
    ) -> SearchResult | None:
        """Récupère un chunk par son ID deterministe."""
        pool = self._get_pool()
        if pool is None:
            return None

        table = self._table_name(collection)

        # Construire WHERE avec filtre version si nécessaire
        where_clause = "chunk_id = $1"
        params: list[Any] = [target_id]
        param_idx = 2

        if game_version:
            where_clause += f" AND metadata_ ->> 'version' = ${param_idx}"
            params.append(game_version)
            param_idx += 1

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT chunk_id, text, embedding, metadata_, source, game_version "
                    f"FROM {table} WHERE {where_clause}",
                    *params,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_by_id(%s, %s) echoue : %s", target_id, collection, exc)
            return None

        if not row:
            return None

        meta: dict[str, Any] = {}
        if row["metadata_"]:
            try:
                meta = json.loads(row["metadata_"])
            except (json.JSONDecodeError, TypeError):
                pass

        return SearchResult(
            collection=collection,
            id=row["chunk_id"],
            prose=self._extract_prose(row["text"]),
            distance=0.0,
            metadata_=meta,
        )

    async def list_collections(self) -> list[str]:
        """Lister les collections PostgreSQL."""
        pool = self._get_pool()
        if pool is None:
            return []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'z_%'"
            )
            return [r["tablename"][2:] for r in rows]

    async def count_collection(self, collection: str) -> int:
        pool = self._get_pool()
        if pool is None:
            return -1
        table = f"z_{collection}"
        async with pool.acquire() as conn:
            row = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            return row if row else 0

    def health(self) -> dict[str, Any]:
        """Verifier la sante PostgreSQL."""
        pool = self._get_pool()
        if pool is None:
            return {"available": False, "mode": "postgresql", "error": "Pool non initialisé"}
        try:
            # Utiliser new_event_loop au lieu de get_event_loop pour eviter
            # les conflits avec les event loops existants (pytest-asyncio, etc.)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _check() -> bool:
                async with pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                    return True

            try:
                result = loop.run_until_complete(_check())
                return {"available": result, "mode": "postgresql"}
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "mode": "postgresql", "error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _table_name(self, collection: str) -> str:
        """Nom de table PostgreSQL pour une collection."""
        return f"z_{collection}"

    async def _generate_query_embedding(self, query_text: str) -> list[float] | None:
        """Genere l'embedding de la requete via Ollama."""
        if not self._conn:
            return None  # pool non initialisé — embedding impossible

        try:
            import httpx

            payload = {
                "model": "nomic-embed-text",
                "input": [query_text],
                "truncate": True,
            }
            with httpx.Client(timeout=30.0) as client:
                resp = client.post("http://localhost:11434/api/embed", json=payload)
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings") or data.get("data", [{}])[0].get("embedding")
                if embeddings and len(embeddings[0]) == 768:
                    return embeddings[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Embedding Ollama echou : %s", exc)
        return None

    def _apply_filters_to_where(
        self,
        filt: dict[str, Any],
        where_parts: list[str],
        params: list[Any],
        param_idx: int,
    ) -> int:
        """Applique les filtres metadata (MongoDB-style) a la clause WHERE.

        Returns le prochain indice de paramètre après ajout.
        """
        if "$and" in filt and isinstance(filt["$and"], list):
            for inner in filt["$and"]:
                param_idx = self._apply_filters_to_where(inner, where_parts, params, param_idx)
            return param_idx

        # Si le filtre est une simple clé=valeur (sans operator)
        if not any(k.startswith("$") for k in filt):
            for key, value in filt.items():
                if isinstance(value, dict):
                    if "$eq" in value:
                        val = str(value["$eq"])
                        param_idx += 1
                        where_parts.append(f"metadata_ ->> '{key}' = ${param_idx}")
                        params.append(val)
                else:
                    val_str = str(value)
                    param_idx += 1
                    where_parts.append(f"metadata_ ->> '{key}' = ${param_idx}")
                    params.append(val_str)
            return param_idx

        # Filtre avec operators explicites ($eq, $ne, etc.)
        for key, value in filt.items():
            if isinstance(value, dict):
                for op, val in value.items():
                    param_idx += 1
                    op_sql = "=" if op == "$eq" else "!=" if op == "$ne" else "=?"
                    where_parts.append(f"metadata_ ->> '{key}' {op_sql} ${param_idx}")
                    params.append(str(val))
            else:
                param_idx += 1
                where_parts.append(f"metadata_ ->> '{key}' = ${param_idx}")
                params.append(str(value))

        return param_idx

    def _extract_prose(self, doc: str) -> str:
        """Extrait une prose lisible depuis un document (JSON ou texte brut)."""
        try:
            parsed = json.loads(doc)
            return json.dumps(parsed, ensure_ascii=False)[:3000]
        except (json.JSONDecodeError, TypeError):
            return doc[:3000] if isinstance(doc, str) else ""


# ---------------------------------------------------------------------------
# Utilitaires pgvector
# ---------------------------------------------------------------------------

def _format_pgvector(vec: list[float]) -> str:
    """Formate une liste de floats en literal pgvector '{a,b,c}'.

    Exemple : [0.1, -0.2, 0.3] → '{0.1,-0.2,0.3}'
    Compatible avec le cast ::vector de PostgreSQL/pgvector.
    """
    formatted = ",".join(f"{v:.8g}" for v in vec)
    return f"{{{formatted}}}"
