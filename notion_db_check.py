"""Check DB status options and current values."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

schema = client.get_schema()
props = schema["properties"]

# Show all column types
print("=== Columns ===")
for k, v in props.items():
    t = v["type"]
    extra = ""
    if t == "select":
        opts = v.get("select", {}).get("options", [])
        names = [o["name"] for o in opts]
        extra = f" -> {names}"
    print(f"  {k} ({t}){extra}")

# Check current values used
items = client.query_items()
statuses = set()
phases = set()
sources = set()
priorities = set()
for item in items:
    p = item.get("properties", {})
    s = p.get("Status", {}).get("select") or {}
    statuses.add(s.get("name", ""))
    ph = p.get("Phase", {}).get("select") or {}
    phases.add(ph.get("name", ""))
    src = p.get("Source", {}).get("select") or {}
    sources.add(src.get("name", ""))
    pri = p.get("Priority", {}).get("select") or {}
    priorities.add(pri.get("name", ""))

print(f"\n=== Current values ===")
print(f"  Status:   {statuses}")
print(f"  Phase:    {phases}")
print(f"  Source:   {sources}")
print(f"  Priority: {priorities}")
print(f"  Total:    {len(items)} items")

client.close()
