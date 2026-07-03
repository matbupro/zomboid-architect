"""notion_client/sync.py — Compare agent/todo.md local ↔ Notion et upsert les changements.

Algorithme :
1. parser.parse_todo() → list de Phase/Task locaux
2. client.query_items() → liste des items existants dans Notion
3. Pour chaque tache locale :
   a. Chercher un item Notion correspondant (par texte + phase)
   b. Si trouvee → mettre a jour le statut si different
   c. Sinon → creer un nouvel item
4. Pour chaque item Notion sans match local → marquer comme "skipped" (ne pas supprimer)

Le sync est *idempotent* : relancer deux fois produit le meme resultat.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import api, parser


@dataclass
class SyncAction:
    phase: str       # Phase N : Nom
    task_text: str   # Libelle de la tache
    local_done: bool  # Statut local ([x] ou [ ])
    action: str      # "created" / "updated_status" / "unchanged" / "new_phase"


# Mapping des priorites basees sur les mots-clés dans le texte de la tâche
PRIORITY_KEYWORDS = {
    "P0": {"urgent", "bloquant", "critique", "blocker", "fix", "correction", "crash", "regr"},
    "P1": {"prioritaire", "essentiel", "fondamental", "docker", "readme",
            "golden", "evaluation", "qualite", "recall",
            "integration", "promote", "backup", "securite", "circuit breaker",
            "test unitaire", "chroma_writer", "lock", "engine", "text"},
}


def _detect_priority(task_text: str) -> str:
    """Déduire la priorité du libellé de la tâche (P0→P3)."""
    lower = task_text.lower()
    for priority in ("P0", "P1"):
        keywords = PRIORITY_KEYWORDS[priority]
        if any(kw in lower for kw in keywords):
            return priority
    # Par défaut : P3 (priorité faible — taches de maintenance fine)
    return "P3"


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
    select = prop.get("select") or {}
    if isinstance(select, dict):
        return select.get("name", "") or ""
    return ""


def sync(
    dry_run: bool = False,
    file_path: str | None = None,
) -> list[SyncAction]:
    """Lancer le sync local → Notion et renvoyer la liste des actions.

    Args:
        dry_run: si True, n'envoie aucune requête (affiche juste ce qui serait fait)
        file_path: chemin vers le todo.md (défaut : agent/todo.md)

    Returns:
        Liste de SyncAction décrivant chaque action effectuée
    """
    config = api.get_config()
    client = api.NotionClient(config)

    try:
        # 1. Parse local
        phases = parser.parse_todo(file_path)

        # 2. Récupérer items existants dans Notion
        remote_items = client.query_items()

        # Découvrir les noms de colonnes via le schema dynamique
        title_col = client._title_col
        phase_col = client._phase_col          # peut être None
        status_col = client._status_col         # toujours trouvé (fallback "Status")
        priority_col = client._priority_col    # peut être None

        # Indexer par (nom de phase, texte) pour correspondance rapide
        remote_index: dict[tuple[str, str], dict] = {}
        for item in remote_items:
            props = item.get("properties", {})
            name_val = _extract_text(props.get(title_col, {}))
            phase_val = _extract_select(props.get(phase_col, {})) if phase_col else ""
            if name_val and phase_val:
                remote_index[(phase_val.strip(), name_val.strip())] = item

        # 3. Parcourir les phases et tâches locales
        actions: list[SyncAction] = []
        for phase in phases:
            phase_name = re.sub(r"^\s*Phase\s+\d+\s*:\s*", "", phase.name).strip()

            if not remote_items and not dry_run:
                # Première sync : créer toutes les tâches
                for task in phase.tasks:
                    status = "Done" if task.done else "Not Started"
                    page_id = client.create_item(
                        name=task.text,
                        phase=f"Phase {re.search(r'\d+', phase.name).group()}" if re.search(r'\d+', phase.name) else phase_name,
                        status=status,
                        priority=_detect_priority(task.text),
                    )
                    actions.append(SyncAction(
                        phase=phase.name, task_text=task.text, local_done=task.done, action="created"
                    ))
                continue

            for task in phase.tasks:
                # Chercher un match dans Notion (par texte + approx de nom de phase)
                remote_match = None
                for (r_phase, r_text), item in list(remote_index.items()):
                    if r_text.lower().replace("-", " ").strip() == task.text.lower().replace("-", " ").strip():
                        # Comparaison souple : ignorer la numérotation de phase
                        local_num = re.search(r"Phase\s+(\d+)", phase.name)
                        remote_num = re.search(r"Phase\s+(\d+)", r_phase)
                        if not local_num or not remote_num or local_num.group(1) == remote_num.group(1):
                            remote_match = item
                            break

                if remote_match is None:
                    # Nouvelle tâche : la créer
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
                    # Tâche existante : comparer statut + priorité
                    remote_status = _extract_select(remote_match.get("properties", {}).get(status_col, {}))
                    expected_status = "Done" if task.done else "Not Started"

                    status_changed = remote_status.strip() != expected_status
                    pri_changed = False
                    updates: dict[str, Any] = {}

                    if status_changed:
                        updates[status_col] = {"select": {"name": expected_status}}

                    # Comparer la priorité
                    if priority_col:
                        remote_pri_prop = remote_match.get("properties", {}).get(priority_col, {})
                        remote_pri = _extract_select(remote_pri_prop)
                        expected_pri = _detect_priority(task.text)
                        if remote_pri != expected_pri:
                            pri_changed = True
                            updates[priority_col] = {"select": {"name": expected_pri}}

                    if status_changed or pri_changed:
                        client.update_item(
                            remote_match["id"],
                            extra_props=updates,
                        )
                        action_label = "updated_priority" if not status_changed else ("updated_status" if not pri_changed else "updated_status+pri")
                        actions.append(SyncAction(
                            phase=phase.name, task_text=task.text, local_done=task.done, action=action_label
                        ))
                    else:
                        if dry_run:
                            actions.append(SyncAction(
                                phase=phase.name, task_text=task.text, local_done=task.done, action="unchanged [no change needed]"
                            ))
                        else:
                            actions.append(SyncAction(
                                phase=phase.name, task_text=task.text, local_done=task.done, action="synced"
                            ))

        return actions

    finally:
        client.close()
