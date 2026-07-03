from notion_client import api

config = api.get_config()
client = api.NotionClient(config)
items = client.query_items()

archived = [i for i in items if i.get("archived", False)]
active = [i for i in items if not i.get("archived", False)]

print(f"Total: {len(items)}")
print(f"Archivés: {len(archived)}")
print(f"Actifs: {len(active)}")

# Show a sample
if active:
    p = active[0].get("properties", {})
    name_blocks = p.get("Name", {}).get("title", [])
    name_val = name_blocks[0]["text"]["content"] if name_blocks else ""
    print(f"Premier actif: {name_val}")

# Show schema properties again
schema = client.get_schema()
print(f"\nSchema columns: {list(schema['properties'].keys())}")
client.close()
