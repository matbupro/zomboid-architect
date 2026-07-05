# notion_client — Sync todo.md → Notion

Synchronise `agent/todo.md` vers une base de données Notion (création, mise à jour statut/priorité).

## Configuration

```powershell
cd notion_client/
copy .env.notion.example .env.notion
# remplir NOTION_API_KEY et NOTION_DATABASE_ID dans .env.notion
```

## Usage CLI

```powershell
# Via package (recommandé)
python -m notion_client --push           # push tout vers Notion
python -m notion_client --dry-run        # preview sans modifier
python -m notion_client --schema         # schéma DB imprimée
python -m notion_client --stats          # stats phases todo.md

# Via script racine (delegate)
python notion_sync.py --push
```

## Programmable API

```python
from notion_client import parse_todo, sync_remote, NotionClient, get_config

# Parser local
phases = parse_todo()  # lit agent/todo.md

# Sync vers Notion
actions = sync_remote(dry_run=False)
for a in actions:
    print(f"{a.action}: [{a.phase}] {a.task_text}")

# Client direct
config = get_config()
client = NotionClient(config)
items = client.query_items()
```

## Architecture

```
notion_sync.py (root) ───→ notion_client/cli.py  (argparse + cmd functions)
                                          ├──→ notion_client/sync.py  (diff local↔remote)
                                          ├──→ notion_client/parser.py (todo.md → Phase/Task)
                                          ├──→ notion_client/api.py   (NotionClient httpx)
                                          └──→ .env.notion           (secrets)

database/extract_pz.py ← unrelated (PZ file extractor)
```
