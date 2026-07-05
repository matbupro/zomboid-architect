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

## 🔒 Sécurité

### Gestion des secrets

- **`.env.notion` est PRIVÉ** : jamais committe (voir `.gitignore`)
- **`.env.notion.example` est PUBLIC** : template à jour dans Git pour l'onboarding
- **En cas de fuite du token** :
  1. Aller sur https://notion.so/my-integrations
  2. Cliquer sur l'intégration affectée
  3. Régénérer le token immédiatement
  4. Mettre à jour `.env.notion` localement
  5. Vérifier l'historique Git si le fichier a été commité

### Contrôle d'accès Notion

L'intégration Notion doit avoir **permissions minimales** :
- ✅ Lecture/Écriture sur la database spécifique uniquement
- ❌ Pas d'accès à d'autres pages / workspaces
- ❌ Pas d'accès Admin workspace-wide

Pour plus de détails, voir [GOVERNANCE.md](GOVERNANCE.md).

## Architecture

```
notion_sync.py (root) ───→ notion_client/cli.py  (argparse + cmd functions)
                                          ├──→ notion_client/sync.py  (diff local↔remote)
                                          ├──→ notion_client/parser.py (todo.md → Phase/Task)
                                          ├──→ notion_client/api.py   (NotionClient httpx)
                                          └──→ .env.notion           (secrets)

database/extract_pz.py ← unrelated (PZ file extractor)
```
