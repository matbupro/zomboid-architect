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

import json
from dataclasses import dataclass
from typing import Any

from src.governance.logger import get_logger
from src.storage.sqlite_storage import SearchResult

logger = get_logger(__name__)


@dataclass
class PostgresChunk:
    """Chargement chunk depuis PostgreSQL."""

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

    async def write_chunks(
        self,
        chunks: list[Any],
        source: str,
        content_type: str,
        collection: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Ecrire des chunks (non-implemente en V2 — leve NotImplementedError)."""
        logger.warning("PostgreSQL write_chunks non implemente en V2")
        return False

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        filters: dict[str, Any] | None = None,
        game_version: str | None = None,
    ) -> list[SearchResult]:
        """Recherche vectorielle (non-implemente en V2 — leve NotImplementedError)."""
        logger.warning("PostgreSQL query non implemente en V2")
        return []

    async def cross_collection_search(
        self,
        query_text: str,
        n_results: int = 10,
        collections: list[str] | None = None,
    ) -> list[SearchResult]:
        logger.warning("PostgreSQL cross_collection_search non implemente en V2")
        return []

    async def get_by_id(
        self,
        target_id: str,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> SearchResult | None:
        logger.warning("PostgreSQL get_by_id non implemente en V2")
        return None

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
            import asyncio

            async def _check() -> bool:
                async with pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                    return True

            return {"available": asyncio.get_event_loop().run_until_complete(_check()), "mode": "postgresql"}
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "mode": "postgresql", "error": str(exc)}
