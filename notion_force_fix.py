"""Force fix priorities corrompues en iterant sur tous les items."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

# Forcer les noms de colonnes exacts
title_col = "Name"
phase_col = "Phase"
status_col = "Status"
priority_col = "Priority"

items = client.query_items()
print(f"Total items: {len(items)}")

valid_pri = {"P0", "P1", "P2", "P3"}
fixed = 0
errors = 0
for item in items:
    props = item.get("properties", {})
    pri_prop = props.get(priority_col, {})
    select = pri_prop.get("select") or {}
    if not isinstance(select, dict):
        continue
    pri_name = select.get("name", "")

    if pri_name and pri_name not in valid_pri:
        print(f"  Fixing {pri_name} -> P2 on id={item['id'][:8]}...")
        try:
            client.update_item(
                item["id"],
                extra_props={priority_col: {"select": {"name": "P2"}}},
            )
            fixed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

print(f"\nFixes: {fixed}/{len(items)} | Erreurs: {errors}")

# Also check N/A priorities
na_count = sum(1 for i in items if not (i.get("properties", {}).get(priority_col, {}).get("select") or {}).get("name"))
if na_count:
    print(f"\nItems avec Priority vide: {na_count}")

client.close()
