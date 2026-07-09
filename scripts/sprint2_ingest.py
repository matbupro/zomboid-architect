#!/usr/bin/env python3
"""Sprint 2: Data absorption fix. Bypass StorageWriter embedding pipeline, write directly to PG via psycopg2.

Fixes the gap between what was parsed and what actually landed in PG:
- pz_items: 201 claimed vs real (need to re-ingest all native game data)
- pz_recipes: 12 claimed vs real
- pz_mechanics: 69 claimed vs real
- pz_lua_api: need all 1369+ Lua files parsed and written
- pz_java_api: TABLE DOES NOT EXIST - create it
- z_pz_mods: TABLE DOES NOT EXIST - create it
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg2

# Config
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_DB = "zomboid_storage_test"
PG_USER = "postgres"
PG_PASS = "270990"

GAME_LUA_DIR = Path("f:/Games/Steam/steamapps/common/ProjectZomboid/media/lua")


def get_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS
    )


def ensure_table(conn, table_name):
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            chunk_id  TEXT PRIMARY KEY,
            text      TEXT NOT NULL,
            embedding TEXT DEFAULT NULL,
            metadata_ JSONB DEFAULT '{{}}',
            source    TEXT,
            game_version TEXT DEFAULT 'Build 42.19',
            ingest_time DOUBLE PRECISION
        )
    """)
    conn.commit()


def write_chunks_direct(conn, table_name, chunks):
    """Write chunks directly to PG without embedding."""
    cur = conn.cursor()
    written = 0
    for chunk_id, text, meta in chunks:
        try:
            meta_json = json.dumps(meta, ensure_ascii=False)
            cur.execute(f"""
                INSERT INTO {table_name} (chunk_id, text, embedding, metadata_, source, game_version, ingest_time)
                VALUES (%s, %s, NULL, %s, %s, 'Build 42.19', EXTRACT(EPOCH FROM NOW()))
                ON CONFLICT(chunk_id) DO NOTHING
            """, (chunk_id, text[:50000], meta_json, meta.get("source", "manual")))
            written += cur.rowcount
        except Exception as e:
            print(f"    [err] {chunk_id[:30]}: {e}")
    conn.commit()
    return written


def get_table_count(conn, table_name):
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cur.fetchone()[0]
    except Exception:
        return -1


# Phase 1: Create missing tables
def phase1_create_tables():
    print("\n" + "=" * 60)
    print("PHASE 1: Create missing PG tables")
    print("=" * 60)

    conn = get_conn()
    ensure_table(conn, "z_pz_java_api")
    ensure_table(conn, "z_pz_mods")

    for tbl in ["z_pz_java_api", "z_pz_mods"]:
        cnt = get_table_count(conn, tbl)
        print(f"  {tbl}: {cnt} rows")

    conn.close()


# Phase 2: Parse ALL Lua files and write directly to PG
@dataclass
class ApiEntry:
    name: str
    api_type: str
    module: str
    source_file: str
    signature: str
    description: str
    fields: list


def parse_lua_file(file_path):
    entries = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return entries

    rel_path = str(file_path.relative_to(GAME_LUA_DIR))
    module_parts = str(file_path.parent).split(os.sep)
    module = module_parts[-3] if len(module_parts) >= 3 else "unknown"

    for match in re.finditer(r'^(\w+)\s*=\s*\{', content, re.MULTILINE):
        class_name = match.group(1)
        block_content = content[match.end():min(match.end() + 5000, len(content))]
        fields = re.findall(r'^\s+(\w+)\s*=', block_content, re.MULTILINE)
        fields = [f for f in fields if not f.startswith('_')]

        desc = ""
        comment_area = content[max(0, match.start() - 300):match.start()]
        doc_match = re.search(r'--\s*(.*?)(?:\n|$)', comment_area[-200:], re.DOTALL)
        if doc_match:
            desc = doc_match.group(1).strip()[:200]

        entries.append(ApiEntry(class_name, "class", module, str(file_path.relative_to(GAME_LUA_DIR)),
                                f"class {class_name} = {{}}", desc, fields[:20]))

    for match in re.finditer(r'^function\s+(\w+)(\([^)]*\))?', content, re.MULTILINE):
        func_name = match.group(1)
        if func_name.startswith('_') or func_name in ('require', 'print', 'pairs', 'ipairs', 'next', 'type'):
            continue
        desc = ""
        comment_area = content[max(0, match.start() - 300):match.start()]
        doc_match = re.search(r'--\s*(.*?)(?:\n|$)', comment_area[-200:], re.DOTALL)
        if doc_match:
            desc = doc_match.group(1).strip()[:200]
        sig = match.group(2) or ""
        entries.append(ApiEntry(func_name, "function", module, str(file_path.relative_to(GAME_LUA_DIR)),
                                f"function {func_name}{sig}", desc, []))

    already_names = {e.name for e in entries}
    for match in re.finditer(r'^(\w+)\s*=\s*(.+)$', content, re.MULTILINE):
        var_name = match.group(1)
        var_value = match.group(2).strip().rstrip(',')
        if var_name.startswith('_') or var_name in ('require', 'pairs', 'ipairs', 'print'):
            continue
        if var_name in already_names:
            continue
        if len(var_value) > 200:
            continue
        vtype = "variable" if '=' in var_value else "constant"
        entries.append(ApiEntry(var_name, vtype, module, str(file_path.relative_to(GAME_LUA_DIR)),
                                f"{var_name} = {var_value[:100]}", "", []))

    return entries


def phase2_ingest_lua_api():
    print("\n" + "=" * 60)
    print("PHASE 2: Ingest ALL Lua API entries -> pz_lua_api")
    print("=" * 60)

    if not GAME_LUA_DIR.exists():
        print(f"[ERR] Game Lua dir not found: {GAME_LUA_DIR}")
        return {}

    lua_files = sorted(GAME_LUA_DIR.rglob("*.lua"))
    total_files = len(lua_files)
    print(f"\nFound {total_files} Lua files in {GAME_LUA_DIR}")

    all_entries = []
    parsed_files = 0
    for i, fp in enumerate(lua_files):
        entries = parse_lua_file(fp)
        if entries:
            all_entries.extend(entries)
            parsed_files += 1
        if (i + 1) % 200 == 0 or i == total_files - 1:
            print(f"  Parsed {i+1}/{total_files} files -> {len(all_entries)} entries")

    by_type = {}
    for e in all_entries:
        by_type[e.api_type] = by_type.get(e.api_type, 0) + 1

    by_mod = {}
    for e in all_entries:
        by_mod[e.module] = by_mod.get(e.module, 0) + 1

    print(f"\nTotal entries: {len(all_entries)}")
    print(f"Parsed files: {parsed_files}/{total_files}")
    print(f"By type: {by_type}")
    print(f"By module: {by_mod}")

    conn = get_conn()
    ensure_table(conn, "z_pz_lua_api")

    chunks_to_write = []
    seen_ids = set()
    for entry in all_entries:
        lines = [f"API ENTRY ({entry.api_type}): {entry.name}"]
        if entry.signature:
            lines.append(f"  Signature: {entry.signature}")
        if entry.description:
            lines.append(f"  Description: {entry.description[:150]}")
        if entry.fields:
            lines.append(f"  Fields ({len(entry.fields)}): {', '.join(entry.fields[:8])}")
        lines.append(f"\nSource: {entry.source_file}")
        lines.append(f"Module: {entry.module}")

        chunk_id = f"lua_api::{abs(hash(entry.name + entry.module)) % (10**9)}"
        if chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)

        meta = {
            "type": entry.api_type,
            "module": entry.module,
            "source_file": entry.source_file,
            "entry_name": entry.name[:100],
            "collection": "pz_lua_api",
            "content_type": "text/lua",
        }
        chunks_to_write.append((chunk_id, "\n".join(lines), meta))

    written = write_chunks_direct(conn, "z_pz_lua_api", chunks_to_write)
    conn.close()

    conn = get_conn()
    final_count = get_table_count(conn, "z_pz_lua_api")
    conn.close()

    print(f"\n[RESULT] Written {written} new entries (total now: {final_count})")
    return {
        "files_found": total_files,
        "files_parsed": parsed_files,
        "entries": len(all_entries),
        "written": written,
        "by_type": by_type,
        "by_module": by_mod,
        "total_pz_lua_api": final_count,
    }


# Phase 3: Re-ingest native game data (items, recipes, mechanics) from generated/
def phase3_ingest_native_data():
    print("\n" + "=" * 60)
    print("PHASE 3: Ingest native game scripts -> pg")
    print("=" * 60)

    generated_dir = Path("f:/Games/Steam/steamapps/common/ProjectZomboid/media/scripts/generated")
    if not generated_dir.exists():
        print("[ERR] media/scripts/generated dir not found")
        return {}

    # Walk through all subdirs
    items_chunks = []
    recipes_chunks = []
    mechanics_chunks = []

    item_count = 0
    recipe_count = 0
    mech_count = 0

    for root, dirs, files in os.walk(generated_dir):
        for fname in files:
            if not (fname.endswith('.lua') or fname.endswith('.txt')):
                continue
            fpath = Path(root) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = str(fpath.relative_to(generated_dir))
            chunk_id = f"native::{abs(hash(str(fpath))) % (10**9)}"

            if "items" in rel_path or "vehicles" in rel_path or "entities" in rel_path:
                items_chunks.append((chunk_id, content[:50000], {
                    "type": "native_game_data", "path": rel_path,
                    "collection": "pz_items", "content_type": "text/lua" if fname.endswith('.lua') else "text/plain",
                }))
                item_count += 1
            elif "recipes" in rel_path:
                recipes_chunks.append((chunk_id, content[:50000], {
                    "type": "native_recipe", "path": rel_path,
                    "collection": "pz_recipes", "content_type": "text/lua" if fname.endswith('.lua') else "text/plain",
                }))
                recipe_count += 1
            elif any(k in rel_path for k in ["sounds", "characters", "physics", "biome", "farming"]):
                mechanics_chunks.append((chunk_id, content[:50000], {
                    "type": "native_mechanic", "path": rel_path,
                    "collection": "pz_mechanics", "content_type": "text/lua" if fname.endswith('.lua') else "text/plain",
                }))
                mech_count += 1

    print(f"\nDiscovered on disk:")
    print(f"  Items data: {item_count} files")
    print(f"  Recipes data: {recipe_count} files")
    print(f"  Mechanics data: {mech_count} files")

    conn = get_conn()
    for tbl in ["z_pz_items", "z_pz_recipes", "z_pz_mechanics"]:
        ensure_table(conn, tbl)

    items_written = write_chunks_direct(conn, "z_pz_items", items_chunks)
    recipes_written = write_chunks_direct(conn, "z_pz_recipes", recipes_chunks)
    mechanics_written = write_chunks_direct(conn, "z_pz_mechanics", mechanics_chunks)
    conn.close()

    conn = get_conn()
    for tbl_name in ["z_pz_items", "z_pz_recipes", "z_pz_mechanics"]:
        cnt = get_table_count(conn, tbl_name)
        print(f"  {tbl_name}: {cnt} rows total")
    conn.close()

    return {
        "files_discovered": item_count + recipe_count + mech_count,
        "items_written": items_written,
        "recipes_written": recipes_written,
        "mechanics_written": mechanics_written,
    }


# Main
if __name__ == "__main__":
    print("Sprint 2 - Data Absorption Fix")
    print("Bypass StorageWriter embedding pipeline -> direct PG writes\n")

    phase1_create_tables()
    lua_result = phase2_ingest_lua_api()
    native_result = phase3_ingest_native_data()

    conn = get_conn()
    cur = conn.cursor()
    print("\n" + "=" * 60)
    print("FINAL PG STATE")
    print("=" * 60)
    for t in ["pz_items", "pz_recipes", "pz_mechanics", "pz_lua_api", "pz_java_api", "pz_web_pages", "pz_mods"]:
        try:
            cur.execute(f'SELECT COUNT(*) FROM z_{t}')
            cnt = cur.fetchone()[0]
            print(f"  z_{t}: {cnt} rows")
        except Exception as e:
            print(f"  z_{t}: ERROR - {e}")
    conn.close()
