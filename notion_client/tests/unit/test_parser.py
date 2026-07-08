"""Tests unitaires pour notion_client.parser.

Verifie le parsing de todo.md, extraction de phases/tâches, formatage,
et les cas limites du parser Markdown checklist.
"""

import pytest
from pathlib import Path

from notion_client import parser


# ===========================================================================
# Parsing basique : phases et tâches
# ===========================================================================


@pytest.mark.unit
class TestParserBasics:
    """Tests de base du parser."""

    def test_parse_todo_retourne_liste_de_phases(self, sample_todo_file):
        """parse_todo retourne une liste de Phase."""
        result = parser.parse_todo(str(sample_todo_file))
        assert isinstance(result, list)
        assert all(isinstance(p, parser.Phase) for p in result)

    def test_parse_todo_trouve_3_phases(self, parsed_phases):
        """Le sample contient exactement 3 phases."""
        assert len(parsed_phases) == 3

    def test_phase_contient_nom_et_taches(self, parsed_phases):
        """Chaque Phase a name (str) et tasks (list[Task])."""
        for phase in parsed_phases:
            assert isinstance(phase.name, str)
            assert len(phase.name) > 0
            assert isinstance(phase.tasks, list)
            assert all(isinstance(t, parser.Task) for t in phase.tasks)

    def test_task_contient_texte_et_statut(self, parsed_phases):
        """Chaque Task a text (str non vide) et done (bool)."""
        for phase in parsed_phases:
            for task in phase.tasks:
                assert isinstance(task.text, str)
                assert len(task.text) > 0
                assert isinstance(task.done, bool)


# ===========================================================================
# Statut [x] / [ ] — tâches complétées vs non-complétées
# ===========================================================================


@pytest.mark.unit
class TestParserStatut:
    """Tests de détection du statut de complétion."""

    def test_tache_fermée_detectee(self, parsed_phases):
        """Les tâches avec [x] ont done=True."""
        phase1 = parsed_phases[0]
        assert phase1.tasks[0].done is True  # Initialiser le repo Git
        assert phase1.tasks[1].done is True  # Configurer Python

    def test_tache_ouverte_detectee(self, parsed_phases):
        """Les tâches avec [ ] ont done=False."""
        phase1 = parsed_phases[0]
        assert phase1.tasks[2].done is False
        assert phase1.tasks[3].done is False

    def test_statut_case_insensitive(self, tmp_path: Path):
        """[X] et [x] sont tous les deux detectes comme fait."""
        content = (
            "## Phase 1 : Test\n"
            "- [x] lowercase x\n"
            "- [X] uppercase X\n"
            "- [ ] space ouvert\n"
        )
        f = tmp_path / "test.md"
        f.write_text(content, encoding="utf-8")
        phases = parser.parse_todo(str(f))
        assert len(phases) == 1
        assert phases[0].tasks[0].done is True
        assert phases[0].tasks[1].done is True
        assert phases[0].tasks[2].done is False

    def test_taches_de_phase_3_sont_ouvertes(self, parsed_phases):
        """Phase 3 n'a aucune tâche [x] dans le sample."""
        phase3 = parsed_phases[2]
        assert all(not t.done for t in phase3.tasks)

    def test_taches_phase_2_melange(self, parsed_phases):
        """Phase 2 a un mélange de [x] et [ ]."""
        phase2 = parsed_phases[1]
        done = sum(1 for t in phase2.tasks if t.done)
        assert done == 1


# ===========================================================================
# Nettoyage du texte Markdown (balises, emojis)
# ===========================================================================


@pytest.mark.unit
class TestParserTexteNettoye:
    """Tests de nettoyage des formats Markdown dans le texte des tâches."""

    def test_enleve_balises_italique(self, parsed_phases):
        """Les *texte* deviennent texte (sans les *)."""
        phase2 = parsed_phases[1]
        task = [t for t in phase2.tasks if "Implémenter" in t.text][0]
        assert "*" not in task.text
        assert "Implémenter" in task.text

    def enleve_backticks(self, tmp_path: Path):
        """Les `code` deviennent code (sans les backticks)."""
        content = (
            "## Phase 1 : Test\n"
            "- [ ] Lire le fichier `README.md`\n"
            "- [x] Tâche normale\n"
        )
        f = tmp_path / "test.md"
        f.write_text(content, encoding="utf-n")
        phases = parser.parse_todo(str(f))
        assert "`" not in phases[0].tasks[0].text

    def test_enleve_emoji_marker_fin_ligne(self, tmp_path: Path):
        """Les marqueurs [OK] en fin de ligne sont retires pour TOUS les tasks."""
        content = (
            "## Phase 1 : Test\n"
            "- [x] Tâche termine [OK]\n"
            "- [x] Autre tache [OK]\n"
            "- [ ] Pas fini encore\n"
        )
        f = tmp_path / "test.md"
        f.write_text(content, encoding="utf-8")
        phases = parser.parse_todo(str(f))
        assert len(phases) == 1
        # Les marqueurs [OK] sont retires de TOUTES les tasks
        assert phases[0].tasks[0].text.endswith("termine")
        assert phases[0].tasks[1].text.endswith("tâche")
        assert phases[0].tasks[2].text == "Pas fini encore"


# ===========================================================================
# format_tasks_as_md — re-generation Markdown
# ===========================================================================


@pytest.mark.unit
class TestFormatTasksAsMd:
    """Tests de la fonction format_tasks_as_md."""

    def test_regenerere_checklist_valid(self, parsed_phases):
        """format_tasks_as_md genere un Markdown avec les bons checklists."""
        md = parser.format_tasks_as_md(parsed_phases)
        assert "- [x] Initialiser le repo Git" in md
        assert "- [ ] Installer les dependances" in md

    def test_inclut_noms_de_phase(self, parsed_phases):
        """Le Markdown genere inclut les ## Phase N."""
        md = parser.format_tasks_as_md(parsed_phases)
        assert "## Phase 1 : Environnement & Fondations" in md
        assert "## Phase 2 : Integration IA" in md
        assert "## Phase 3 : Gouvernance & Déploiement" in md

    def test_sortie_reparsable(self, parsed_phases, tmp_path: Path):
        """Le Markdown genere peut être re-parsé avec le même resultat."""
        md = parser.format_tasks_as_md(parsed_phases)
        tmp = tmp_path / "_reparse.md"
        tmp.write_text(md, encoding="utf-8")
        reparsed = parser.parse_todo(str(tmp))
        assert len(reparsed) == len(parsed_phases)
        for orig, new in zip(parsed_phases, reparsed):
            assert orig.name == new.name
            assert len(orig.tasks) == len(new.tasks)


# ===========================================================================
# get_total_stats — statistiques
# ===========================================================================


@pytest.mark.unit
class TestGetTotalStats:
    """Tests de la fonction get_total_stats."""

    def test_compte_total(self, parsed_phases):
        """Le total est le nombre total de tâches dans toutes les phases."""
        stats = parser.get_total_stats(parsed_phases)
        assert stats["total"] == 12  # 4 + 4 + 4

    def test_compte_terminees(self, parsed_phases):
        """Le done compte uniquement les [x]."""
        stats = parser.get_total_stats(parsed_phases)
        # Phase 1 : 2x[x], Phase 2 : 1x[x], Phase 3 : 0x[x]
        assert stats["done"] == 3

    def test_remaining_calcule_correctement(self, parsed_phases):
        """remaining = total - done."""
        stats = parser.get_total_stats(parsed_phases)
        assert stats["remaining"] == stats["total"] - stats["done"]

    def test_retourne_trois_cles(self, parsed_phases):
        """Le dict retourne exactement les clés : total, done, remaining."""
        stats = parser.get_total_stats(parsed_phases)
        assert set(stats.keys()) == {"total", "done", "remaining"}

    def test_phases_vides_retourne_zeros(self):
        """Avec des phases vides, tout est 0."""
        empty = [parser.Phase(name="Vide", tasks=[])]
        stats = parser.get_total_stats(empty)
        assert stats == {"total": 0, "done": 0, "remaining": 0}


# ===========================================================================
# Cas limites
# ===========================================================================


@pytest.mark.unit
class TestParserEdgeCases:
    """Tests des situations limites."""

    def test_fichier_vide_retourne_liste_vierge(self, tmp_path: Path):
        """Un todo.md vide retourne une liste de phases vide."""
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        assert parser.parse_todo(str(f)) == []

    def test_pas_de_section_phase_retourne_vide(self, tmp_path: Path):
        """Des tâches sans section ## Phase sont ignorees."""
        content = "- [x] Tâche orpheline\n- [ ] Autre orpheline\n"
        f = tmp_path / "orphan.md"
        f.write_text(content, encoding="utf-8")
        assert parser.parse_todo(str(f)) == []

    def test_fichier_inexistant_leve_error(self):
        """Le parser lève FileNotFoundError pour un chemin inexistant."""
        with pytest.raises(FileNotFoundError):
            parser.parse_todo("/absolument/pas/ce/fichier.md")

    def test_phase_avec_separateurs_varies(self, tmp_path: Path):
        """Detecte les phases avec : ou — ou - comme separateur."""
        content = (
            "## Phase 1: Avec deux-points\n"
            "- [ ] Tâche A\n\n"
            "## Phase 2 — Tiret long\n"
            "- [x] Tâche B\n\n"
            "## Phase 3 - Tiret simple\n"
            "- [ ] Tâche C\n"
        )
        f = tmp_path / "variants.md"
        f.write_text(content, encoding="utf-8")
        phases = parser.parse_todo(str(f))
        assert len(phases) == 3

    def test_tache_avec_checkbox_malformee_ignoree(self, tmp_path: Path):
        """Les lignes qui ne matchent pas ^- \\[.]$ sont ignorees."""
        content = (
            "## Phase 1 : Test\n"
            "- [x] Valide\n"
            "-- [ ] Non checklist\n"
            "Tâche sans tiret\n"
            "- [] Checkbox vide\n"
        )
        f = tmp_path / "malformed.md"
        f.write_text(content, encoding="utf-8")
        phases = parser.parse_todo(str(f))
        assert len(phases) == 1
        assert len(phases[0].tasks) == 1  # Seulement la tâche valide
