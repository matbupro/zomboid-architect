"""src/storage/sqlite_storage -- Stockage local SQLite pour le Knowledge Engine.

Remplacement de ChromaDB via SQLite + embedding optionnel Oollama.

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
    """Résultat d'une requête de recherche — format unifié SQLite/ChromaDB."""

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
            where: Conditions where compatibles avec ChromaDB format.

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
        """Convertit un filtre ChromaDB-style en (WHERE clause, params).

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
        """Aplatit un filtre ChromaDB-style vers un dictionnaire combine."""
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
# Backend unifie (ChromaDB → SQLite fallback)
# ---------------------------------------------------------------------------

class StorageBackend:
    """Backend de stockage qui tente d'abord ChromaDB, puis SQLite.

    Mode 1 : ChromaDB en ligne → utilise ChromaDB nativement.
    Mode 2 : ChromaDB hors ligne → bascule automatique sur SQLite.
    """

    def __init__(self, chroma_host: str | None = None, data_dir: str = "data/storage", ollama_url: str | None = "http://localhost:11434"):
        self._chroma_host = chroma_host or "http://localhost:8000"
        self._sqlite = SQLiteStorage(data_dir=data_dir, ollama_url=ollama_url)

        # Verifier ChromaDB
        self._use_chroma = False
        try:
            import httpx

            with httpx.Client(timeout=5.0) as h:
                resp = h.get(f"{self._chroma_host}/api/v2/heartbeat", timeout=5)
                if resp.status_code == 200:
                    self._use_chroma = True
                    logger.info("Backend ChromaDB actif (%s)", self._chroma_host)
                else:
                    raise Exception(f"HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            logger.info("ChromaDB injoignable (%s) → fallback SQLite", exc)
            self._use_chroma = False

    @property
    def is_chroma(self) -> bool:
        """True si ChromaDB est actif."""
        return self._use_chroma

    @property
    def sqlite(self) -> SQLiteStorage:
        """Acces au stockage SQLite sous-jacent (toujours disponible)."""
        return self._sqlite

    # ------------------------------------------------------------------
    # Interface unifiée
    # ------------------------------------------------------------------

    def list_collections(self) -> list[str]:
        if self._use_chroma:
            try:
                import chromadb

                client = chromadb.HttpClient(host=self._chroma_host)
                return [c.name for c in client.list_collections()]
            except Exception:  # noqa: BLE001
                pass
        return self._sqlite.list_collections()

    def ensure_collection(self, collection: str) -> bool:
        if self._use_chroma:
            try:
                import chromadb

                client = chromadb.HttpClient(host=self._chroma_host)
                client.create_collection(collection)
                logger.info("Collection '%s' creee sur ChromaDB", collection)
                return True
            except Exception as exc:  # noqa: BLE001
                if "already exists" not in str(exc).lower():
                    raise
        return self._sqlite.ensure_collection(collection)

    def count_collection(self, collection: str) -> int:
        if self._use_chroma and self._sqlite.count_collection(collection) < 0:
            try:
                import chromadb

                client = chromadb.HttpClient(host=self._chroma_host)
                col = client.get_or_create_collection(collection)
                return col.count() if hasattr(col, "count") else -1
            except Exception:  # noqa: BLE001
                pass
        return self._sqlite.count_collection(collection)

    def write_chunks(
        self,
        chunks: list[Any],
        collection: str,
        source: str = "",
        extra_meta: dict[str, Any] | None = None,
        content_type: str = "text/plain",
    ) -> int:
        if self._use_chroma:
            try:
                return self._write_chunks_chroma(chunks, collection, source, extra_meta, content_type)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ecriture ChromaDB echou (%s) → fallback SQLite", exc)
                self._use_chroma = False

        return self._sqlite.write_chunks(chunks, collection, source, extra_meta, content_type)

    def _write_chunks_chroma(
        self,
        chunks: list[Any],
        collection: str,
        source: str,
        extra_meta: dict[str, Any] | None,
        content_type: str,
    ) -> int:  # type: ignore[no-untyped-def]
        import chromadb

        client = chromadb.HttpClient(host=self._chroma_host)
        col = client.get_or_create_collection(collection)

        ids_w, docs_w, metas_w, vecs_w = [], [], [], []
        embedder = OllamaEmbedder("http://localhost:11434")

        for i, chunk in enumerate(chunks):
            text = getattr(chunk, "text", None) if hasattr(chunk, "text") else str(chunk)
            if not text or not text.strip():
                continue

            chunk_id = f"{source}::chunk::{i}"
            meta: dict[str, Any] = {}
            if hasattr(chunk, "metadata"):
                meta.update(getattr(chunk, "metadata", {}) or {})
            meta.update(extra_meta or {})
            meta["source"] = source
            meta["content_type"] = content_type
            meta["chunk_index"] = i

            embedding = embedder.embed(text)

            ids_w.append(chunk_id)
            docs_w.append(text.strip())
            metas_w.append(meta)
            vecs_w.append(embedding or [0.0] * 768)

        col.upsert(ids=ids_w, embeddings=vecs_w, documents=docs_w, metadatas=metas_w)
        logger.info("Ecriture ChromaDB : %d chunks dans '%s'", len(ids_w), collection)
        return len(ids_w)

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
        if self._use_chroma:
            try:
                return self._query_chroma(collection, query_text, n_results, filters, game_version)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Requete ChromaDB echou (%s) → fallback SQLite", exc)
                self._use_chroma = False

        return self._sqlite.query(collection, query_text, n_results, filters, game_version, where=where)

    def _query_chroma(
        self,
        collection: str,
        query_text: str,
        n_results: int,
        filters: dict[str, Any] | None,
        game_version: str | None,
    ) -> list[SearchResult]:  # type: ignore[no-untyped-def]
        import chromadb

        client = chromadb.HttpClient(host=self._chroma_host)
        col = client.get_or_create_collection(collection)

        embedder = OllamaEmbedder("http://localhost:11434")
        embedding = embedder.embed(query_text)
        if not embedding:
            return []

        results = col.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=filters or None,
        )

        parsed: list[SearchResult] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        for i in range(len(ids)):
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""
            prose = ""
            try:
                parsed_doc = json.loads(doc)
                prose = json.dumps(parsed_doc, ensure_ascii=False)[:3000]
            except (json.JSONDecodeError, TypeError):
                prose = doc[:3000] if isinstance(doc, str) else ""

            parsed.append(SearchResult(
                collection=collection,
                id=ids[i],
                prose=prose,
                distance=float(dists[i]) if i < len(dists) else 0.0,
                metadata_=meta if isinstance(meta, dict) else {},
            ))

        return parsed

    def get_by_id(self, collection: str, item_id: str, game_version: str | None = None) -> SearchResult | None:
        """Récupère une entité par ID deterministe (fallback SQLite)."""
        if self._use_chroma:
            try:
                return self._get_by_id_chroma(collection, item_id, game_version)
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_by_id ChromaDB echou (%s) → fallback SQLite", exc)
                self._use_chroma = False

        return self._sqlite.get_by_id(collection, item_id, game_version)

    def _get_by_id_chroma(self, collection: str, item_id: str, game_version: str | None) -> SearchResult | None:  # type: ignore[no-untyped-def]
        import chromadb

        client = chromadb.HttpClient(host=self._chroma_host)
        col = client.get_or_create_collection(collection)

        where_clause: dict[str, Any] = {"$eq": item_id} if game_version else {"id": item_id}

        # ChromaDB SDK utilise different filtres — on fait une query brute
        # et on filtre le resultat en Python pour compatibilite
        try:
            results = col.get(where={"$and": [where_clause]} if game_version else None, ids=[item_id])
        except Exception:  # noqa: BLE001
            return None

        ids = results.get("ids", [[]])[0] if results.get("ids") else []
        if item_id not in ids:
            return None

        idx = ids.index(item_id)
        docs = results.get("documents", [[]])[0] if results.get("documents") else []
        metas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []

        doc_str = docs[idx] if idx < len(docs) else ""
        meta = metas[idx] if idx < len(metas) else {}

        prose = ""
        try:
            parsed_doc = json.loads(doc_str)
            prose = json.dumps(parsed_doc, ensure_ascii=False)[:3000]
        except (json.JSONDecodeError, TypeError):
            prose = doc_str[:3000] if isinstance(doc_str, str) else ""

        return SearchResult(
            collection=collection, id=item_id, prose=prose, distance=0.0, metadata_=meta or {},
        )

    def delete_collection(self, collection: str) -> None:
        """Supprime une collection (SQLite uniquement, ChromaDB supprime via API)."""
        if self._use_chroma:
            try:
                import chromadb

                client = chromadb.HttpClient(host=self._chroma_host)
                client.delete_collection(collection)
            except Exception:  # noqa: BLE001
                pass
        self._sqlite.delete_collection(collection)

    def health(self) -> dict[str, Any]:
        """Etat du backend actif."""
        if self._use_chroma:
            return {"available": True, "mode": "chromadb", "host": self._chroma_host}
        return {
            "available": True,
            "mode": "sqlite",
            "db_path": self._sqlite._db_path,  # type: ignore[attr-defined]
        }
