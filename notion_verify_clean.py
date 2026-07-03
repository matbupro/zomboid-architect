"""Vérification directe de l'état des priorités."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

items = client.query_items()
print(f"Total: {len(items)} items")

# Check each item's Priority directly
pri_vals = set()
empty_pri = 0
for i, item in enumerate(items):
    props = item.get("properties", {})
    pri_prop = props.get("Priority", {})
    select = pri_prop.get("select") or {}
    if not isinstance(select, dict):
        empty_pri += 1
        continue
    name = select.get("name", "")
    pri_vals.add(name)

print(f"Valeurs Priority uniques: {sorted(pri_vals)}")
print(f"Items avec Priority vide: {empty_pri}")

client.close()
