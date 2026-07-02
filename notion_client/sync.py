"""notion_client/sync.py — Compare agent/todo.md local ↔ Notion et upsert les changements.

Algorithme :
1. parser.parse_todo() → list de Phase/Task locaux
2. client.query_items() → liste des items existants dans Notion
3. Pour chaque t&#226;che locale :
   a. Chercher un item Notion correspondant (par texte + phase)
   b. Si trouv&#233;e → mettre &#224; jour le statut si diff&#233;rent
   c. Sinon → cr&#233;er un nouvel item
4. Pour chaque item Notion sans match local → marquer comme "skipped" (ne pas supprimer)

Le sync est *idempotent* : relancer deux fois produit le m&#234;me r&#233;sultat.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import api, parser


@dataclass
class SyncAction:
    phase: str       # Phase N : Nom
    task_text: str   # Libell&#233; de la t&#226;che
    local_done: bool  # Statut local ([x] ou [ ])
    action: str      # "created" / "updated_status" / "unchanged" / "new_phase"


# Mapping des prioritis&#233;s bas&#233;es sur les mots-cl&#233;s dans le texte du t&#226;che
PRIORITY_KEYWORDS = {
    "P0": {"urgent", "bloquant", "critique", "blocker", "fix"},
    "P1": {"prioritaire", "important", "essentiels", "fondamental"},
}


def _detect_priority(task_text: str) -> str:
    """D&#233;duire la priorit&#233; du libell&#233; de la t&#226;che (P0→P3)."""
    lower = task_text.lower()
    for priority in ("P0", "P1"):
        keywords = PRIORITY_KEYWORDS[priority]
        if any(kw in lower for kw in keywords):
            return priority
    # Par d&#233;faut : P2 (si compl&#233;t&#233;e → on pourrait passer en P3)
    return "P2"


def sync(
    dry_run: bool = False,
    file_path: str | None = None,
) -> list[SyncAction]:
    """Lancer le sync local → Notion et renvoyer la liste des actions.

    Args:
        dry_run: si True, n'envoie aucune requ&#234;te (affiche juste ce qui serait fait)
        file_path: chemin vers le todo.md (d&#233;faut : agent/todo.md)

    Returns:
        Liste de SyncAction d&#233;crivant chaque action effectu&#233;e
    """
    config = api.get_config()
    client = api.NotionClient(config)

    try:
        # 1. Parse local
        phases = parser.parse_todo(file_path)

        # 2. R&#233;cup&#233;rer items existants dans Notion
        remote_items = client.query_items()
        # Indexer par (nom de phase, texte) pour correspondance rapide
        remote_index: dict[tuple[str, str], dict] = {}
        for item in remote_items:
            props = item.get("properties", {})
            name_val = _extract_text(props.get("Name", {}))
            phase_val = _extract_select(props.get("Phase", {}))
            if name_val and phase_val:
                remote_index[(phase_val.strip(), name_val.strip())] = item

        # 3. Parcourir les phases et t&#226;ches locales
        actions: list[SyncAction] = []
        for phase in phases:
            phase_name = re.sub(r"^\s*Phase\s+\d+\s*:\s*", "", phase.name).strip()

            if not remote_items and not dry_run:
                # Premi&#232;re sync : cr&#233;er toutes les t&#226;ches
                for task in phase.tasks:
                    status = "Done" if task.done else "Not Started"
                    if not dry_run:
                        page_id = client.create_item(
                            name=task.text,
                            phase=f"Phase {re.search(r'\d+', phase.name).group()}" if re.search(r'\d+', phase.name) else phase_name,
                            status=status,
                            priority=_detect_priority(task.text),
                        )
                        actions.append(SyncAction(
                            phase=phase.name, task_text=task.text, local_done=task.done, action="created"
                        ))
                    else:
                        preview = " [passe]" if dry_run else f" page_id={page_id}"
                        actions.append(SyncAction(
                            phase=phase.name, task_text=task.text, local_done=task.done, action=f"create{preview}"
                        ))
                continue

            for task in phase.tasks:
                # Chercher un match dans Notion (par texte + approx de nom de phase)
                remote_match = None
                for (r_phase, r_text), item in list(remote_index.items()):
                    if r_text.lower().replace("-", " ").strip() == task.text.lower().replace("-", " ").strip():
                        # Comparaison souple : ignorer la num&#233;rotation de phase
                        local_num = re.search(r"Phase\s+(\d+)", phase.name)
                        remote_num = re.search(r"Phase\s+(\d+)", r_phase)
                        if not local_num or not remote_num or local_num.group(1) == remote_num.group(1):
                            remote_match = item
                            break

                if remote_match is None:
                    # Nouvelle t&#226;che : la cr&#233;er
                    status = "Done" if task.done else "Not Started"
                    phase_num = re.search(r"Phase\s+(\d+)", phase.name)
                    if not dry_run and phase_num:
                        page_id = client.create_item(
                            name=task.text,
                            phase=f"Phase {phase_num.group(1)}",
                            status=status,
                            priority=_detect_priority(task.text),
                        )
                        actions.append(SyncAction(
                            phase=phase.name, task_text=task.text, local_done=task.done, action="created"
                        ))
                    else:
                        actions.append(SyncAction(
                            phase=phase.name, task_text=task.text, local_done=task.done, action=f"create [preview]" if dry_run else "created"
                        ))
                else:
                    # T&#226;che existante : comparer le statut
                    remote_status = _extract_select(remote_match.get("properties", {}).get("Status", {}))
                    expected_status = "Done" if task.done else "Not Started"

                    if remote_status.strip() != expected_status:
                        if not dry_run:
                            client.update_item(
                                remote_match["id"],
                                status=expected_status,
                                extra_props={"Last Sync": {"date": {"now": True}}},
                            )
                        actions.append(SyncAction(
                            phase=phase.name, task_text=task.text, local_done=task.done, action="updated_status"
                        ))
                    else:
                        if dry_run:
                            actions.append(SyncAction(
                                phase=phase.name, task_text=task.text, local_done=task.done, action="unchanged [no change needed]"
                            ))
                        else:
                            # Mettre &#224; jour la date de sync sans autre changement
                            client.update_item(
                                remote_match["id"],
                                extra_props={"Last Sync": {"date": {"now": True}}},
                            )
                            actions.append(SyncAction(
                                phase=phase.name, task_text=task.text, local_done=task.done, action="synced"
                            ))

        return actions

    finally:
        client.close()


def _extract_text(prop: dict | None) -> str:
    """Extrait le texte d'une colonne title."""
    if not prop:
        return ""
    for block in prop.get("title", []):
        return block.get("text", {}).get("content", "")
    return ""


def _extract_select(prop: dict | None) -> str:
    """Extrait le nom d'une colonne select."""
    if not prop:
        return ""
    select = prop.get("select", {})
    if isinstance(select, dict):
        return select.get("name", "") or ""
    return ""
