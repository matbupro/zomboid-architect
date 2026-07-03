"""Check if the DB is truly empty or still has items."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)
items = client.query_items()
print(f"Items: {len(items)}")
if items:
    for item in items[:3]:
        name_blocks = item.get("properties", {}).get("Name", {}).get("title", [])
        name_val = name_blocks[0]["text"]["content"] if name_blocks else ""
        phase = item.get("properties", {}).get("Phase", {}).get("select", {}).get("name", "")
        status = item.get("properties", {}).get("Status", {}).get("select", {}).get("name", "")
        print(f"  - {name_val[:60]} | Phase: {phase} | Status: {status}")
else:
    print("DB vide — je repousse les 80 tâches...")

client.close()
