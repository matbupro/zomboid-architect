"""Diagnostic Notion DB state."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

schema = client.get_schema()
print("Schema columns:")
for k, v in schema["properties"].items():
    print(f"  {k} : type={v['type']}")

items = client.query_items()
print(f"\nTotal items: {len(items)}")

# Sample first 10 items
for i, item in enumerate(items[:10]):
    props = item.get("properties", {})
    name_raw = props.get("Nom", {}).get("title", [{}])[0].get("text", {}).get("content", "")
    phase_raw = props.get("Phase", {}).get("select", {}).get("name", "") if isinstance(props.get("Phase", {}).get("select"), dict) else ""
    status_raw = props.get("Status", {}).get("select", {}).get("name", "") if isinstance(props.get("Status", {}).get("select"), dict) else ""
    print(f"  [{i+1}] id={item['id'][:8]} | Nom={name_raw!r} | Phase={phase_raw!r} | Status={status_raw!r}")

# Check for empty names
empty_count = sum(1 for item in items if not item.get("properties", {}).get("Nom", {}).get("title"))
print(f"\nItems with empty title: {empty_count}/{len(items)}")

client.close()
