"""Redistribue toutes les tâches sur l'échelle P01-P20 et met à jour Notion.

Échelle :
  P01 = Bloquant absolu (rien ne fonctionne sans ça)
  P02-P05 = Critique infrastructure / noyau du projet
  P06-P10 = Important — à faire avant release stable
  P11-P15 = Normal — fonctionnalités utiles, impact modéré
  P16-P20 = Nice-to-have / documentation / bonus
"""

import re
import sys

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

from pathlib import Path
from notion_client import api


# Mapping manuel : {(phase_num, substring): priority_xx}
# Le premier match gagne. Les sous-chaînes sont ordonnées par précision.
PRIORITY_P20_MAP = {
    # ====== Phase 1 : Environnement & Fondations (tâches terminees — mais mapping pour info) ======
    # Toutes ces tâches sont faites [x], on les laisse à leur priorité actuelle ou on mappe proprement
    (1, "Créer l'arborescence complete"): "P05",  # fondation base du projet
    (1, "Initialiser le dépot Git"): "P06",  # versioning standard
    (1, "Fichier VERSION"): "P12",  # convention standard
    (1, "Rédiger CHANGELOG"): "P15",  # documentation
    (1, "Configurer les hooks"): "P18",  # automatisation nice-to-have
    (1, "fiches de mécaniques Markdown"): "P19",  # contenu créatif non bloquant
    (1, "Documentation technique des UI"): "P20",  # documentation avancee

    # ====== Phase 2 : Parsing & Textualization (tous non faits) ======
    (2, "parseur Dual-Field"): "P02",  # CORE — sans parseur, pas de données du tout
    (2, "cascade d'encodages"): "P01",  # sécurité encodage = plus critique que le parseur
    (2, "Validation Pydantic strict"): "P06",  # integrite donnees important mais pas bloquant immédiat
    (2, "identifiants uniques complexes"): "P07",  # anti-collisions nécessaire pour production

    # ====== Phase 3 : Ingestion ChromaDB (tous non faits) ======
    (3, "script d'ingestion globale"): "P01",  # CORE — sans ingest, pas de pipeline
    (3, "Injecter objets textualisés"): "P03",  # etape directe du pipeline core
    (3, "batch adaptatif + checkpoints"): "P06",  # performances critique gros volumes
    (3, "Écrire promote.py"): "P04",  # gated release — securite deploiement
    (3, "Interdire toute écriture directe"): "P05",  # regle de sécurité architecture
    (3, "Backup DB + rotation"): "P08",  # sauvegarde importante mais pas bloquant immédiat
    (3, "Injecter recettes"): "P12",  # contenu specifique du jeu

    # ====== Phase 4 : Branchement MCP & Tests Agent (tous non faits) ======
    (4, "pz_generate_mod_template"): "P05",  # fonctionnalité MCP core
    (4, "ressources Markdown fixes + prompts"): "P07",  # ressources de base nécessaires
    (4, "Isoler chaque handler MCP"): "P03",  # sécurité serveur — isolation des composants critiques
    (4, "watchdog de redémarrage"): "P10",  # robustesse infra mais contournable
    (4, "Connecter le serveur à l'agent local"): "P06",  # connectivité nécessaire pour utilisation
    (4, "Test 1 : panique → armes à feu"): "P09",  # test validation core fonctionnalité
    (4, "Test 2 : générer UI Lua"): "P10",  # test validation feature modding
    (4, "Test 3 : stats exactes de Base.Axe"): "P11",  # test validation déterministe

    # ====== Phase 5 : Évaluation & Qualité (tous non faits) ======
    (5, "golden set de 25-30"): "P01",  # evaluation = base absolue de confiance
    (5, "Mesurer recall@5"): "P02",  # measurement critique sans laquelle pas de validation
    (5, "lier le golden set à promote.py"): "P01",  # gated release critique = securite deploiement
    (5, "Documenter les scores de référence"): "P13",  # documentation des résultats
    (5, "Générer le rapport de version"): "P14",  # reporting post-release

    # ====== Phase 6 : Maintenance & Build 42 (tous non faits) ======
    (6, "Détection de patch cassant"): "P03",  # regression detection = securite deploiement critique
    (6, "Filtrage $and natif"): "P08",  # optimisation requete core
    (6, "Mise à jour incrémentale Chroma"): "P05",  # performance re-ingestion importante
    (6, "tag Git annoté + archivage backup"): "P12",  # release management standard
    (6, "patch notes depuis Git"): "P15",  # automatisation nice-to-have

    # ====== Phase 7 : Moteur d'ingestion multi-format (termine) ======
    (7, "Arborescence ingestor"): "P03",  # déjà fait — fondation
    (7, "Processor.extract()"): "P02",  # déjà fait — interface core
    (7, "détection MIME"): "P03",  # déjà fait — fonctionnalité core
    (7, "ChromaDB writer"): "P04",  # déjà fait — stockage critique
    (7, "FFmpeg installe"): "P15",  # déjà fait — outil externe
    (7, "Tesseract OCR"): "P18",  # déjà fait — dépendance externe
    (7, "Playwright"): "P12",  # déjà fait — outil utilitaire
    (7, "Dépendances installes"): "P06",  # déjà fait — prerequisites

    # ====== Phase 8 : Web crawling (tous non faits) ======
    (8, "Moteur recherche DuckDuckGo"): "P12",  # pas d'API key nécessaire = utile mais pas critiqie
    (8, "Crawler Playwright BFS"): "P07",  # crawler core pour web ingestion
    (8, "Brave Search fallback"): "P10",  # fallback important mais DDG fonctionne déjà
    (8, "Stockage dans ChromaDB pz_web_pages"): "P09",  # stockage web pages necessaire
    (8, "Test sur un site reel"): "P13",  # validation

    # ====== Phase 9 : Processeurs multi-format (tous faits sauf test CLI) ======
    (9, "Text (.txt"): "P04",  # processeur base le plus utilise
    (9, "PDF"): "P05",  # format doc standard important
    (9, "Images"): "P07",  # OCR nécessaire mais pas premieraire
    (9, "Video"): "P06",  # traitement lourd mais cas d'usage niche
    (9, "Audio"): "P10",  # transcription utile mais moins prioritaire
    (9, "Word .docx"): "P11",  # format office courant
    (9, "eBooks .epub"): "P13",  # format niche
    (9, "CLI --file + --dir testes"): "P08",  # interface utilisateur CLI nécessaire

    # ====== Phase 10 : Safety + Infrastructure ======
    (10, "Quarantine manager"): "P02",  # sécurité core anti-contamination
    (10, "Circuit breaker anti-crash"): "P03",  # robustesse serveur absolue
    (10, "Disk space monitoring"): "P10",  # monitoring utile mais pas bloquant
    (10, "Docker service ingestor"): "P06",  # deploiement standard necessaire
    (10, "README ingestor"): "P14",  # documentation infra
    (10, "Tests unitaires processeurs"): "P01",  # qualite CORE — sans tests, pas de confiance deployment
    (10, "Structure bot"): "P07",  # structure code necessaire
    (10, "Slash commands"): "P09",  # fonctionnalité interface utilisateur bot
    (10, "Mode DM automatique"): "P12",  # fonctionnalité pratique mais pas critique
    (10, "Dockerfile + docker-compose.yml"): "P08",  # deploiement standard
    (10, "Corrections fix send_embed"): "P15",  # correctif mineur deja fait
    (10, "Lancement sans Docker"): "P13",  # utility scripts alternatif
    (10, "README bot"): "P14",  # documentation bot
    (10, "P0 fix async health checks"): "P16",  # correctif mineur deja fait
    (10, "Ollama qwen3.6"): "P12",  # model deployment standard
    (10, "ChromaDB docker compose"): "P09",  # deployment base necessaire
    (10, "Test du bot et validation"): "P07",  # validation finale fonctionnelle

    # ====== Phase 11 : Tests + Evaluation (PRIORITAIRE) ======
    (11, "golden.json cree"): "P15",  # donnees de test deja creees
    (11, "Tests unitaires processeurs critiques"): "P01",  # CORE — critical path absolu avant integration
    (11, "Golden set de 25-30 Q/R"): "P01",  # evaluation = base absolue de confiance du systeme
    (11, "Rapports de qualite"): "P08",  # deliverable qualite important mais apres tests
}


def match_p20_priority(phase_num: int, task_text: str) -> str:
    """Retourner la priorité Pxx manuelle pour cette tâche."""
    for (pn, substring), pri in PRIORITY_P20_MAP.items():
        if pn == phase_num and substring.lower() in task_text.lower():
            return pri
    return ""


def main():
    config = api.get_config()
    client = api.NotionClient(config)

    # Lire le todo.md
    todo_path = Path(__file__).parent / "agent" / "todo.md"
    if not todo_path.exists():
        todo_path = Path("agent/todo.md")
    text = todo_path.read_text(encoding="utf-8")

    phases_list = []  # list of (phase_num, task_text)
    phase_re = re.compile(r"^##\s+(?:NOUVEAU\s*:?\s+)?(?:PHASE|Phase)\s*(\d+)\s*([:\s—\-]+)(.+)$", re.MULTILINE)
    task_re = re.compile(r"^- \[(.)\] (.+)$", re.MULTILINE)

    current_phase_num = None
    for line in text.splitlines():
        stripped = line.strip()
        pm = phase_re.match(stripped)
        if pm:
            current_phase_num = int(pm.group(1))
            continue
        tm = task_re.match(stripped)
        if tm and current_phase_num is not None:
            txt = tm.group(2).strip()
            phases_list.append((current_phase_num, txt))

    # Query Notion et mettre à jour les priorités
    items = client.query_items()
    priority_col = client._priority_col
    if not priority_col:
        print("ERREUR : colonne Priority non trouvée !")
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

        m = re.search(r"Phase\s+(\d+)", phase_name)
        phase_num = int(m.group(1)) if m else 0

        new_pri = match_p20_priority(phase_num, name_val)
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

    # Summary par niveau de priorité
    pri_counts = {}
    for item in items:
        pri_prop = item.get("properties", {}).get(priority_col, {})
        pri_name = (pri_prop.get("select") or {}).get("name", "") if isinstance(pri_prop, dict) else "?"
        pri_counts[pri_name] = pri_counts.get(pri_name, 0) + 1

    print(f"\n{'='*60}")
    print(f"Total tâches : {total}")
    print(f"Modifiées : {changed}")
    print(f"Inchangées : {unchanged}")

    print(f"\nDistribution finale P01-P20 :")
    for k in sorted(k for k in pri_counts):
        bar = "█" * pri_counts[k]
        print(f"  {k:4s} | {bar} ({pri_counts[k]})")

    if unmatched:
        print(f"\nNon mappées ({len(unmatched)}) :")
        for pn, txt in unmatched[:10]:
            print(f"  Phase {pn}: {txt[:60]}")

    client.close()


if __name__ == "__main__":
    main()
