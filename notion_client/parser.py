"""notion_client/parser.py — Parse agent/todo.md et extrait les phases/t&#226;ches.

Formats support&#233;s :
- [x] texte compl&#233;t&#233;
- [ ] texte non-compl&#233;t&#233;
- ## Phase N : Nom   → d&#233;but de section
- ### Sous-phase      → sous-section

Renvoie une liste de phases, chacune contenant ses t&#226;ches avec leur statut.
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    text: str       # libell&#233; de la t&#226;che
    done: bool      # compl&#233;t&#233; ou non


@dataclass
class Phase:
    name: str       # "Phase 1 : Environnement & Fondations"
    tasks: list[Task]


# Regex pour une ligne de t&#226;che Markdown checklist
_CHECKBOX_RE = re.compile(r"^- \[(.)\] (.+)$", re.MULTILINE)


def parse_todo(file_path: str | None = None) -> list[Phase]:
    """Parser agent/todo.md et renvoyer la liste des phases + t&#226;ches.

    Args:
        file_path: chemin vers le fichier todo.md (d&#233;faut : agent/todo.md)

    Returns:
        Liste de Phase(chaine de Task objects)
    """
    if file_path is None:
        # Essayer agent/todo.md relatif au repo root
        candidates = [
            Path(__file__).parents[1] / "agent" / "todo.md",
        ]
        for p in candidates:
            if p.exists():
                file_path = str(p)
                break
        else:
            raise FileNotFoundError(
                "agent/todo.md non trouv&#233;. Passer le chemin explicitement."
            )

    text = Path(file_path).read_text(encoding="utf-8")
    phases: list[Phase] = []
    current_phase: Phase | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        # D&#233;tection d'une nouvelle phase (## PHASE N ou ## NOUVEAU : Phase N)
        # Supporte les formats: "Phase 1 :", "Phase 7 —", "NOUVEAU : Phase 9"
        phase_match = re.match(
            r"^##\s+(?:NOUVEAU\s*:?\s+)?(?:PHASE|Phase)\s*(\d+)\s*([:\s—\-]+)(.+)$", stripped
        )
        if phase_match:
            if current_phase is not None:
                phases.append(current_phase)
            phase_num = int(phase_match.group(1))
            phase_name = phase_match.group(3).strip()
            # Nettoyer les emojis/marqueurs de status (✅ TERMINE, etc.)
            phase_name = re.sub(r"\s*[✓✔✅]+\s*\w*", "", phase_name).strip()
            phase_name = re.sub(r"\s*\(\d{4}[-–]\d{2}\)\s*$", "", phase_name).strip()
            # Ajouter la num&#233;rotation au nom si manquante
            if f"Phase {phase_num} :" not in phase_name and f"Phase {phase_num}-" not in phase_name:
                phase_name = f"Phase {phase_num} : {phase_name}"
            current_phase = Phase(name=phase_name, tasks=[])
            continue

        # Match de t&#226;che checklist
        task_match = _CHECKBOX_RE.match(stripped)
        if task_match and current_phase is not None:
            checkbox_char = task_match.group(1)
            task_text = task_match.group(2).strip()
            done = checkbox_char == "x" or checkbox_char == "X"

            # Nettoyer le texte : enlever les balises de code inline comme *impl&#233;ment&#233;*
            clean_text = re.sub(r"\*([^*]+)\*", r"\1", task_text)
            clean_text = re.sub(r"`([^`]+)`", r"\1", clean_text)
            # Enlever les marqueurs de completion comme "✅ TERMINE"
            clean_text = re.sub(r"\s*[✓✔✅]+\s*$", "", clean_text).strip()

            current_phase.tasks.append(Task(text=clean_text, done=done))

    # Ajouter la derni&#232;re phase si existe
    if current_phase is not None:
        phases.append(current_phase)

    return phases


def format_tasks_as_md(phases: list[Phase]) -> str:
    """Re-g&#233;n&#233;rer le contenu Markdown des phases (utile pour sync backward ou debug)."""
    lines: list[str] = []
    for phase in phases:
        lines.append(f"\n## {phase.name}\n")
        for task in phase.tasks:
            checkbox = "[x]" if task.done else "[ ]"
            lines.append(f"- {checkbox} {task.text}")
    return "\n".join(lines)


def get_total_stats(phases: list[Phase]) -> dict[str, int]:
    """Renvoyer un r&#233;sum&#233; du nombre total de t&#226;ches et compl&#233;t&#233;es."""
    total = sum(len(p.tasks) for p in phases)
    done = sum(1 for p in phases for t in p.tasks if t.done)
    return {"total": total, "done": done, "remaining": total - done}
