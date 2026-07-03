"""Redistribue manuellement les priorités P0-P5 dans Notion pour toutes les tâches du todo.md.

Mapping basé sur l'impact réel des tâches :
  P0 = Bloquant (rien ne fonctionne sans ça)
  P1 = Critique (fondamental mais pas bloquant immédiat)
  P2 = Important (à faire bientôt, impact direct)
  P3 = Normal (à faire, priorité moyenne)
  P4 = Nice-to-have (amélioration optionnelle)
  P5 = Bonus / documentation future
"""

import re
import sys

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from pathlib import Path
from notion_client import api


# ---------------------------------------------------------------------------
# Mapping manuel des priorités par phase + texte de tâche
# Format: {(phase_num, substring_in_task_text): priority_string}
# Le premier match correspondu gagne. "" = pas de changement.
# ---------------------------------------------------------------------------

PRIORITY_MAP = {
    # ====== Phase 1 : Environnement & Fondations ======
    (1, "Initialiser le dép"): "P3",
    (1, "Créer l'arborescence"): "P3",
    (1, "Fichier VERSION"): "P3",
    (1, "Rédiger CHANGELOG"): "P3",
    (1, "Configurer les hooks"): "P3",
    (1, "fiches de mécaniques"): "P4",  # contenu créatif, non bloquant
    (1, "Documentation technique des UI"): "P4",  # documentation avancee

    # ====== Phase 2 : Parsing & Textualization ======
    (2, "Coder le parseur Dual-Field"): "P0",  # CORE ENGINE — sans parser, rien ne marche
    (2, "Implémenter la cascade d'encodages"): "P0",  # securité/robustesse — bloque tout pipeline
    (2, "Validation Pydantic strict"): "P1",  # integrite des donnees
    (2, "Générer identifiants uniques"): "P1",  # anti-collisions mod

    # ====== Phase 3 : Ingestion ChromaDB ======
    (3, "Coder le script d'ingestion globale"): "P0",  # core pipeline — sans ingest, pas de donnees
    (3, "Injecter objets textualisés"): "P1",  # etape normale du pipeline
    (3, "Injecter recettes"): "P2",  # contenu specifique
    (3, "Implémenter batch adaptatif"): "P1",  # performances — anti-OOM critique pour gros projets
    (3, "Écrire promote.py"): "P1",  # gated release — securite du flux staging->prod
    (3, "Interdire toute écriture directe"): "P2",  # regle de sécurité importante
    (3, "Backup DB + rotation"): "P1",  # securite des donnees

    # ====== Phase 4 : Branchement MCP & Tests Agent ======
    (4, "pz_generate_mod_template"): "P0",  # fonctionnalité core MCP
    (4, "ressources Markdown fixes"): "P1",  # ressources de base
    (4, "Isoler chaque handler MCP"): "P1",  # sécurité du serveur
    (4, "watchdog de redémarrage"): "P2",  # robustesse infra
    (4, "Connecter le serveur à l'agent"): "P0",  # connexion serveur -> client = fonctionnalité viable
    (4, "Test 1 : panique"): "P1",  # validation critique du système
    (4, "Test 2 : générer UI Lua"): "P1",  # validation fonctionnalité clé
    (4, "Test 3 : stats exactes"): "P2",  # validation deterministe

    # ====== Phase 5 : Évaluation & Qualité ======
    (5, "golden set de 25-30"): "P0",  # evaluation = base de toute la qualite
    (5, "Mesurer recall@5"): "P1",  # measurement critique
    (5, "Documenter les scores"): "P2",  # documentation des résultats
    (5, "lier le golden set à promote.py"): "P0",  # gated release = sécurité deployment
    (5, "rapport de version"): "P2",  # reporting post-release

    # ====== Phase 6 : Maintenance & Build 42 ======
    (6, "Filtrage"): "P1",  # maintenance core ChromaDB
    (6, "Mise à jour incrémentale"): "P1",  # performance critique pour re-ingestion
    (6, "Détection de patch cassant"): "P0",  # regression detection = sécurité deployment
    (6, "tag Git annoté"): "P2",  # release management standard
    (6, "patch notes depuis Git"): "P3",  # automatisation nice-to-have

    # ====== Phase 7 : Moteur d'ingestion multi-format ======
    # Toutes terminées — P0/P1/P3 deja assignés
    (7, "Arborescence"): "P0",  # déjà fait
    (7, "Interface Processor.extract"): "P0",  # déjà fait
    (7, "Moteur de détection MIME"): "P0",  # déjà fait
    (7, "ChromaDB writer"): "P1",  # déjà fait
    (7, "Dépendances installes"): "P3",  # already done
    (7, "Playwright"): "P2",  # already done
    (7, "FFmpeg installe"): "P3",  # already done
    (7, "Tesseract OCR"): "P3",  # already done

    # ====== Phase 8 : Web crawling ======
    (8, "Brave Search fallback"): "P1",  # robustesse recherche = important pour CLI
    (8, "Test sur un site reel"): "P2",  # validation avant release

    # ====== Phase 9 : Processeurs multi-format ======
    (9, "CLI --file + --dir testes"): "P1",  # test CLI = verification de la fonctionnalité principale
    (9, "deppr FFmpeg standalone"): "P3",  # already noted as done

    # ====== Phase 10 : Safety + Infrastructure ======
    (10, "Quarantine manager"): "P0",  # sécurité core
    (10, "Circuit breaker anti-crash"): "P0",  # robustesse serveur critique
    (10, "Disk space monitoring"): "P2",  # monitoring utile mais pas bloquant
    (10, "Docker service ingestor"): "P1",  # déploiement standard
    (10, "README ingestor"): "P2",  # documentation infra
    (10, "Tests unitaires processeurs"): "P0",  # qualite core — sans tests, pas de confiance deployment
    (10, "Structure bot"): "P3",  # déjà fait
    (10, "Slash commands"): "P2",  # validation fonctionnalité
    (10, "Mode DM automatique"): "P3",  # déjà fait
    (10, "Dockerfile + docker-compose"): "P1",  # déploiement standard
    (10, "Corrections"): "P3",  # already done
    (10, "Lancement sans Docker"): "P2",  # utilities
    (10, "README bot"): "P2",  # documentation
    (10, "P0 fix"): "P3",  # déjà fait
    (10, "Ollama"): "P3",  # déjà verified online
    (10, "ChromaDB : docker compose"): "P3",  # already up
    (10, "Test du bot"): "P1",  # validation finale avant release

    # ====== Phase 11 : Tests + Evaluation ======
    (11, "golden.json cree"): "P3",  # already done
    (11, "Tests unitaires processeurs critiques"): "P0",  # CORE — critical path avant integration
    (11, "Golden set de 25-30 Q/R + mesure recall@5"): "P0",  # evaluation = base qualite
    (11, "Rapports de qualite"): "P1",  # deliverable qualite important
}


def match_priority(phase_num: int, task_text: str) -> str:
    """Retourner la priorité manuelle pour cette tâche, ou '' si aucun match."""
    for (pn, substring), pri in PRIORITY_MAP.items():
        if pn == phase_num and substring.lower() in task_text.lower():
            return pri
    return ""


def main():
    config = api.get_config()
    client = api.NotionClient(config)

    # Lire le todo.md pour extraire phase_num + task_text
    todo_path = Path(__file__).parent / "agent" / "todo.md"
    if not todo_path.exists():
        todo_path = Path("agent/todo.md")
    text = todo_path.read_text(encoding="utf-8")

    phases = {}  # (phase_num, task_text) -> done
    phase_match = re.compile(r"^##\s+(?:NOUVEAU\s*:?\s+)?(?:PHASE|Phase)\s*(\d+)\s*([:\s—\-]+)(.+)$", re.MULTILINE)
    task_re = re.compile(r"^- \[(.)\] (.+)$", re.MULTILINE)

    current_phase_num = None
    for line in text.splitlines():
        stripped = line.strip()
        pm = phase_match.match(stripped)
        if pm:
            current_phase_num = int(pm.group(1))
            continue
        tm = task_re.match(stripped)
        if tm and current_phase_num is not None:
            char = tm.group(1)
            txt = tm.group(2).strip()
            phases[(current_phase_num, txt)] = (char == "x" or char == "X")

    # Query Notion et mettre à jour les priorités
    items = client.query_items()
    priority_col = client._priority_col
    if not priority_col:
        print("ERREUR : colonne Priority non trouvee dans le schema Notion!")
        return False

    total = 0
    changed = 0
    unchanged = 0
    unmatched = []

    for item in items:
        props = item.get("properties", {})
        name_prop = props.get(client._title_col, {})
        name_val = ""
        if isinstance(name_prop, dict):
            blocks = name_prop.get("title", [])
            if blocks:
                name_val = blocks[0].get("text", {}).get("content", "")

        phase_prop = props.get("Phase", {}).get("select") or {}
        phase_name = phase_prop.get("name", "") if isinstance(phase_prop, dict) else ""

        pri_prop = props.get(priority_col, {})
        old_pri = (pri_prop.get("select") or {}).get("name", "") if isinstance(pri_prop, dict) else "?"

        # Trouver le numéro de phase dans le nom
        m = re.search(r"Phase\s+(\d+)", phase_name)
        phase_num = int(m.group(1)) if m else 0

        new_pri = match_priority(phase_num, name_val)
        total += 1

        if not new_pri:
            unmatched.append((phase_num, name_val[:60]))
            continue

        if old_pri == new_pri:
            unchanged += 1
            continue

        try:
            client.update_item(
                item["id"],
                extra_props={priority_col: {"select": {"name": new_pri}}},
            )
            changed += 1
            print(f"  [{phase_name}] {old_pri} -> {new_pri}: {name_val[:70]}")
        except Exception as e:
            print(f"  ERREUR sur '{name_val[:40]}': {e}")

    print(f"\n{'='*60}")
    print(f"Tâches synchronisées : {total}")
    print(f"Nouvelles priorités : {changed}")
    print(f"Inchangées : {unchanged}")
    if unmatched:
        print(f"Non mappées ({len(unmatched)}) :")
        for pn, txt in unmatched[:10]:
            print(f"  Phase {pn}: {txt[:60]}")

    client.close()
    return True


if __name__ == "__main__":
    main()
