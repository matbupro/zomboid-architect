"""Met à jour le schema de la DB Notion : remplace les options Priority P0-P3 par P01-P20."""

import sys

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from notion_client import api

config = api.get_config()
client = api.NotionClient(config)

# Récupérer le schema actuel
schema = client.get_schema()
props = schema.get("result", {}).get("properties", {}) or schema.get("properties", {})
priority_prop = props.get("Priority", {})
print(f"Schema actuel Priority: {priority_prop}")

# Options P01-P20 avec couleurs en cycle
COLOR_CYCLE = [
    "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "gray"
]

new_options = []
for i in range(1, 21):
    color = COLOR_CYCLE[(i - 1) % len(COLOR_CYCLE)]
    new_options.append({"name": f"P{i:02d}", "color": color})

# Pour modifier le schema : PATCH /databases/{id} avec properties.Priority.select.options
print(f"Options P01-P20 preparees ({len(new_options)} options)")
for opt in new_options[:5]:
    print(f"  {opt['name']} ({opt['color']})")
print(f"  ... et {len(new_options) - 5} autres")

# Patch le schema de la DB
db_id = config.database_id
body = {
    "properties": {
        "Priority": {
            "select": {
                "options": new_options
            }
        }
    }
}
try:
    result = client._request("PATCH", f"/databases/{db_id}", json_body=body)
    print("\nSchema mis a jour ! Nouvelle options de priorité : P01-P20")
except Exception as e:
    print(f"\nErreur lors du patch du schema: {e}")

client.close()
