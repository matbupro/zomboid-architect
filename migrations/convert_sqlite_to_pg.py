#!/usr/bin/env python3
"""convert_sqlite_to_pg — Migrer les donnees SQLite → PostgreSQL/pgvector.

Lit toutes les collections de la base SQLite locale, les transforment
et les injecte dans PostgreSQL via le StorageBackend switch (pgvector).

Usage CLI :
    python migrations/convert_sqlite_to_pg.py --sqlite data/storage/zomboid.db
    python migrations/convert_sqlite_to_pg.py --sqlite path/to/db.sqlite --pg-host localhost --pg-port 5432

Variables d'environnement optionnelles :
    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASS
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


# ===========================================================================
# Configuration
# ===========================================================================

PG_ENV = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "db": os.getenv("PG_DB", "zomboid_storage"),
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASS", ""),
}


# ===========================================================================
# Lecture SQLite — collections (tables z_*) et operationnelles
# ===========================================================================

def list_sqlite_collections(db_path: str) -> list[str]:
    """Retourne toutes les tables de collection dans la base SQLite."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'z_%'",
        ).fetchall()
        return sorted([r[0] for r in rows])
    finally:
        conn.close()


def read_collection_rows(db_path: str, table_name: str) -> list[dict[str, Any]]:
    """Lit toutes les lignes d'une table SQLite de collection."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        # Colonnes : id, text, embedding, metadata, source, version, ingest_time
        colnames = [desc[0] for desc in conn.execute(f"PRAGMA table_info({table_name})").description]
        results = []
        for row in rows:
            d = dict(zip(colnames, row))
            # Lister embedding JSON → python list si c'est un string
            if isinstance(d.get("embedding"), str):
                try:
                    d["embedding"] = json.loads(d["embedding"])
                except (json.JSONDecodeError, TypeError):
                    d["embedding"] = None
            # metadata_ colonne → dict
            if isinstance(d.get("metadata"), str) or isinstance(d.get("metadata_"), str):
                meta_key = "metadata" if "metadata" in colnames else "metadata_"
                try:
                    d[meta_key] = json.loads(str(d.get(meta_key, "{}")))
                except (json.JSONDecodeError, TypeError):
                    d[meta_key] = {}
            results.append(d)
        return results
    finally:
        conn.close()


def read_operational_tables(db_path: str) -> dict[str, list[dict]]:
    """Lit les tables operationnelles (ingestion_runs, data_coverage, ...)."""
    conn = sqlite3.connect(db_path)
    try:
        all_tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()]

        operational = {}
        # Tables operationnelles connues dans le schema PG
        target_ops = {"ingestion_runs", "data_coverage", "collection_health", "data_links"}
        for t in all_tables:
            if t.startswith("z_") or t not in target_ops:
                continue
            try:
                rows = conn.execute(f"SELECT * FROM {t}").fetchall()
                colnames = [desc[0] for desc in conn.execute(
                    f"PRAGMA table_info({t})"
                ).description]
                operational[t] = [dict(zip(colnames, r)) for r in rows]
            except sqlite3.OperationalError:
                pass
        return operational
    finally:
        conn.close()


# ===========================================================================
# Conversion embeddings SQLite → pgvector format
# ===========================================================================

def _sqlite_emb_to_pgvector(embedding: list[float] | None) -> str | None:
    """Convertit un embedding JSON [0.1, -0.2, ...] en string PG vector literal."""
    if embedding is None:
        return None
    # pgvector accepte '[0.1,-0.2,...]' comme format texte pour vector(768)
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


# ===========================================================================
# Injection PostgreSQL via StorageBackend switch (si PG actif)
# ===========================================================================

def migrate_collections_via_backend(db_path: str, pg_config: dict[str, Any]) -> dict[str, int]:
    """Migration via StorageBackend.switch → PG si active."""
    results = {}

    # Charger le module storage pour detecter si PG est disponible
    try:
        from src.storage.sqlite_storage import (
            _load_storage_config,
            _load_pg_config,  # peut etre absent en fonction de la version
        )
    except ImportError:
        print("[WARN] StorageBackendPG non dispo — utilisation write_chunks SQLite.")
        return results

    # Si PG config existe dans l'environnement, le backend bascule automatiquement
    for key, value in pg_config.items():
        if key == "host":
            os.environ["STORAGE_PG_HOST"] = value
        elif key == "port":
            os.environ["STORAGE_PG_PORT"] = str(value)
        elif key == "db":
            os.environ["STORAGE_PG_DB"] = value
        elif key == "user":
            os.environ["STORAGE_PG_USER"] = value
        elif key == "password":
            os.environ["STORAGE_PG_PASS"] = value

    # Recharger la config avec les variables PG injectees
    try:
        from src.storage.sqlite_storage import StorageBackend

        cfg = _load_storage_config()
        backend = StorageBackend(ollama_url="http://x:11434", config=cfg)

        # Forcer le backend vers PG
        os.environ["STORAGE_BACKEND"] = "postgresql"
        backend2 = StorageBackend(ollama_url="http://x:11434", config=_load_storage_config())

        if not hasattr(backend2, '_ensure_postgres') or backend2._ensure_postgres() is None:
            print("[WARN] PostgreSQL inaccessible — skip injection via Backend.")
            return results

    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Impossible de charger StorageBackend PG: {exc}")
        return results

    return results  # Placeholder — real migration uses direct cursor below


# ===========================================================================
# Injection directe via psycopg2 / asyncpg (preferred)
# ===========================================================================

def migrate_via_cursor(db_path: str, pg_config: dict[str, Any]) -> dict[str, int]:
    """Migration directe via psycopg2 connect/cursor.

    Pour chaque collection SQLite :
      1. Lire les lignes
      2. Mapper le nom de table (z_pz_items → z_pz_items identique dans PG)
      3. INSERT into z_pz_items avec pgvector embedding literal
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        host=pg_config["host"],
        port=pg_config["port"],
        dbname=pg_config["db"],
        user=pg_config["user"],
        password=pg_config["password"],
    )
    conn.autocommit = False

    results: dict[str, int] = {}

    try:
        cursor = conn.cursor()

        # S'assurer que pgvector est active
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()

        collections = list_sqlite_collections(db_path)
        print(f"[INFO] Collections SQLite trouvees ({len(collections)}) : {', '.join(collections)}")

        for table_name in collections:
            rows = read_collection_rows(db_path, table_name)
            if not rows:
                print(f"  [SKIP] {table_name}: vide")
                continue

            collection_name = table_name[2:]  # z_pz_items → pz_items
            pg_table = f"z_{collection_name}"

            # Créer la table PG si elle n'existe pas (sans HNSW avant que les donnees soient inserees)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {pg_table} (
                    chunk_id   TEXT PRIMARY KEY,
                    text       TEXT NOT NULL,
                    embedding  vector(768),
                    metadata_  jsonb DEFAULT '{{}}',
                    source     TEXT,
                    version    TEXT,
                    ingest_time DOUBLE PRECISION
                )
            """)
            conn.commit()

            # Trunc + insert (migrer les donnees entieres)
            cursor.execute(f"TRUNCATE {pg_table} CASCADE")
            conn.commit()

            inserted = 0
            for row in rows:
                chunk_id = str(row.get("id", ""))
                text = str(row.get("text", "") or "").strip()
                if not text:
                    continue

                # Convertir embedding JSON → pgvector literal
                raw_emb = row.get("embedding")
                emb_str = _sqlite_emb_to_pgvector(raw_emb) if isinstance(raw_emb, list) else None

                meta = row.get("metadata", row.get("metadata_", {})) or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}

                source = row.get("source", "") or None
                version = row.get("version") or None
                ingest_time = float(row.get("ingest_time", 0)) or time.time()

                # INSERT avec pgvector cast: '{0.1,-0.2,...}'::vector
                insert_sql = f"""
                    INSERT INTO {pg_table}
                        (chunk_id, text, embedding, metadata_, source, version, ingest_time)
                    VALUES (%s, %s, %s::vector, %s::jsonb, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        text = EXCLUDED.text,
                        embedding = EXCLUDED.embedding,
                        metadata_ = EXCLUDED.metadata_,
                        version = EXCLUDED.version,
                        ingest_time = EXCLUDED.ingest_time
                """

                cursor.execute(insert_sql, (
                    chunk_id,
                    text,
                    emb_str,  # sera cast en ::vector par PG
                    json.dumps(meta, ensure_ascii=False),
                    source,
                    version,
                    ingest_time,
                ))
                inserted += 1

            conn.commit()
            results[table_name] = inserted
            print(f"  [OK] {table_name} → {pg_table}: {inserted} lignes")

        # Tables operationnelles
        op_tables = read_operational_tables(db_path)
        for table_name, rows in op_tables.items():
            if not rows:
                print(f"  [SKIP] oper.{table_name}: vide")
                continue

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id          TEXT PRIMARY KEY,
                    metadata    jsonb DEFAULT '{{}}',
                    text        TEXT,
                    source      TEXT,
                    version     TEXT,
                    ingest_time DOUBLE PRECISION
                )
            """)
            conn.commit()

            cursor.execute(f"TRUNCATE {table_name} CASCADE")
            conn.commit()

            inserted = 0
            for row in rows:
                chunk_id = str(row.get("id", ""))
                if not chunk_id or chunk_id == "None":
                    continue

                meta = row.get("metadata", {}) or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}

                text = str(row.get("text", "") or "")
                source = row.get("source") or ""
                version = row.get("version") or None
                ingest_time = float(row.get("ingest_time", 0)) or time.time()

                insert_sql = f"""
                    INSERT INTO {table_name}
                        (id, metadata, text, source, version, ingest_time)
                    VALUES (%s, %s::jsonb, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        metadata = EXCLUDED.metadata,
                        text = EXCLUDED.text,
                        source = EXCLUDED.source,
                        version = EXCLUDED.version,
                        ingest_time = EXCLUDED.ingest_time
                """

                cursor.execute(insert_sql, (
                    chunk_id,
                    json.dumps(meta, ensure_ascii=False),
                    text,
                    source,
                    version,
                    ingest_time,
                ))
                inserted += 1

            conn.commit()
            results[f"oper.{table_name}"] = inserted
            print(f"  [OK] oper.{table_name}: {inserted} lignes")

        print(f"\n[INFO] Migration terminee: {sum(results.values())} lignes au total")

    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"[ERROR] Migration echouee: {exc}")
        raise
    finally:
        cursor.close()
        conn.close()

    return results


# ===========================================================================
# CLI
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Migrer les donnees SQLite → PostgreSQL/pgvector",
    )
    parser.add_argument(
        "--sqlite",
        type=str,
        default="data/storage/zomboid.db",
        help="Chemin vers la base SQLite source (defaut: data/storage/zomboid.db)",
    )
    parser.add_argument("--pg-host", default=PG_ENV["host"], help="Host PostgreSQL")
    parser.add_argument("--pg-port", type=int, default=PG_ENV["port"], help="Port PostgreSQL")
    parser.add_argument("--pg-db", default=PG_ENV["db"], help="Nom de la base PG")
    parser.add_argument("--pg-user", default=PG_ENV["user"], help="Utilisateur PG")
    parser.add_argument("--pg-pass", default=PG_ENV["password"], help="Mot de passe PG")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lister les collections sans migrer",
    )
    args = parser.parse_args()

    pg_config = {
        "host": args.pg_host,
        "port": args.pg_port,
        "db": args.pg_db,
        "user": args.pg_user,
        "password": args.pg_pass,
    }

    # Pre-requis: psycopg2 installe
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        print("[ERROR] psycopg2 requis. Installer: pip install psycopg2-binary")
        sys.exit(1)

    # Verifier que la base SQLite existe
    if not Path(args.sqlite).exists():
        print(f"[ERROR] Base SQLite inexistante: {args.sqlite}")
        sys.exit(1)

    print(f"[INFO] Source SQLite : {args.sqlite}")
    print(f"[INFO] Target PG     : {pg_config['user']}@{pg_config['host']}:{pg_config['port']}/{pg_config['db']}")

    if args.dry_run:
        collections = list_sqlite_collections(args.sqlite)
        total = 0
        for col in collections:
            rows = read_collection_rows(args.sqlite, col)
            print(f"  {col}: {len(rows)} lignes")
            total += len(rows)
        print(f"\n[INFO] Total: {total} lignes dans {len(collections)} collections")
        return

    results = migrate_via_cursor(args.sqlite, pg_config)
    for table, count in results.items():
        print(f"  → {table}: {count}")

    # Summary
    total = sum(results.values())
    print(f"\n[OK] Migration terminee: {total} lignes migrees vers PostgreSQL")


if __name__ == "__main__":
    main()
