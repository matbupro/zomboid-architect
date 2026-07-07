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
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import api, parser


# ---------------------------------------------------------------------------
# Normalisation / fuzzy matching pour la correspondance local↔Notion
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Normaliser un texte de tâche pour comparaison fuzzy.

    Etapes :
    1. Decompose accents/accents composes (NFD) → supprime les marques diacritiques
    2. Remplace tirets/em-dashes par des espaces (uniformise "a-b" / "ab" / "a b")
    3. Retire les apostrophes/quotes simples
    4. Collapse espaces multiples + strip
    """
    # Decompose accents (é → e + ́) puis supprime les marques de diacritique
    nfkd = unicodedata.normalize("NFKD", text)
    stripped_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Tirets, em-dashes, en-dashes → espaces
    s = re.sub(r"[–—―\-]", " ", stripped_accents)
    # Apostrophes et quotes droits/gauches -> espace
    s = re.sub(r"\x27", " ", s)
    # Collapse espaces multiples + strip
    return re.sub(r"\s+", " ", s).strip().lower()


def _fuzzy_match(
    local_text: str, remote_texts: list[str], threshold: float = 0.85
) -> str | None:
    """Determiner si une tâche locale correspond à une tâche Notion existante.

    Retourne le texte distant matche (si trouvé), sinon None.

    La comparaison se fait sur des textes normalisés (sans accents, sans ponctuation).
    threshold : seuil de similarité Levenshtein (0.0-1.0). Par défaut 0.85.
    """

    local_norm = _normalize_text(local_text)
    if not local_norm:
        return None

    best_match: str | None = None
    best_score = 0.0

    for remote_text in remote_texts:
        remote_norm = _normalize_text(remote_text)
        if not remote_norm:
            continue

        # Correspondance exacte sur textes normalisés → score maximal
        if local_norm == remote_norm:
            return remote_text

        # Similarité Levenshtein pour les cas approximatifs
        score = _levenshtein_similarity(local_norm, remote_norm)
        if score > best_score:
            best_score = score
            best_match = remote_text

    # On ne retourne un match que si le score dépasse le threshold
    return best_match if best_score >= threshold else None


def _levenshtein_similarity(a: str, b: str) -> float:
    """Calculer la similarité Levenshtein entre deux chaines (0.0-1.0).

    1.0 = identiques, 0.0 = aucune similarite.
    Optimise pour les petites chaines (<500 chars) typiques des libelles de tâches.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    len_a, len_b = len(a), len(b)
    if len_a > len_b:
        a, b = b, a
        len_a, len_b = len_b, len_a

    # Distances de Levenshtein optimisée en memoire (2 colonnes)
    current_row = list(range(len_a + 1))
    for i, char_b in enumerate(b, start=1):
        prev_row = current_row
        current_row = [i] + [0] * len_a
        for j, char_a in enumerate(a, start=1):
            cost = 0 if char_a == char_b else 1
            current_row[j] = min(
                prev_row[j] + 1,      # insertion
                current_row[j - 1] + 1, # suppression
                prev_row[j - 1] + cost, # substitution
            )

    edit_distance = current_row[len_a]
    max_len = max(len_a, len_b)
    return 1.0 - (edit_distance / max_len) if max_len > 0 else 1.0


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
            "test unitaire", "storage_writer", "lock", "engine", "text"},
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
    cleanup_orphans: bool = False,
) -> list[SyncAction]:
    """Lancer le sync local → Notion et renvoyer la liste des actions.

    Args:
        dry_run: si True, n'envoie aucune requête (affiche juste ce qui serait fait)
        file_path: chemin vers le todo.md (défaut : agent/todo.md)
        cleanup_orphans: supprimer les items Notion sans match local (par défaut False → warning only)

    Returns:
        Liste de SyncAction décrivant chaque action effectuée. Les orphelins supprimés
        sont retournés avec action="deleted_orphan" ou action="delete [dry-run]".
    """
    config = api.get_config()
    client = api.NotionClient(config)

    # Collecteur d'orphanes (items non-matches)
    deleted_items: list[str] = []  # IDs supprimés

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

        # Indexer les textes distants par phase pour fuzzy matching (sans le dict item)
        remote_texts_by_phase: dict[str, list[str]] = {}
        for (r_phase, r_text), _ in remote_index.items():
            remote_texts_by_phase.setdefault(r_phase, []).append(r_text)

        # 3. Parcourir les phases et tâches locales
        actions: list[SyncAction] = []
        matched_remote_ids: set[str] = set()  # IDs d'items Notion trouvés par fuzzy match

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
                # Chercher un match dans Notion (par texte normalisé + fuzzy)
                remote_match = None
                # Collecter les textes distants de la phase courante (et phases similaires)
                phase_texts_for_match: list[str] = []
                phase_num_local = re.search(r"Phase\s+(\d+)", phase.name)
                for r_phase, texts in remote_texts_by_phase.items():
                    if _normalize_text(phase_name) in _normalize_text(r_phase):
                        phase_texts_for_match.extend(texts)
                    else:
                        # Comparer numéros de phase pour tolerantiser "Phase 3" vs "Phase 3.5"
                        remote_num = re.search(r"Phase\s+(\d+)", r_phase)
                        if (
                            not phase_num_local
                            or not remote_num
                            or phase_num_local.group(1) == remote_num.group(1)
                        ):
                            phase_texts_for_match.extend(texts)

                # Fuzzy match : si aucun texte dans cette phase, chercher partout
                all_texts = list(remote_index.keys())
                if not phase_texts_for_match:
                    all_texts = [(r, t) for r, t in remote_index.keys()]
                    phase_texts_for_match = [t for _, t in all_texts]

                matched_text = _fuzzy_match(task.text, phase_texts_for_match) if phase_texts_for_match else None
                if matched_text:
                    # Retrouver l'item dans remote_index (parsing de la clé)
                    for (r_phase, r_text), item in remote_index.items():
                        if _normalize_text(r_text) == _normalize_text(matched_text):
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
                    # Match trouvé → tracked via matched_remote_ids pour orphelin detection
                    matched_remote_ids.add(remote_match["id"])

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

        # 4. Orphan cleanup : items Notion sans match local
        orphan_items: list[tuple[str, str]] = []  # (id, text) des orphelins
        for item in remote_items:
            rid = item["id"]
            props = item.get("properties", {})
            rtext = _extract_text(props.get(title_col, {}))
            if rid not in matched_remote_ids and rtext:
                orphan_items.append((rid, rtext))

        if orphan_items:
            if cleanup_orphans:
                if dry_run:
                    for rid, rtext in orphan_items:
                        actions.append(SyncAction(
                            phase="Orphan cleanup", task_text=rtext, local_done=False, action=f"delete [dry-run]"
                        ))
                else:
                    deleted = 0
                    for rid, rtext in orphan_items:
                        try:
                            client._request("DELETE", f"/pages/{rid}")
                            deleted += 1
                            deleted_items.append(rid)
                            actions.append(SyncAction(
                                phase="Orphan cleanup", task_text=rtext, local_done=False, action="deleted_orphan"
                            ))
                        except RuntimeError:
                            pass  # ignore les erreurs de suppression
                    if not dry_run:
                        print(f"\n  [🧹 {deleted} orphelin(s) supprimé(s) de Notion")
            else:
                # Warning : tâches orphelines sans suppression
                for rid, rtext in orphan_items[:5]:
                    actions.append(SyncAction(
                        phase="Orphan warning", task_text=rtext, local_done=False, action=f"orphan [no match — run --cleanup]"
                    ))

        # Cleanup final (si des orphelins ont été supprimés)
        if deleted_items and not dry_run:
            print(f"\n  [🧹 {len(deleted_items)} tâche(s) orpheline(s) supprimée(s) de Notion")
            print("      Pour supprimer automatiquement à chaque sync, utiliser --cleanup flag sur la CLI.")

        return actions

    finally:
        client.close()
