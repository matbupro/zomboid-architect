"""Check real Notion page IDs."""
from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

items = client.query_items()
print(f"Total items: {len(items)}")

# Show full IDs of first 3
for item in items[:3]:
    pid = item.get("id", "NO ID")
    props = item.get("properties", {})
    name_raw = ""
    for block in props.get("Name", {}).get("title", []):
        name_raw = block.get("text", {}).get("content", "").strip()

    # Check if it's a real unique page ID or a DB reference
    print(f"  id length: {len(pid)}")
    print(f"  id full: {pid}")
    print(f"  Name: {name_raw}")

# Try to delete one with the API using PATCH (safe way)
print("\n=== Testing delete method ===")
page_id = items[1]["id"] if len(items) > 1 else items[0]["id"]
print(f"Testing DELETE /pages/{page_id}")
try:
    # Notion requires PATCHing page properties to archived=true
    result = client._request("PATCH", f"/pages/{page_id}", json_body={"archived": True})
    print(f"  Result: archived=True → {result.get('archived')}")
except Exception as e:
    print(f"  Error: {e}")

# Let's try a search to see if we can find all items and their real IDs
print("\n=== Search for all items ===")
results = client.search(filter={"property": "object", "value": "page"})
print(f"Search results count: {len(results)}")
for r in results[:3]:
    print(f"  page id={r['id']} type={r.get('object')}, title={r.get('url', '')}")

client.close()
