"""Nettoyer les doublons dans la DB Notion."""
import sys
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

items = client.query_items()
print(f"Total items avant nettoyage : {len(items)}")

# Group par Nom (tâche) — ignore la phase, garde l'item le plus ancien d'abord
seen: dict[str, str] = {}  # nom -> page_id à garder
to_delete: list[str] = []

for item in items:
    props = item.get("properties", {})
    name_val = ""
    for block in props.get("Name", {}).get("title", []):
        name_val = block.get("text", {}).get("content", "").strip()
    if not name_val:
        continue
    # Normaliser : strip + lowercase pour match fiable
    key = name_val.lower()
    page_id = item["id"]
    if key in seen:
        to_delete.append(page_id)
    else:
        seen[key] = page_id

print(f"Items à supprimer : {len(to_delete)}")
print(f"Items restants : {len(items) - len(to_delete)}")

print(f"\nSuppression automatique de {len(to_delete)} doublons...")
# Supprimer les doublons
success = 0
failures = 0
for page_id in to_delete:
    try:
        client._request("DELETE", f"/pages/{page_id}")
        success += 1
    except Exception as e:
        failures += 1
        print(f"  Erreur {page_id[:8]}... : {e}")

print(f"\nSupprimés : {success}")
if failures:
    print(f"Erreurs : {failures}")

client.close()
