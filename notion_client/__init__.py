"""notion_client — Sync agent/todo.md vers une base de données Notion.

Sub-modules :
  notion_client.api    → NotionClient (httpx wrapper), get_config, NotionConfig
  notion_client.parser → parse_todo, format_tasks_as_md, get_total_stats, Task, Phase
  notion_client.sync   → sync(dry_run) → list[SyncAction]
  notion_client.cli    → cmd_push, cmd_stats, main()

Usage CLI :
    python -m notion_client --push          # push les tâches vers Notion
    python -m notion_client --dry-run       # prévisualiser sans modifier
    python -m notion_client --schema        # imprimer le schéma de la DB
    python -m notion_client --stats         # stats des phases

Config : charger les variables depuis .env.unified a la racine du projet (NOTION_API_KEY + NOTION_DATABASE_ID).
"""

__all__ = ["api", "parser", "sync", "cli"]

from .api import NotionClient, get_config, NotionConfig
from .parser import parse_todo, Task, Phase, format_tasks_as_md, get_total_stats
from .sync import sync as sync_remote

__version__ = "1.0.0"
