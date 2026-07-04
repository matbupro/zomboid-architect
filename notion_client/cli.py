"""notion_client/cli.py — CLI functions pour la synchronisation todo.md → Notion.

Exporte :
  cmd_push(dry_run)   → actions de sync
  cmd_schema()        → schéma DB imprimée
  cmd_create_schema() → instructions création DB
  cmd_stats()         → stats phases depuis agent/todo.md
  main()              → point d'entrée argparse
"""

import argparse
import json
import re
import sys
from pathlib import Path

from . import api, parser, sync

# Chemin vers agent/todo.md relatif au repo root
REPO_ROOT = Path(__file__).resolve().parent.parent


def _print_actions(actions: list[sync.SyncAction]) -> None:
    """Afficher les actions de sync en format lisible."""
    created = [a for a in actions if "created" in a.action or "create" in a.action]
    updated = [a for a in actions if "updated_status" in a.action]
    synced = [a for a in actions if a.action == "synced"]

    print(f"\n{'='*60}")
    print(f"Actions ({len(actions)} tâches traitées)")
    print(f"{'='*60}")

    if created:
        print(f"\n  [+ {len(created)} créée(s) :")
        for a in created[:15]:
            phase_short = re.sub(r"^Phase\s+\d+\s*:\s*", "", a.phase).strip() if hasattr(a, 'phase') else a.phase
            print(f"      - [{a.phase}] {a.task_text[:60]}")
        if len(created) > 15:
            print(f"      ... et {len(created) - 15} autres")

    if updated:
        print(f"\n  [~ {len(updated)} statut mis à jour :")
        for a in updated[:10]:
            phase_short = re.sub(r"^Phase\s+\d+\s*:\s*", "", a.phase).strip() if hasattr(a, 'phase') else a.phase
            print(f"      - [{a.phase}] {a.task_text[:60]}")
        if len(updated) > 10:
            print(f"      ... et {len(updated) - 10} autres")

    if synced:
        print(f"\n  [✓ {len(synced)} déjà synchronisé(es)")

    if not created and not updated and not synced:
        print("\n  Rien à faire — tout est jour.")


def cmd_push(dry_run: bool = False) -> list[sync.SyncAction]:
    """Push les tâches locales vers Notion."""
    actions = sync.sync(dry_run=dry_run)
    if dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN — ce qui serait fait (aucune modification)")
        print(f"{'='*60}")
        created = [a for a in actions if "create" in a.action]
        updated = [a for a in actions if "updated_status" in a.action or "synced" in a.action]
        unchanged = [a for a in actions if "unchanged" in a.action]
        print(f"  Créer       : {len(created)}")
        print(f"  Mettre à jour: {len(updated)}")
        print(f"  Inchangé    : {len(unchanged)}")
    else:
        _print_actions(actions)
    return actions


def cmd_schema() -> None:
    """Imprimer le schéma de la DB Notion."""
    config = api.get_config()
    client = api.NotionClient(config)
    try:
        schema = client.get_schema()
        print(json.dumps(schema, indent=2, ensure_ascii=False))
    finally:
        client.close()


def cmd_create_schema() -> None:
    """Afficher les instructions pour créer une nouvelle DB Zomboid Tasks."""
    config = api.get_config()
    print("\nATTENTION : ce script crée la database mais pas les vues.")
    print("Après exécution, ouvrir Notion et ajouter manuellement la vue Board Kanban.\n")

    schema = api.NotionClient.create_database_schema()

    print("Pour créer la database manuellement :")
    print("  1. Ouvrir une page Notion")
    print("  2. Taper /table full")
    print("  3. Configurer les colonnes avec le schéma ci-dessous")
    print(f"\n{'='*60}")
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def cmd_stats() -> None:
    """Afficher les stats des phases (total/done/remaining) depuis agent/todo.md."""
    todo_path = REPO_ROOT / "agent" / "todo.md"

    if not todo_path.exists():
        print(f"Error: {todo_path} non trouvée", file=sys.stderr)
        sys.exit(1)

    phases = parser.parse_todo(str(todo_path))
    stats = parser.get_total_stats(phases)

    print(f"\n{'='*60}")
    print("Statistiques agent/todo.md")
    print(f"{'='*60}")
    print(f"  Total       : {stats['total']} tâches")
    print(f"  Terminées   : {stats['done']}/{stats['total']} ({int(100*stats['done']/max(stats['total'],1))}%)")
    print(f"  En attente   : {stats['remaining']}")

    for phase in phases:
        total = len(phase.tasks)
        done = sum(1 for t in phase.tasks if t.done)
        if total > 0:
            pct = int(100 * done / total)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\n  [{phase.name}]\n    [{bar}] {done}/{total} ({pct}%)")


def main() -> None:
    """Point d'entrée argparse — usage : python -m notion_client [--push | --stats | ...]"""

    # UTF-8 stdout sur Windows (pour █/░ dans les progress bars)
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")

    arg_parser = argparse.ArgumentParser(
        description="Sync agent/todo.md vers Notion.",
        epilog="Exemples:\n"
               "  python -m notion_client --push\n"
               "  python -m notion_client --dry-run\n"
               "  python -m notion_client --schema\n"
               "  python -m notion_client --stats\n",
    )

    group = arg_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--push", action="store_true", help="Push les tâches vers Notion")
    group.add_argument("--dry-run", action="store_true", help="Prévisualiser sans modifier")
    group.add_argument("--schema", action="store_true", help="Imprimer le schéma de la DB")
    group.add_argument("--create-schema", action="store_true", help="Afficher le schéma pour création manuelle")
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
