#!/usr/bin/env python3
"""notion_sync.py — CLI pour synchroniser agent/todo.md vers Notion.

Usage :
    python notion_sync.py --push          # push les t&#226;ches locales dans Notion
    python notion_sync.py --dry-run       # pr&#233;visualise sans toucher
    python notion_sync.py --schema        # imprime le sch&#233;ma de la DB actuelle
    python notion_sync.py --stats         # stats des phases (total/done/remaining)
"""

import argparse
import json
import re
import sys
from pathlib import Path

# UTF-8 stdout sur Windows (pour █/░ dans les progress bars)
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

# Ajouter le repo root au path pour les imports relatifs
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from notion_client import api, parser, sync


def _print_actions(actions: list[sync.SyncAction]) -> None:
    """Afficher les actions de sync en format lisible."""
    created = [a for a in actions if "created" in a.action or "create" in a.action]
    updated = [a for a in actions if "updated_status" in a.action]
    synced = [a for a in actions if a.action == "synced"]

    print(f"\n{'='*60}")
    print(f"Actions ({len(actions)} t&#226;ches trait&#233;es)")
    print(f"{'='*60}")

    if created:
        print(f"\n  [+ {len(created)} cr&#233;&#233;e(s) :")
        for a in created[:15]:  # max 15 affich&#233;s
            phase_short = re.sub(r"^Phase\s+\d+\s*:\s*", "", a.phase).strip() if hasattr(a, 'phase') else a.phase
            print(f"      - [{a.phase}] {a.task_text[:60]}")
        if len(created) > 15:
            print(f"      ... et {len(created) - 15} autres")

    if updated:
        print(f"\n  [~ {len(updated)} statut mis &#224; jour :")
        for a in updated[:10]:
            phase_short = re.sub(r"^Phase\s+\d+\s*:\s*", "", a.phase).strip() if hasattr(a, 'phase') else a.phase
            print(f"      - [{a.phase}] {a.task_text[:60]}")
        if len(updated) > 10:
            print(f"      ... et {len(updated) - 10} autres")

    if synced:
        print(f"\n  [✓ {len(synced)} d&#233;j&#224; syncronis&#233;(s)")

    if not created and not updated and not synced:
        print("\n  Rien &#224; faire — tout est jour.")


def cmd_push(dry_run: bool = False) -> None:
    """Push les t&#226;ches locales vers Notion."""
    actions = sync.sync(dry_run=dry_run)
    if dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN — ce qui serait fait (aucune modification)")
        print(f"{'='*60}")
        created = [a for a in actions if "create" in a.action]
        updated = [a for a in actions if "updated_status" in a.action or "synced" in a.action]
        unchanged = [a for a in actions if "unchanged" in a.action]
        print(f"  Cr&#233;er       : {len(created)}")
        print(f"  Mettre &#224; jour: {len(updated)}")
        print(f"  Inchang&#233;    : {len(unchanged)}")
    else:
        _print_actions(actions)


def cmd_schema() -> None:
    """Imprimer le sch&#233;ma de la DB Notion."""
    config = api.get_config()
    client = api.NotionClient(config)
    try:
        schema = client.get_schema()
        print(json.dumps(schema, indent=2, ensure_ascii=False))
    finally:
        client.close()


def cmd_create_schema() -> None:
    """Cr&#233;er une nouvelle DB "Zomboid Tasks" si inexistante."""
    config = api.get_config()
    print("\nATTENTION : ce script cr&#233;e la database mais pas les vues.")
    print("Apr&#232;s ex&#233;cution, ouvrir Notion et ajouter manuellement la vue Board Kanban.\n")

    schema = api.NotionClient.create_database_schema()

    # On ne peut pas cr&#233;er une DB directement via l'API -- il faut une page parent
    print("Pour cr&#233;er la database manuellement :")
    print("  1. Ouvrir une page Notion")
    print("  2. Taper /table full")
    print("  3. Configurer les colonnes avec le sch&#233;ma ci-dessous")
    print(f"\n{'='*60}")
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def cmd_stats() -> None:
    """Afficher les stats des phases (total/done/remaining)."""
    todo_path = REPO_ROOT / "agent" / "todo.md"

    if not todo_path.exists():
        print(f"Error: {todo_path} non trouv&#233;", file=sys.stderr)
        sys.exit(1)

    phases = parser.parse_todo(str(todo_path))
    stats = parser.get_total_stats(phases)

    print(f"\n{'='*60}")
    print("Statistiques agent/todo.md")
    print(f"{'='*60}")
    print(f"  Total       : {stats['total']} t&#226;ches")
    print(f"  Termin&#233;es   : {stats['done']}/{stats['total']} ({int(100*stats['done']/max(stats['total'],1))}%)")
    print(f"  En attente   : {stats['remaining']}")

    for phase in phases:
        total = len(phase.tasks)
        done = sum(1 for t in phase.tasks if t.done)
        if total > 0:
            pct = int(100 * done / total)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\n  [{phase.name}]\n    [{bar}] {done}/{total} ({pct}%)")


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Sync agent/todo.md vers Notion.",
        epilog="Exemples:\n"
               "  python notion_sync.py --push\n"
               "  python notion_sync.py --dry-run\n"
               "  python notion_sync.py --schema\n"
               "  python notion_sync.py --stats\n",
    )

    group = arg_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--push", action="store_true", help="Push les t&#226;ches vers Notion")
    group.add_argument("--dry-run", action="store_true", help="Pr&#233;visualiser sans modifier")
    group.add_argument("--schema", action="store_true", help="Imprimer le sch&#233;ma de la DB")
    group.add_argument("--create-schema", action="store_true", help="Afficher le sch&#233;ma pour cr&#233;ation manuelle")
    group.add_argument("--stats", action="store_true", help="Stats des phases dans todo.md")

    args = arg_parser.parse_args()

    if args.push or args.dry_run:
        try:
            cmd_push(dry_run=args.dry_run)
        except RuntimeError as e:
            print(f"Erreur de configuration : {e}", file=sys.stderr)
            sys.exit(1)
    elif args.schema:
        cmd_schema()
    elif args.create_schema:
        cmd_create_schema()
    elif args.stats:
        cmd_stats()


if __name__ == "__main__":
    main()
