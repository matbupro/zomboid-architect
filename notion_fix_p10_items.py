"""Corrige les tasks qui ont recu P10 par defaut avec leurs vraies priorites."""

import sys

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

# Mapping par substring dans le nom de la tâche
TASK_FIXES = {
    # Phase 3 — CORE
    "script d'ingestion globale (ingest.py)": "P01",
    # Phase 2 — security cascade
    "cascade d'encodages + quarantaine": "P01",
    # Phase 1 — foundation tasks (terminees, mapping correct)
    "arborescence complete (staging/": "P05",
    "Initialiser le dépot Git du projet": "P06",
    # Phase 4 — MCP tools
    "pz_knowledge_retrieval": "P07",
    "pz_get_item (lookup déterministe par ID)": "P06",
    "agent local (OpenClaw": "P07",
    # Phase 8
    "Brave Search fallback integre dans CLI --search": "P10",  # deja correct
    # Phase 7
    "Dépendances installées : pip install -r ingestor/requirements.txt": "P15",
    # Phase 6
    "patch notes depuis l'historique Git": "P20",
    # Phase 9
    "CLI --file <path> + --dir <path> testes": "P08",
}

items = client.query_items()
priority_col = client._priority_col
title_col = client._title_col

fixed = 0
for item in items:
    pri_prop = item.get("properties", {}).get(priority_col, {})
    pri_name = (pri_prop.get("select") or {}).get("name", "") if isinstance(pri_prop, dict) else "?"

    name_prop = item.get("properties", {}).get(title_col, {})
    name_val = ""
    if isinstance(name_prop, dict):
        blocks = name_prop.get("title", [])
        if blocks:
            name_val = blocks[0].get("text", {}).get("content", "")

    for substring, new_pri in TASK_FIXES.items():
        if substring.lower() in name_val.lower():
            if pri_name != new_pri:
                try:
                    client.update_item(
                        item["id"],
                        extra_props={priority_col: {"select": {"name": new_pri}}},
                    )
                    print(f"  {pri_name:4s} -> {new_pri:4s} | {name_val[:70]}")
                    fixed += 1
                except Exception as e:
                    print(f"  ERREUR sur '{name_val[:40]}': {e}")
            break

print(f"\nCorrections effectuees: {fixed}")

# Verification finale
items2 = client.query_items()
pri_counts = {}
for item in items2:
    pri_prop = item.get("properties", {}).get(priority_col, {})
    pri_name = (pri_prop.get("select") or {}).get("name", "") if isinstance(pri_prop, dict) else "?"
    pri_counts[pri_name] = pri_counts.get(pri_name, 0) + 1

print(f"\n{'='*60}")
print("Distribution finale P01-P20 :")
for k in sorted(k for k in pri_counts):
    bar = "█" * min(pri_counts[k], 40)
    print(f"  {k:4s} | {bar} ({pri_counts[k]})")

client.close()
