"""Fixe priorities corrompues (P4-P20 → P2) dans Notion."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

# Schema dynamique - decouverte des vrais noms de colonnes
title_col = client._title_col
phase_col = client._phase_col
status_col = client._status_col
priority_col = client._priority_col or "Priority"
print(f"Columns: title={title_col!r}, phase={phase_col!r}, status={status_col!r}, priority={priority_col!r}")

items = client.query_items()
valid_priorities = {"P0", "P1", "P2", "P3"}
fixed = 0
for item in items:
    props = item.get("properties", {})
    select = props.get(priority_col, {}).get("select") or {}
    pri_name = select.get("name", "") if isinstance(select, dict) else ""

    if pri_name and pri_name not in valid_priorities:
        print(f"  Fixing {pri_name} → P2 on item id={item['id'][:8]}...")
        try:
            client.update_item(
                item["id"],
                extra_props={priority_col: {"select": {"name": "P2"}}},
            )
            fixed += 1
        except Exception as e:
            print(f"  ERROR: {e}")

print(f"\nPriorites corrigees : {fixed}/{len(items)} items")
client.close()
