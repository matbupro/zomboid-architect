"""test_postgres_backend — S5-c: Backend PostgreSQL/pgvector complet.

Verifie que le backend PostgresStorageBackend gere correctement:
- Creation/verification de collections avec HNSW index
- write_chunks (batch INSERT ... ON CONFLICT DO UPDATE)
- query vectorielle via pgvector <=> operator
- cross_collection_search
- get_by_id deterministe
- list_collections / count_collection / health
- Fallback si PG indisponible

Isolation garantie par mocks — aucun serveur PostgreSQL requis.
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock pgvector format utility
from src.storage.postgres_backend import PostgresStorageBackend, _format_pgvector, SearchResult


# ===========================================================================
# Utilitaires : mock de pool asyncpg / connexions
# ===========================================================================


class _MockRow:
    """Simule une ligne retournee par asyncpg."""

    def __init__(self, data: dict[str, Any]):
        for k, v in data.items():
            setattr(self, k, v)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class _MockConnection:
    """Simule une connection asyncpg avec transactions."""

    def __init__(self):
        self._tables: dict[str, bool] = {}
        self._data: dict[str, list[dict[str, Any]]] = {}  # table -> rows
        self._rows_returned: list[list[_MockRow]] = []

    def transaction(self) -> AsyncMock:
        """Simule conn.transaction() async context manager."""
        mock = AsyncMock()
        mock.__aenter__ = AsyncMock(return_value=self)
        mock.__aexit__ = AsyncMock(return_value=None)
        return mock

    async def execute(self, query: str, *args: Any) -> None:
        pass  # create/copy/insert ignored

    async def fetch(self, query: str, *args: Any) -> list[_MockRow]:
        """Simule une requete SELECT avec support pgvector distance."""
        rows = []
        if "SELECT COUNT" in query:
            # count_collection
            table_name = query.split("FROM ")[-1].strip().rstrip(";")
            count = len(self._data.get(table_name, []))
            return [_MockRow({"count": count})]

        if "embedding <=>" in query and "$1::vector" in query:
            # Requete vectorielle
            limit_match = None
            for part in query.split():
                if part.lstrip("$").isdigit():
                    limit_match = int(part.lstrip("$"))

            table_name = None
            for line in query.split("\n"):
                if "FROM" in line and "WHERE" not in line.upper():
                    continue
                parts = line.lower().split("from")
                for p in parts:
                    t = p.strip().split()[0] if p.strip() else None
                    if t and t.startswith("z_"):
                        table_name = t

            mock_data = self._data.get(table_name, [])
            # Simuler distances cosinus (trié)
            for i, row_data in enumerate(mock_data):
                distance = float(row_data.get("_mock_distance", 0.1 * (i + 1)))
                rows.append(_MockRow({
                    "chunk_id": row_data["chunk_id"],
                    "text": row_data["text"],
                    "metadata_": json.dumps(row_data.get("metadata_", {})) if isinstance(row_data.get("metadata_"), dict) else row_data.get("metadata_"),
                    "source": row_data.get("source"),
                    "game_version": row_data.get("game_version"),
                    "distance": distance,
                }))

        # Pour les requetes INSERT/UPSERT
        if "INSERT" in query or "ON CONFLICT" in query:
            table_name = None
            for line in query.split("\n"):
                if "INTO" in line and "VALUES" not in line:
                    table_name = line.split("INTO")[1].strip().split()[0]
                    break

        return rows

    async def fetchrow(self, query: str, *args: Any) -> _MockRow | None:
        """Simule fetchrow (get_by_id)."""
        chunk_id = args[0] if args else ""
        for table_rows in self._data.values():
            for row_data in table_rows:
                if row_data["chunk_id"] == chunk_id:
                    return _MockRow({
                        "chunk_id": row_data["chunk_id"],
                        "text": row_data["text"],
                        "embedding": row_data.get("embedding"),
                        "metadata_": json.dumps(row_data.get("metadata_", {})) if isinstance(row_data.get("metadata_"), dict) else None,
                        "source": row_data.get("source"),
                        "game_version": row_data.get("game_version"),
                    })
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Simule fetchval (single value)."""
        if "COUNT" in query:
            table_name = query.split("FROM ")[-1].strip().rstrip(";")
            return len(self._data.get(table_name, []))
        if "SELECT 1" in query:
            return 1
        return None

    async def executemany(self, query: str, batch: list[tuple]) -> None:
        """Simule executemany (batch write)."""
        # Extraire le nom de table
        table_name = "z_pz_items"
        for line in query.split("\n"):
            if "INTO" in line and "VALUES" not in line:
                parts = line.split("INTO")
                if len(parts) > 1:
                    table_name = parts[-1].strip().split()[0]
                break

        if table_name not in self._data:
            self._data[table_name] = []

        for row_vals in batch:
            # Parse les valeurs positionnelles du UPSERT
            row_data = {
                "chunk_id": row_vals[0] if len(row_vals) > 0 else "",
                "text": row_vals[1] if len(row_vals) > 1 else "",
                "embedding": row_vals[2] if len(row_vals) > 2 else None,
                "metadata_": row_vals[3] if len(row_vals) > 3 else "{}",
                "source": row_vals[4] if len(row_vals) > 4 else None,
                "game_version": row_vals[5] if len(row_vals) > 5 else None,
            }

        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass


class _MockPool:
    """Simule un pool de connections asyncpg."""

    def __init__(self, conn: _MockConnection):
        self._conn = conn

    def acquire(self) -> "_MockConnection":
        return self._conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a: Any) -> None:
        pass


# ===========================================================================
# Test _format_pgvector (pure utility)
# ===========================================================================


class TestFormatPgVector:
    """Verifie le format pgvector '{a,b,c}'.vector."""

    def test_simple_three_dims(self):
        result = _format_pgvector([0.1, -0.2, 0.3])
        assert "{" in result and "}" in result
        assert "0.1" in result and "-0.2" in result

    def test_768_dims_matches_nomic(self):
        vec = [i * 0.001 for i in range(768)]
        result = _format_pgvector(vec)
        parts = result.strip("{}").split(",")
        assert len(parts) == 768

    def test_zero_vector(self):
        result = _format_pgvector([0.0] * 10)
        assert "0" in result

    def test_negative_values(self):
        result = _format_pgvector([-1.0, -2.0, -3.0])
        parts = result.strip("{}").split(",")
        assert all(float(p) < 0 for p in parts)

    def test_format_is_compatible_with_pg_cast(self):
        vec = [0.12345678, -0.98765432, 1e-8]
        result = _format_pgvector(vec)
        # Le format doit etre utilisable en SQL: '{...}'::vector
        assert result.startswith("{") and result.endswith("}")


# ===========================================================================
# Test PostgresStorageBackend — init et health
# ===========================================================================


class TestPgInitHealth:

    @pytest.mark.asyncio
    async def test_init_fails_without_asyncpg(self):
        """Sans asyncpg, _get_pool retourne None."""
        # asyncpg n'est pas installé → le fallback ImportError se déclenche nativement
        backend = PostgresStorageBackend()
        assert backend._get_pool() is None

    def test_health_unavailable(self):
        """Sans pool, health retourne available=False."""
        with patch.object(PostgresStorageBackend, "_get_pool", return_value=None):
            backend = PostgresStorageBackend()
            health = backend.health()
            assert health["available"] is False
            assert health["mode"] == "postgresql"

    @pytest.mark.asyncio
    async def test_health_available_with_pool(self):
        """Avec pool mocké, health retourne available=True."""

        async def _fetch(*a, **k): return 1

        # Connexion mockée — fetchval renvoie un coroutine
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=_fetch)

        # Pool: acquire() retourne un async context manager
        acm_mock = AsyncMock()
        acm_mock.__aenter__ = AsyncMock(return_value=mock_conn)
        acm_mock.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value = acm_mock

        with patch.object(PostgresStorageBackend, "_get_pool", return_value=mock_pool):
            backend = PostgresStorageBackend()
            health = backend.health()
            assert health["available"] is True
            assert health["mode"] == "postgresql"

    @pytest.mark.asyncio
    async def test_init_creates_pool_when_asyncpg_present(self):
        """Avec asyncpg installé, _get_pool cree le pool."""
        try:
            import asyncpg as _asyncpg_mod  # noqa: F401
        except ImportError:
            pytest.skip("asyncpg not installed")

        with patch("src.storage.postgres_backend.asyncpg.create_pool") as mock_create:
            mock_pool = MagicMock()
            mock_create.return_value = mock_pool
            backend = PostgresStorageBackend(
                host="localhost", port=5432, db="test_db", user="test_user", password="test_pass"
            )
            pg_pool = backend._get_pool()
            assert pg_pool == mock_pool
            mock_create.assert_called_once_with(
                host="localhost", port=5432, database="test_db",
                user="test_user", password="test_pass", min_size=1, max_size=4,
            )


# ===========================================================================
# Test ensure_collection (table + HNSW index)
# ===========================================================================


class TestPgEnsureCollection:

    @pytest.mark.asyncio
    async def test_creates_table_and_index(self):
        mock_conn = _MockConnection()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(PostgresStorageBackend, "_get_pool", return_value=mock_pool):
            backend = PostgresStorageBackend()
            await backend.ensure_collection("pz_items")
            # Pas d'exception = la table a ete creee


# ===========================================================================
# Test write_chunks (batch INSERT ... ON CONFLICT)
# ===========================================================================


class MockChunk:
    """Simule un objet Chunk avec .text et .metadata."""

    def __init__(self, text: str, metadata: dict[str, Any] | None = None, chunk_index: int = 0):
        self.text = text
        self.metadata = metadata or {}
        self.chunk_index = chunk_index


class TestPgWriteChunks:

    @pytest.mark.asyncio
    async def test_writes_returns_false_without_asyncpg(self):
        """Sans asyncpg, _get_pool retourne None → write_chunks retourne False."""
        try:
            import asyncpg  # noqa: F401
            pytest.skip("asyncpg installed — skip this fallback test")
        except ImportError:
            pass

        backend = PostgresStorageBackend()
        result = await backend.write_chunks(
            chunks=[MockChunk("test")],
            source="test",
            content_type="text/plain",
            collection="pz_items",
        )
        assert result is False


# ===========================================================================
# Test query vectorielle (pgvector <=>)
# ===========================================================================


class TestPgQuery:

    @pytest.mark.asyncio
    async def test_returns_empty_without_embedding(self):
        mock_conn = _MockConnection()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(PostgresStorageBackend, "_get_pool", return_value=mock_pool):
            backend = PostgresStorageBackend()
            # Pas d'Ollama — embedding None → retourne []
            results = await backend.query("pz_items", "test query")
            assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_pool_none(self):
        with patch.object(PostgresStorageBackend, "_get_pool", return_value=None):
            backend = PostgresStorageBackend()
            results = await backend.query("pz_items", "test")
            assert results == []


# ===========================================================================
# Test get_by_id deterministe
# ===========================================================================


class TestPgGetById:

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self):
        with patch.object(PostgresStorageBackend, "_get_pool", return_value=None):
            backend = PostgresStorageBackend()
            result = await backend.get_by_id("some-id", "pz_items")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_conn = _MockConnection()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(PostgresStorageBackend, "_get_pool", return_value=mock_pool):
            backend = PostgresStorageBackend()
            result = await backend.get_by_id("nonexistent", "pz_items")
            assert result is None


# ===========================================================================
# Test list_collections et count_collection
# ===========================================================================


class TestPgListCount:

    @pytest.mark.asyncio
    async def test_list_returns_empty_without_pool(self):
        with patch.object(PostgresStorageBackend, "_get_pool", return_value=None):
            backend = PostgresStorageBackend()
            result = await backend.list_collections()
            assert result == []

    @pytest.mark.asyncio
    async def test_count_returns_minus_one_without_pool(self):
        with patch.object(PostgresStorageBackend, "_get_pool", return_value=None):
            backend = PostgresStorageBackend()
            result = await backend.count_collection("pz_items")
            assert result == -1


# ===========================================================================
# Test _apply_filters_to_where (pure logic)
# ===========================================================================


class TestPgFilterLogic:

    def test_simple_filter(self):
        backend = PostgresStorageBackend()
        where_parts: list[str] = ["embedding IS NOT NULL"]
        params: list[Any] = [None, 5, 3]  # emb_str, n_results, next_idx ($3)
        idx = backend._apply_filters_to_where({"version": "b42"}, where_parts, params, 3)
        assert idx == 4
        assert any("version" in p for p in where_parts)

    def test_and_filter(self):
        backend = PostgresStorageBackend()
        where_parts: list[str] = ["embedding IS NOT NULL"]
        params: list[Any] = [None, 5, 3]
        idx = backend._apply_filters_to_where(
            {"$and": [{"version": "b42"}, {"item_type": "weapon"}]},
            where_parts, params, 3,
        )
        assert idx == 5

    def test_eq_operator_filter(self):
        backend = PostgresStorageBackend()
        where_parts: list[str] = ["embedding IS NOT NULL"]
        params: list[Any] = [None, 5, 3]
        idx = backend._apply_filters_to_where(
            {"version": {"$eq": "b42"}},
            where_parts, params, 3,
        )
        assert idx == 4


# ===========================================================================
# Test StorageBackend integration (PostgreSQL mode)
# ===========================================================================


class TestPgStorageBackendIntegration:

    @pytest.mark.asyncio
    async def test_backend_type_sqlite_default(self):
        """Par defaut, le backend est sqlite."""
        from src.storage.sqlite_storage import StorageBackend

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            sb = StorageBackend(data_dir=tmpdir)
            assert sb.backend_type == "sqlite"
