#!/usr/bin/env python3
"""CLI entry-point — délégue vers notion_client.cli.main().

Usage :
    python notion_sync.py --push          # push les tâches vers Notion
    python notion_sync.py --dry-run       # prévisualiser sans modifier
    python notion_sync.py --schema        # imprimer le schéma de la DB
    python notion_sync.py --stats         # stats des phases
"""

from notion_client.cli import main
main()
