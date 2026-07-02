"""notion_client — Sync agent/todo.md vers une base de donn&#233;es Notion.

Flux :
    parse     → lit agent/todo.md et extrait les phases/t&#226;ches
    sync      compare local vs remote, upsert les items manquants
    push      cr&#233;e ou met &#224; jour chaque t&#226;che dans Notion

Usage :
    python notion_sync.py --push          # push tout vers Notion
    python notion_sync.py --dry-run       # montre ce qui changera sans toucher
    python notion_sync.py --schema        # imprime le sch&#233;ma de la DB actuelle
    python notion_sync.py --create-schema # cr&#233;e une DB "Zomboid Tasks" avec le bon sch&#233;ma

Config : charger notion_client/.env.notion (variables NOTION_API_KEY + NOTION_DATABASE_ID).
        Un template est disponible dans .env.notion.example.
"""

__all__ = ["api", "parser", "sync"]
