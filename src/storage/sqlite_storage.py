"""src/storage/sqlite_storage -- Stockage local SQLite pour le Knowledge Engine.

Stockage vectoriel local SQLite avec embedding optionnel Ollama.

Architecture :
- Une table par collection (prefix `z_` → `z_pz_items`, `z_pz_recipes`, etc.)
- Colonne `embedding` = TEXT JSON array of floats (768 dims for nomic-embed-text)
- Similarité cosinus calculée en SQL pur
- Fallback Ollama si pas d'embedding fourni à l'écriture

Schema par table :
  id       TEXT PRIMARY KEY    → hash chunk_id unique
  text     TEXT NOT NULL       → chunk prose
  embedding TEXT               → JSON array [0.1, -0.2, ...] (NULL = non vectorisé)
  metadata TEXT NOT NULL       → JSON objet
  source   TEXT                 → origine du chunk
  version  TEXT                 → b41 / b42 / None
  ingest_time REAL              → timestamp Unix

Exemple :
    >>> from src.storage.sqlite_storage import SQLiteStorage
    >>> db = SQLiteStorage()
    >>> db.ensure_collection("pz_items")
    >>> db.write_chunks("pz_items", chunks, source="ingest.py")
    >>> results = db.query("axe pickup", n_results=5, collection="pz_items")
    >>> for r in results:
    ...     print(r.id, r.distance)  # cosine distance (0 = identique, 2 = oppose)
"""

from __future__ import annotations

import asyncio as _asyncio
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Resultat standardise (compatible SearchResult de bot/engine_client.py)
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Résultat d'une requête de recherche — format unifié (StorageBackend)."""

    collection: str
    id: str
    prose: str
    distance: float = 0.0
    metadata_: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Embedding via Ollama (facultatif)
# ---------------------------------------------------------------------------

class OllamaEmbedder:
    """Genere des embeddings via l'API Ollama locale."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float] | None:
        """Genere l'embedding d'un texte."""
        if not text or not text.strip():
            return None

        cache_key = self._model + "|" + text[:50]
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

                # Ollama renvoie embeddings[] OU data[].embeddings
                embeddings = data.get("embeddings") or data.get("data", [{}])[0].get("embedding")
                if embeddings:
                    self._cache[cache_key] = embeddings[0]
                    return embeddings[0]

            logger.warning("Embedding vide pour : %s", text[:50])
            return None

        except Exception as exc:  # noqa: BLE001
            logger.debug("Embedding echou : %s", exc)
            return None


# ---------------------------------------------------------------------------
# Stockage SQLite principal
# ---------------------------------------------------------------------------

class SQLiteStorage:
    """Stockage local base de donnees des chunks du Knowledge Engine.

    Utilise une table SQLite par collection. Les embeddings sont optionnels
    (colonne TEXT JSON). La recherche vectorielle calcule la similarite cosinus
    en SQL pur pour les lignes avec embedding non-NULL.

    Args:
        data_dir: Repertoire de la base sqlite (par defaut data/storage/zomboid.db)
        ollama_url: URL du serveur Ollama pour l'embedding optionnel.
            Si None, pas d'auto-embedding (recherche vectorielle impossible sans embedding pre-existant).
    """

    # Prefix pour eviter collisions avec d'autres tables
    _TABLE_PREFIX = "z_"

    def __init__(self, data_dir: str = "data/storage", ollama_url: str | None = "http://localhost:11434"):
        self._db_path = str(Path(data_dir) / "zomboid.db")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Embedder optionnel (Ollama)
        self._embedder: OllamaEmbedder | None = None
        if ollama_url:
            self._embedder = OllamaEmbedder(base_url=ollama_url)

    # ------------------------------------------------------------------
    # Connexion DB
    # ------------------------------------------------------------------

    def _conn(self):  # type: ignore[no-untyped-def]
        """Retourne une connexion SQLite."""
        import sqlite3

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # meilleure concurrence
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ------------------------------------------------------------------
    # Collections (tables par collection)
    # ------------------------------------------------------------------

    def _table_name(self, collection: str) -> str:
        """Nom de table pour une collection."""
        return self._TABLE_PREFIX + collection

    def ensure_collection(self, collection: str) -> bool:
        """Crée la table si elle n'existe pas. Retourne True si creee."""
        table = self._table_name(collection)
        # Verifier existence AVANT creation (COUNT=0 apres CREATE IF NOT EXISTS est ambigu)
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]

        if exists:
            logger.debug("Collection '%s' existe deja.", collection)
            return False

        sql = f"""
            CREATE TABLE {table} (
                id          TEXT PRIMARY KEY,
                text        TEXT NOT NULL,
                embedding   TEXT,
                metadata    TEXT NOT NULL DEFAULT '{{}}',
                source      TEXT,
                version     TEXT,
                ingest_time REAL NOT NULL
            )
        """
        with self._conn() as conn:
            conn.execute(sql)
            conn.commit()

        logger.info("Collection '%s' creee (0 documents)", collection)
        return True

    def list_collections(self) -> list[str]:
        """Liste les collections (tables prefixees z_)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'z_%'"
            ).fetchall()

        return [r["name"][2:] for r in rows if r["name"]]  # strip prefix

    def count_collection(self, collection: str) -> int:
        """Nombre de documents dans une collection."""
        table = self._table_name(collection)
        try:
            with self._conn() as conn:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:  # noqa: BLE001
            return -1

    def delete_collection(self, collection: str) -> None:
        """Supprime une collection (table)."""
        table = self._table_name(collection)
        with self._conn() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()

    # ------------------------------------------------------------------
    # Ecriture
    # ------------------------------------------------------------------

    def write_chunk(
        self,
        collection: str,
        chunk_id: str,
        text: str,
        metadata: dict[str, Any],
        source: str = "",
        embedding: list[float] | None = None,
    ) -> bool:
        """Ecrit un seul chunk (insert ou upsert)."""
        import time as _time

        self.ensure_collection(collection)
        ingest_time = _time.time()

        # Generer embedding automatique via Ollama si pas fourni
        if embedding is None and self._embedder and text.strip():
            embedding = self._embedder.embed(text)
            if embedding is None:
                logger.debug("Pas d'embedding pour chunk %s", chunk_id[:30])

        meta_json = json.dumps(metadata, ensure_ascii=False)
        emb_json = json.dumps(embedding) if embedding else None

        with self._conn() as conn:
            # Delete puis insert (upsert simulate)
            conn.execute(
                f"DELETE FROM {self._table_name(collection)} WHERE id = ?",
                (chunk_id,),
            )
            conn.execute(
                f"""INSERT INTO {self._table_name(collection)}
                    (id, text, embedding, metadata, source, version, ingest_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    text.strip(),
                    emb_json,
                    meta_json,
                    source or None,
                    metadata.get("version"),
                    ingest_time,
                ),
            )
            conn.commit()

        return True

    def write_chunks(
        self,
        chunks: list[Any],
        collection: str,
        source: str = "",
        extra_meta: dict[str, Any] | None = None,
        content_type: str = "text/plain",
    ) -> int:
        """Ecrit une liste de chunks (upsert batch).

        Pour chaque chunk, si embedding est None et Ollama dispo → generation auto.

        Args:
            chunks: Liste d'objets avec .text et optional .metadata.
            collection: Nom de la collection cible.
            source: Source du contenu.
            extra_meta: Metadata globales a fusionner.
            content_type: Type MIME du contenu.

        Returns:
            Nombre de chunks ecrits avec succes.
        """
        self.ensure_collection(collection)
        table = self._table_name(collection)
        ingest_time = time.time()
        written = 0

        # Batch SQL params pour rapidite
        rows_to_insert: list[tuple[str, str, str | None, str, str | None, str | None]] = []

        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue

            chunk_id = f"{source}::chunk::{i}"
            meta = {}
            if hasattr(chunk, "metadata"):
                meta = dict(getattr(chunk, "metadata", {}) or {})
            meta.update(extra_meta or {})
            meta["source"] = source
            meta["content_type"] = content_type
            meta["chunk_index"] = i
            meta["ingest_time"] = str(time.time())

            # Tentative embedding
            emb = None
            if self._embedder:
                try:
                    emb = self._embedder.embed(text)
                except Exception:  # noqa: BLE001
                    pass

            rows_to_insert.append((
                chunk_id,
                text.strip(),
                json.dumps(emb) if emb else None,
                json.dumps(meta, ensure_ascii=False),
                source or None,
                meta.get("version"),
                ingest_time,  # timestamp Unix
            ))

        # Supprimer les anciens puis inserer (upsert simulate)
        with self._conn() as conn:
            ids = [r[0] for r in rows_to_insert]
            if ids:
                placeholders = ",".join(["?"] * len(ids))
                conn.execute(
                    f"DELETE FROM {table} WHERE id IN ({placeholders})",
                    ids,
                )

            if rows_to_insert:
                conn.executemany(
                    f"""INSERT INTO {table}
                        (id, text, embedding, metadata, source, version, ingest_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows_to_insert,
                )

            conn.commit()

        written = len(rows_to_insert)
        logger.info("Ecriture SQLite : %d/%d chunks dans '%s'", written, len(rows_to_insert), collection)
        return written

    def delete_by_id(self, collection: str, chunk_id: str) -> bool:
        """Supprime un chunk par ID."""
        table = self._table_name(collection)
        with self._conn() as conn:
            cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (chunk_id,))
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Recherche vectorielle (cosinus en SQL pur)
    # ------------------------------------------------------------------

    def _vector_dot_product(self, emb_col: str) -> str:
        """Retourne l'expression SQL de produit scalaire entre deux vecteurs."""
        # On stocke les embeddings sous forme JSON array → on extrait avec SUBSTR + REPLACE
        # Solution plus simple : on charge en Python et on calcule ici pour les top-N candidates
        # Cette methode est appelee par vector_search_python qui fait le calcul cote client
        return emb_col  # placeholder

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calcule la similarite cosinus entre deux vecteurs."""
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            logger.warning(
                "Dimensions incompatibles : %d vs %d", len(a), len(b)
            )
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def cosine_distance(self, a: list[float], b: list[float]) -> float:
        """Retourne la distance cosinus (1 - similarite) pour le tri."""
        sim = self._cosine_similarity(a, b)
        return 1.0 - sim

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        filters: dict[str, Any] | None = None,
        game_version: str | None = None,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Recherche vectorielle dans une collection.

        Args:
            collection: Nom de la collection.
            query_text: Texte de requete pour embedding.
            n_results: Nombre de resultats retournes.
            filters: Filtres metadata ($and, $eq).
            game_version: Filtrage par version PZ (b41/b42).
            where: Conditions where (format MongoDB-style: $and, $eq).

        Returns:
            Liste de SearchResult triee par similarite cosinus.
        """
        # 1. Generer embedding de la requete
        query_emb = None
        if self._embedder:
            try:
                query_emb = self._embedder.embed(query_text)
            except Exception:  # noqa: BLE001
                logger.warning("Embedding echou pour la requete : '%s'", query_text[:50])

        if not query_emb:
            logger.warning(
                "Pas d'embedding disponible — retourne resultat vide pour '%s'",
                query_text[:50],
            )
            return []

        # 2. Construire WHERE clause SQL from filters
        where_clause, where_params = self._build_sql_where(filters, game_version, where)

        # 3. Charger tous les chunks avec embedding non-NULL depuis la collection
        table = self._table_name(collection)
        try:
            with self._conn() as conn:
                if where_clause:
                    rows = conn.execute(
                        f"SELECT * FROM {table} WHERE embedding IS NOT NULL AND {where_clause}",
                        where_params,
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM {} WHERE embedding IS NOT NULL".format(table)
                    ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Requete SQLite echoue (%s) : %s", collection, exc)
            return []

        if not rows:
            return []

        # 4. Calculer similarite cosinus cote client (precis + pas de dependance C extension)
        results: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            emb_str = row["embedding"]
            if not emb_str:
                continue

            try:
                emb = json.loads(emb_str)
            except (json.JSONDecodeError, TypeError):
                continue

            dist = self.cosine_distance(query_emb, emb)
            meta = {}
            try:
                meta = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass

            results.append((dist, {
                "id": row["id"],
                "prose": self._extract_prose(row["text"]),
                "metadata": meta,
                "_distance": dist,
            }))

        # 5. Trier et prendre top-N
        results.sort(key=lambda x: x[0])
        ranked = results[:n_results]

        return [
            SearchResult(
                collection=collection,
                id=r[1]["id"],
                prose=r[1]["prose"],
                distance=r[1]["_distance"],
                metadata_=r[1]["metadata"],
            )
            for r in ranked
        ]

    def _build_sql_where(
        self,
        filters: dict[str, Any] | None,
        game_version: str | None,
        where: dict[str, Any] | None,
    ) -> tuple[str, list[Any]]:
        """Convertit un filtre MongoDB-style ($and/$eq) en (WHERE clause, params).

        Returns:
            Tuple (where_clause_string, param_list) — None if no conditions.
        """
        conditions: list[str] = []
        params: list[Any] = []

        # Fusionner filters et where (priorite a where)
        combined: dict[str, Any] = {}
        if filters:
            self._flatten_filter(filters, combined)
        if where:
            self._flatten_filter(where, combined)

        # Version filter (game_version)
        if game_version:
            combined["version"] = game_version

        for key, value in combined.items():
            if isinstance(value, dict):
                # $eq / $ne operators
                if "$eq" in value:
                    val = value["$eq"]
                    conditions.append(f"(metadata->>'{key}' = ?)")
                    params.append(str(val))
                elif "$ne" in value:
                    val = value["$ne"]
                    conditions.append(f"(metadata->>'{key}' != ?)")
                    params.append(str(val))
            else:
                # Direct equality
                val_str = str(value)
                if key == "version":
                    conditions.append("(metadata->>'version' = ?)")
                    params.append(val_str)
                elif val_str.isdigit():
                    conditions.append(f"(CAST(metadata->>'{key}' AS INTEGER) = ?)")
                    params.append(int(val_str))
                else:
                    # Escape single quotes for SQL safety
                    safe_val = val_str.replace("'", "''")
                    conditions.append(f"(metadata->>'{key}' = '{safe_val}')")

        where_clause = " AND ".join(conditions) if conditions else None
        return (where_clause, params) if where_clause else (None, [])

    def _flatten_filter(self, filt: dict[str, Any], combined: dict[str, Any]) -> None:
        """Aplatit un filtre MongoDB-style ($and/$eq) vers un dictionnaire combine."""
        if "$and" in filt and isinstance(filt["$and"], list):
            for inner in filt["$and"]:
                self._flatten_filter(inner, combined)
        else:
            for key, value in filt.items():
                if key == "$or" or key == "$and":
                    continue  # skip nested operators already handled
                combined[key] = value

    def _extract_prose(self, doc: str) -> str:
        """Extrait une prose lisible depuis un document (JSON ou texte brut)."""
        try:
            parsed = json.loads(doc)
            return json.dumps(parsed, ensure_ascii=False)[:3000]
        except (json.JSONDecodeError, TypeError):
            return doc[:3000] if isinstance(doc, str) else ""

    # ------------------------------------------------------------------
    # Lookup deterministe par ID (pz_get_item style)
    # ------------------------------------------------------------------

    def get_by_id(
        self,
        collection: str,
        item_id: str,
        game_version: str | None = None,
    ) -> SearchResult | None:
        """Récupère une entité exacte par son identifiant deterministe."""
        table = self._table_name(collection)

        where_clause = "id = ?"
        params: list[Any] = [item_id]

        if game_version:
            from src.governance.game_version import build_version_filter

            version_clause = build_version_filter(game_version)
            if version_clause and "$and" in version_clause:
                for inner in version_clause["$and"]:
                    for k, v in inner.items():
                        if isinstance(v, dict) and "$eq" in v:
                            val = v["$eq"]
                            where_clause += " AND metadata->>'version' = ?"
                            params.append(val)

        try:
            with self._conn() as conn:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE {where_clause}",
                    params,
                ).fetchone()
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_by_id(%s) echoue (%s) : %s", item_id, collection, exc)
            return None

        if not row:
            return None

        meta = {}
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

        # Distance nulle pour lookup exact
        return SearchResult(
            collection=collection,
            id=row["id"],
            prose=self._extract_prose(row["text"]),
            distance=0.0,
            metadata_=meta,
        )

    # ------------------------------------------------------------------
    # Recherche cross-collection (multi-collection search)
    # ------------------------------------------------------------------

    def cross_collection_search(
        self,
        query_text: str,
        collections: list[str] | None = None,
        n_results: int = 10,
    ) -> list[SearchResult]:
        """Recherche sur plusieurs collections (cross-collection).

        Retourne les resultats fusionnes et triés par distance cosinus.
        """
        if not collections:
            collections = self.list_collections()

        query_emb = None
        if self._embedder:
            try:
                query_emb = self._embedder.embed(query_text)
            except Exception:  # noqa: BLE001
                logger.warning("Embedding echou pour cross-collection : '%s'", query_text[:50])

        if not query_emb:
            return []

        all_results: list[tuple[float, SearchResult]] = []

        for col in collections:
            table = self._table_name(col)
            try:
                with self._conn() as conn:
                    rows = conn.execute(
                        "SELECT * FROM {} WHERE embedding IS NOT NULL".format(table)
                    ).fetchall()
            except Exception:  # noqa: BLE001
                continue

            for row in rows:
                emb_str = row["embedding"]
                if not emb_str:
                    continue
                try:
                    emb = json.loads(emb_str)
                except (json.JSONDecodeError, TypeError):
                    continue

                dist = self.cosine_distance(query_emb, emb)
                meta = {}
                try:
                    meta = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass

                all_results.append((dist, SearchResult(
                    collection=col,
                    id=row["id"],
                    prose=self._extract_prose(row["text"]),
                    distance=dist,
                    metadata_=meta,
                )))

        # Tri global par distance + top-N
        all_results.sort(key=lambda x: x[0])
        return [r for _, r in all_results[:n_results]]


# ---------------------------------------------------------------------------
# Backend unifie — SQLite (defaut) + PostgreSQL/pgvector (configurable)
# ---------------------------------------------------------------------------

import os as _os


class _StorageConfig:
    """Configuration du stockage chargee depuis les variables d'environnement."""

    def __init__(self) -> None:
        self.backend: str = _os.getenv("STORAGE_BACKEND", "sqlite").lower() or "sqlite"
        self.data_dir: str = _os.getenv("STORAGE_SQLITE_DIR", "data/storage")
        self.ollama_url: str | None = _os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") or None
        # Qdrant vector store (S5-c): remote vector search over embeddings
        self.qdrant_url: str = _os.getenv("STORAGE_QDRANT_URL", "http://localhost:6333")
        # PostgreSQL options
        self.pg_host: str = _os.getenv("STORAGE_PG_HOST", "localhost")
        self.pg_port: int = int(_os.getenv("STORAGE_PG_PORT", "5432"))
        self.pg_db: str = _os.getenv("STORAGE_PG_DB", "zomboid_storage")
        self.pg_user: str = _os.getenv("STORAGE_PG_USER", "postgres")
        self.pg_pass: str | None = _os.getenv("STORAGE_PG_PASS")
        # Dual-sync pendant migration (S5-b): ecrit sur SQLite + PG simultanement
        self.dual_sync: bool = _os.getenv("STORAGE_DUAL_SYNC", "false").lower() in ("true", "1", "yes")


def _load_storage_config() -> _StorageConfig:
    return _StorageConfig()


class StorageBackend:
    """Backend de stockage vectoriel — SQLite par defaut (V1), PostgreSQL/pgvector (V2), Qdrant (V3).

    Configure via .env :
      STORAGE_BACKEND=sqlite     → SQLite local (defaut, aucun service externe)
      STORAGE_BACKEND=postgres   → PostgreSQL + pgvector (necessite un serveur PG)
      STORAGE_BACKEND=qdrant     → Qdrant distant + SQLite texte (S5-c, necessite docker-compose up qdrant)

    S5-c : Architecture hybride — SQLite garde texte+metadata, Qdrant gere les vecteurs.
           query() delegate a Qdrant pour la recherche vectorielle cosinus.
           write_chunks() upsert les embeddings vers Qdrant en parallel.

    Args:
        data_dir: Repertoire de la base SQLite (si backend=sqlite).
        ollama_url: URL Ollama pour l'embedding (optionnel).
        config: Configuration explicite. Chargee depuis l'environnement si None.
    """

    def __init__(
        self,
        data_dir: str = "data/storage",
        ollama_url: str | None = "http://localhost:11434",
        config: _StorageConfig | None = None,
    ):
        cfg = config or _load_storage_config()
        self._backend_type = cfg.backend
        self._sqlite = SQLiteStorage(data_dir=data_dir, ollama_url=ollama_url)

        # PostgreSQL backend (V2) — chargee a la demande ou eagerly en dual-sync mode
        self._postgres: Any | None = None
        self._dual_sync = cfg.dual_sync
        self._pg_ready = False  # PG confirme healthy

        # Qdrant vector store (S5-c) — remote vector search + embeddings
        self._qdrant: Any | None = None
        self._qdrant_ready = False
        self._qdrant_url = cfg.qdrant_url
        if self._backend_type == "qdrant":
            qd = self._ensure_qdrant()
            if qd is not None:
                self._qdrant_ready = True
                logger.info("Qdrant vector store active (url=%s)", cfg.qdrant_url)
                # S'assurer les collections existent
                try:
                    from src.storage.qdrant_backend import DEFAULT_QDRANT_CATEGORIES

                    qd.ensure_all_collections(DEFAULT_QDRANT_CATEGORIES, recreate=False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Initialisation collections Qdrant echoue (non-critique): %s", exc)
            else:
                logger.warning("Qdrant backend demande mais indisponible — SQLite en fallback")

        if self._dual_sync:
            # En dual-mode, on initialise PG des le demarrage (lazy mais precoce)
            pg = self._ensure_postgres()
            if pg is not None:
                self._pg_ready = True
                logger.info("Dual-sync active : SQLite + PostgreSQL (sync en cours)")
            else:
                logger.warning("Dual-sync demandé mais PG indisponible — SQLite seul")

        # Si backend postgresql ET PG indisponible, fallback explicite
        if self._backend_type == "postgresql" and self._postgres is None:
            logger.warning("PostgreSQL backend demandee mais indisponible — SQLite en fallback forcé")

    def _ensure_postgres(self) -> Any:
        """Charge le backend PostgreSQL a la demande (lazy import).

        Charge PG si:
          - backend_type == 'postgresql' (mode PG principal)
          - OU dual_sync active (ecritures simultanees SQLite + PG)
        """
        if self._postgres is None and (self._backend_type == "postgresql" or self._dual_sync):
            try:
                from src.storage.postgres_backend import PostgresStorageBackend  # noqa: F811
                cfg = _load_storage_config()
                self._postgres = PostgresStorageBackend(
                    host=cfg.pg_host,
                    port=cfg.pg_port,
                    db=cfg.pg_db,
                    user=cfg.pg_user,
                    password=cfg.pg_pass,
                )
                logger.info("PostgreSQL backend activee (host=%s:%d, db=%s)", cfg.pg_host, cfg.pg_port, cfg.pg_db)
            except ImportError as exc:  # noqa: BLE001
                logger.warning("PostgreSQL indisponible (%s) — fallback SQLite", exc)
                if self._backend_type == "postgresql":
                    self._backend_type = "sqlite"
            except Exception as exc:  # noqa: BLE001
                # Capturer toutes les exceptions (ConnectionError, etc.) de __init__
                logger.warning("PostgreSQL init echou (%s) — fallback SQLite", exc)
                if self._backend_type == "postgresql":
                    self._backend_type = "sqlite"
        return self._postgres

    def _ensure_qdrant(self) -> Any:
        """Charge le backend Qdrant a la demande (lazy import).

        S'assure que les collections par defaut existent sur le serveur.
        """
        if self._qdrant is not None:
            return self._qdrant

        try:
            from src.storage.qdrant_backend import QdrantVectorBackend  # noqa: F811

            cfg = _load_storage_config()
            self._qdrant = QdrantVectorBackend(
                url=cfg.qdrant_url,
                vector_size=768,  # nomic-embed-text dims
            )
            logger.info("Qdrant backend active (url=%s)", cfg.qdrant_url)
        except ImportError as exc:  # noqa: BLE001
            logger.warning("Qdrant indisponible (%s) — fallback SQLite", exc)
            if self._backend_type == "qdrant":
                self._backend_type = "sqlite"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant init echou (%s) — fallback SQLite", exc)
            if self._backend_type == "qdrant":
                self._backend_type = "sqlite"
        return self._qdrant

    @property
    def sqlite(self) -> SQLiteStorage:
        """Acces au stockage SQLite sous-jacent (toujours disponible)."""
        return self._sqlite

    @property
    def backend_type(self) -> str:
        """Type du backend actif : 'sqlite', 'postgresql', 'dual-sync' ou 'qdrant'."""
        if self._dual_sync and self._pg_ready:
            return "dual-sync"
        if self._backend_type == "qdrant" and self._qdrant_ready:
            return "qdrant"
        return self._backend_type

    # ------------------------------------------------------------------
    # S5-b — Dual-sync helpers (ecritures simultanees SQLite + PG)
    # ------------------------------------------------------------------

    def _sync_to_pg(self, fn_name: str, *args: Any, **kwargs: Any) -> bool:  # type: ignore[no-untyped-def]
        """Synchroniser un appel ecriture vers PG (silencieusement)."""
        if not self._dual_sync or not self._pg_ready:
            return False

        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)

        # Mapper le nom de methode SQLite → PG
        method_map = {
            "write_chunks": "write_chunks",
            "ensure_collection": "ensure_collection",
        }
        pg_method_name = method_map.get(fn_name)
        if not pg_method_name:
            return False

        async def _do_sync() -> bool:
            try:
                pg = self._ensure_postgres()
                if not pg:
                    return False
                method = getattr(pg, pg_method_name, None)
                if not method or not callable(method):
                    return False
                # Les signatures SQLite/PG differents → adapter les args
                result = await method(*args, **kwargs)
                return True  # type: ignore
            except Exception as exc:  # noqa: BLE001
                logger.debug("Dual-sync PG echou (silencieux): %s", exc)
                return False

        try:
            sync_result = loop.run_until_complete(_do_sync())
            if sync_result:
                logger.debug("Dual-sync PG OK pour %s", fn_name)
            return sync_result  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.debug("Dual-sync PG exec echou (silencieux): %s", exc)
            return False


    def list_collections(self) -> list[str]:
        if self._backend_type == "postgresql":
            pg = self._ensure_postgres()
            if pg:
                return pg.list_collections()
        return self._sqlite.list_collections()

    def ensure_collection(self, collection: str) -> bool:
        created = self._sqlite.ensure_collection(collection)
        # En dual-mode, s'assurer la collection existe aussi sur PG
        if self._dual_sync and self._pg_ready:
            try:
                loop = _asyncio.get_event_loop()
            except RuntimeError:
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
            async def _ensure_pg():  # type: ignore[no-untyped-def]
                pg = self._ensure_postgres()
                if not pg or not hasattr(pg, 'ensure_collection'):
                    return False
                await pg.ensure_collection(collection)
                return True
            try:
                loop.run_until_complete(_ensure_pg())
            except Exception as exc:  # noqa: BLE001
                logger.debug("Dual-sync ensure_collection PG echou (silencieux): %s", exc)
        return created

    def count_collection(self, collection: str) -> int:
        if self._backend_type == "postgresql":
            pg = self._ensure_postgres()
            if pg:
                return pg.count_collection(collection)
        return self._sqlite.count_collection(collection)

    def write_chunks(
        self,
        chunks: list[Any],
        collection: str,
        source: str = "",
        extra_meta: dict[str, Any] | None = None,
        content_type: str = "text/plain",
    ) -> int:
        # Ecriture primaire sur SQLite (toujours) — embedder Ollama genere les vecteurs cote SQLite
        written = self._sqlite.write_chunks(chunks, collection, source, extra_meta, content_type)

        # Synchronisation PG en dual-mode
        if self._dual_sync and self._pg_ready:
            try:
                loop = _asyncio.get_event_loop()
            except RuntimeError:
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
            async def _sync_chunks() -> bool:  # type: ignore[no-untyped-def]
                pg = self._ensure_postgres()
                if not pg or not hasattr(pg, 'write_chunks'):
                    return False
                try:
                    await pg.write_chunks(chunks, collection, source, content_type, extra_meta)
                    return True  # type: ignore
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Dual-sync write_chunks PG echou (silencieux): %s", exc)
                    return False
            try:
                loop.run_until_complete(_sync_chunks())
            except Exception as exc:  # noqa: BLE001
                logger.debug("Dual-sync write_chunks exec echou (silencieux): %s", exc)

        # S5-c : synchronisation embeddings vers Qdrant si backend=qdrant
        if self._backend_type == "qdrant" and self._qdrant_ready:
            self._sync_embeddings_qdrant(chunks, collection, source)

        return written

    def _sync_embeddings_qdrant(self, chunks: list[Any], collection: str, source: str = "") -> None:
        """Extracte les embeddings generes et upsert vers Qdrant.

        Les embeddings sont generates par Ollama dans sqlite_storage.write_chunks
        (colonne embedding JSON). On regenere ici pour extraire les vecteurs bruts.
        """
        qdb = self._ensure_qdrant()
        if not qdb or not hasattr(qdb, 'batch_upsert'):
            return

        vectors: list[list[float]] = []
        ids: list[str] = []
        payloads: list[dict[str, Any]] = []

        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue

            # Regenerer l'embedding via Ollama (déjà en cache)
            emb = None
            if self._sqlite._embedder:
                try:
                    emb = self._sqlite._embedder.embed(text)
                except Exception:  # noqa: BLE001
                    pass

            if not emb or len(emb) != 768:
                continue

            vectors.append(emb)
            chunk_id = f"{source}::chunk::{i}"
            ids.append(chunk_id)
            meta: dict[str, Any] = {}
            if hasattr(chunk, "metadata"):
                meta = dict(getattr(chunk, "metadata", {}) or {})
            meta["source"] = source
            payloads.append(meta)

        if vectors:
            try:
                qdb.batch_upsert(collection, vectors, ids, payloads)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Synchronisation embeddings Qdrant echou (silencieux): %s", exc)

    def write_chunk(
        self,
        collection: str,
        chunk_id: str,
        text: str,
        metadata: dict[str, Any],
        source: str = "",
        embedding: list[float] | None = None,
    ) -> bool:
        return self._sqlite.write_chunk(collection, chunk_id, text, metadata, source, embedding)

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        filters: dict[str, Any] | None = None,
        game_version: str | None = None,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if self._backend_type == "postgresql":
            pg = self._ensure_postgres()
            if pg:
                return pg.query(collection, query_text, n_results, filters, game_version)

        if self._backend_type == "qdrant" and self._qdrant_ready:
            # S5-c : requete vectorielle via Qdrant + texte depuis SQLite
            return self._query_qdrant(collection, query_text, n_results)

        return self._sqlite.query(collection, query_text, n_results, filters, game_version, where=where)

    def _query_qdrant(
        self,
        collection: str,
        query_text: str,
        n_results: int,
    ) -> list[SearchResult]:
        """Recherche vectorielle via Qdrant — embedding Ollama + retrieval SQLite.

        Flux :
          1. Genere embedding de la requete via Ollama (stocke en cache)
          2. Requete Qdrant pour les points les plus similaires
          3. Récupère le texte complet depuis SQLite par ID
        """
        # Etape 1: embedding via Ollama
        query_emb = None
        if self._sqlite._embedder:
            try:
                query_emb = self._sqlite._embedder.embed(query_text)
            except Exception:  # noqa: BLE001
                logger.warning("Embedding Ollama echou pour '%s' — fallback SQLite", query_text[:50])

        if not query_emb:
            logger.warning(
                "Pas d'embedding disponible pour Qdrant — retourne resultat vide pour '%s'",
                query_text[:50],
            )
            return []

        # Etape 2: requete vectorielle Qdrant
        qdb = self._ensure_qdrant()
        if not qdb or not hasattr(qdb, 'query'):
            logger.warning("Qdrant indisponible — fallback SQLite")
            return self._sqlite.query(collection, query_text, n_results)

        try:
            from src.storage.qdrant_backend import QdrantSearchResult  # noqa: F811

            qdrant_results = qdb.query(collection, query_vector=query_emb, n_results=n_results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recherche Qdrant echou (%s) — fallback SQLite", exc)
            return self._sqlite.query(collection, query_text, n_results)

        if not qdrant_results:
            return []

        # Etape 3: conversion SearchResult (compatibilité) + retrieval texte depuis SQLite
        results: list[SearchResult] = []
        for hit in qdrant_results:
            if isinstance(hit, QdrantSearchResult):
                # Récupère le texte complet depuis SQLite si non présent dans payload
                prose = hit.prose
                if not prose:
                    sr = self._sqlite.get_by_id(collection, hit.id)
                    if sr:
                        prose = sr.prose
                    else:
                        prose = ""

                results.append(SearchResult(
                    collection=collection,
                    id=hit.id,
                    prose=prose,
                    distance=round(1.0 - hit.score, 6),
                    metadata_=hit.metadata_,
                ))

        return results

    def get_by_id(self, collection: str, item_id: str, game_version: str | None = None) -> SearchResult | None:
        """Récupère une entité par ID deterministe (fallback SQLite)."""
        if self._backend_type == "postgresql":
            pg = self._ensure_postgres()
            if pg:
                return pg.get_by_id(collection, item_id, game_version)
        return self._sqlite.get_by_id(collection, item_id, game_version)

    def delete_collection(self, collection: str) -> None:
        """Supprime une collection (SQLite uniquement)."""
        self._sqlite.delete_collection(collection)

    def health(self) -> dict[str, Any]:
        """Etat du backend actif."""
        result: dict[str, Any] = {"available": True}

        # Qdrant vector store (S5-c)
        if self._backend_type == "qdrant" and self._qdrant_ready:
            qd_health = {}
            try:
                qdb = self._ensure_qdrant()
                if qdb and hasattr(qdb, 'health'):
                    qd_health = qdb.health()
            except Exception:  # noqa: BLE001
                pass
            result["qdrant"] = qd_health or {"available": False, "mode": "qdrant", "error": "health check failed"}
            result["sqlite"] = {"available": True, "db_path": self._sqlite._db_path}  # type: ignore[attr-defined]
            result["mode"] = "qdrant+sqlite-text"
            return result

        # SQLite (toujours disponible en dual-mode)
        if self._dual_sync or self._backend_type == "sqlite":
            result["mode"] = "sqlite" + ("+pg-dual" if self._dual_sync and self._pg_ready else "")
            result["sqlite"] = {"available": True, "db_path": self._sqlite._db_path}  # type: ignore[attr-defined]

        if self._dual_sync and self._pg_ready:
            pg_health = {}
            try:
                pg = self._ensure_postgres()
                if pg:
                    pg_health = pg.health()
            except Exception:  # noqa: BLE001
                pass
            result["postgresql"] = pg_health or {"available": False, "mode": "postgresql", "error": "health check failed"}
        elif self._backend_type == "postgresql":
            pg = self._ensure_postgres()
            if pg:
                result["mode"] = "postgresql"
                result["postgresql"] = pg.health()
            else:
                result["available"] = False
                result["mode"] = "postgresql"
                result["error"] = "Backend indisponible"

        return result

