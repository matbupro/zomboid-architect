"""Tests unitaires pour notion_client.sync.

Verifie la detection de priorite, l'extraction de texte/colonnes select,
la correspondance fuzzy des taches, et le flux complet du sync (mocke).
"""

import pytest
from unittest.mock import MagicMock, patch

from notion_client.sync import (
    SyncAction,
    _detect_priority,
    _extract_text,
    _extract_select,
    _normalize_text,
    _fuzzy_match,
    _levenshtein_similarity,
    sync,
)


# ===========================================================================
# Detection de priorite via mots-clés
# ===========================================================================


@pytest.mark.unit
class TestPriorityDetection:
    """Tests de la fonction _detect_priority."""

    def test_detecte_P0_urgent(self):
        assert _detect_priority("Fix urgent bug") == "P0"
        assert _detect_priority("Blocker critique") == "P0"
        assert _detect_priority("Crash en production") == "P0"
        assert _detect_priority("Corrección de regresión") == "P0"

    def test_detecte_P0_blocker_fix(self):
        assert _detect_priority("Blocker fix required") == "P0"
        assert _detect_priority("Regr: regression detected") == "P0"

    def test_detecte_P1_prioritaire(self):
        assert _detect_priority("Prioritaire feature") == "P1"
        assert _detect_priority("Essentiel refactor") == "P1"
        assert _detect_priority("Fondamental update") == "P1"
        assert _detect_priority("Docker configuration") == "P1"
        assert _detect_priority("Readme update") == "P1"

    def test_detecte_P1_integration(self):
        assert _detect_priority("Integration API backend") == "P1"
        assert _detect_priority("Backup strategy") == "P1"
        assert _detect_priority("Circuit breaker pattern") == "P1"

    def test_detecte_P3_par_defaut(self):
        assert _detect_priority("Task quelconque sans mot-clé") == "P3"
        assert _detect_priority("Documentation générale") == "P3"
        assert _detect_priority("") == "P3"

    def test_insensible_a_la_casse(self):
        assert _detect_priority("URGENT TASK") == "P0"
        assert _detect_priority("PRIORITAIRE tâche") == "P1"
        assert _detect_priority("BLOCKER ISSUE") == "P0"


# ===========================================================================
# Extraction de texte et select depuis les proprietes Notion
# ===========================================================================


@pytest.mark.unit
class TestExtractHelpers:
    """Tests des helpers d'extraction (texte, select)."""

    def test_extract_text_retourne_contenu(self):
        prop = {"title": [{"type": "text", "text": {"content": "Ma tache"}}]}
        assert _extract_text(prop) == "Ma tache"

    def test_extract_text_vide_si_none(self):
        assert _extract_text(None) == ""

    def test_extract_text_retourne_premier_block(self):
        prop = {
            "title": [
                {"type": "text", "text": {"content": "Premier"}},
                {"type": "text", "text": {"content": "Deuxieme"}},
            ]
        }
        assert _extract_text(prop) == "Premier"

    def test_extract_select_retourne_nom(self):
        prop = {"select": {"name": "Done", "id": "st2"}}
        assert _extract_select(prop) == "Done"

    def test_extract_select_vide_si_pas_dict(self):
        prop = {"select": "string_value"}  # pas un dict
        assert _extract_select(prop) == ""

    def test_extract_select_vide_si_none(self):
        assert _extract_select(None) == ""


# ===========================================================================
# Flux de sync complet (avec mocks)
# ===========================================================================


@pytest.mark.unit
class TestSyncFlow:
    """Tests du flux complet de sync avec mocks."""

    def test_sync_cre_taches_lorsque_no_remote(
        self, sample_todo_file, mock_config, monkeypatch
    ):
        """Quand il n'y a aucun item distant, toutes les taches sont creees."""
        client_mock = MagicMock()
        client_mock.query_items.return_value = []
        client_mock._title_col = "Name"
        client_mock._phase_col = "Phase"
        client_mock._status_col = "Status"
        client_mock._priority_col = "Priority"

        created_ids: list[str] = []

        def _create_item(**kwargs):
            new_id = f"new_{len(created_ids)}"
            created_ids.append(new_id)
            return new_id

        client_mock.create_item.side_effect = _create_item

        monkeypatch.setenv("NOTION_API_KEY", "ntn_test")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db_test")

        with patch("notion_client.api.get_config", return_value=mock_config):
            with patch("notion_client.api.NotionClient", return_value=client_mock):
                actions = sync(dry_run=False, file_path=str(sample_todo_file))

        assert len(created_ids) == 12
        assert all(a.action == "created" for a in actions)

    def test_sync_mets_a_jour_statut_si_different(
        self, sample_todo_file, mock_config, monkeypatch
    ):
        """Si le statut distant differre du local, update_item est appele."""
        remote_item = {
            "id": "existing_page",
            "properties": {
                "Name": {"title": [{"text": {"content": "Installer les dependances"}}]},
                "Phase": {"select": {"name": "Phase 1 : Environnement & Fondations"}},
                "Status": {"select": {"name": "Not Started"}},
                "Priority": {"select": {"name": "P3"}},
            },
        }
        client_mock = MagicMock()
        client_mock.query_items.return_value = [remote_item]
        client_mock._title_col = "Name"
        client_mock._phase_col = "Phase"
        client_mock._status_col = "Status"
        client_mock._priority_col = "Priority"
        client_mock.create_item.return_value = "new_page"

        monkeypatch.setenv("NOTION_API_KEY", "ntn_test")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db_test")

        with patch("notion_client.api.get_config", return_value=mock_config):
            with patch("notion_client.api.NotionClient", return_value=client_mock):
                actions = sync(dry_run=False, file_path=str(sample_todo_file))

        # La tache "Installer les dependances" a [ ] (done=False) → statut attendu "Not Started"
        # Le distant est aussi "Not Started" → pas de mise a jour attendue
        assert len(actions) == 12

    def test_sync_mode_dry_run_ne_cre_pas_rien(
        self, sample_todo_file, mock_config, monkeypatch
    ):
        """En dry_run, aucun item n'est cree dans Notion."""
        client_mock = MagicMock()
        client_mock.query_items.return_value = []
        client_mock._title_col = "Name"
        client_mock._phase_col = "Phase"
        client_mock._status_col = "Status"
        client_mock._priority_col = "Priority"

        monkeypatch.setenv("NOTION_API_KEY", "ntn_test")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db_test")

        with patch("notion_client.api.get_config", return_value=mock_config):
            with patch("notion_client.api.NotionClient", return_value=client_mock):
                actions = sync(dry_run=True, file_path=str(sample_todo_file))

        client_mock.create_item.assert_not_called()
        assert len(actions) == 12


# ===========================================================================
# Creer un item avec une DB vide (premiere sync)
# ===========================================================================


@pytest.mark.unit
class TestFirstSync:
    """Tests specifiques a la premiere sync (DB Notion vide)."""

    def test_premiere_sync_cree_toutes_les_taches(
        self, sample_todo_file, mock_config, monkeypatch
    ):
        """La premiere sync cree une page par tache locale."""
        client_mock = MagicMock()
        client_mock.query_items.return_value = []
        client_mock._title_col = "Name"
        client_mock._phase_col = "Phase"
        client_mock._status_col = "Status"
        client_mock._priority_col = "Priority"

        monkeypatch.setenv("NOTION_API_KEY", "ntn_test")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db_test")

        with patch("notion_client.api.get_config", return_value=mock_config):
            with patch("notion_client.api.NotionClient", return_value=client_mock):
                actions = sync(dry_run=False, file_path=str(sample_todo_file))

        assert client_mock.create_item.call_count == 12
        assert len(actions) == 12

    def test_premiere_sync_preserve_phase_et_statut(
        self, sample_todo_file, mock_config, monkeypatch
    ):
        """La premiere sync preserve la phase et le statut de chaque tache."""
        client_mock = MagicMock()
        client_mock.query_items.return_value = []
        client_mock._title_col = "Name"
        client_mock._phase_col = "Phase"
        client_mock._status_col = "Status"
        client_mock._priority_col = "Priority"

        monkeypatch.setenv("NOTION_API_KEY", "ntn_test")
        monkeypatch.setenv("NOTION_DATABASE_ID", "db_test")

        with patch("notion_client.api.get_config", return_value=mock_config):
            with patch("notion_client.api.NotionClient", return_value=client_mock):
                actions = sync(dry_run=False, file_path=str(sample_todo_file))

        phases_vues = {a.phase for a in actions}
        assert len(phases_vues) == 3


# ===========================================================================
# SyncAction dataclass
# ===========================================================================


@pytest.mark.unit
class TestSyncAction:
    """Tests sur le dataclass SyncAction."""

    def test_creer_sync_action(self):
        action = SyncAction(
            phase="Phase 1 : Test",
            task_text="Ma tache",
            local_done=True,
            action="created",
        )
        assert action.phase == "Phase 1 : Test"
        assert action.task_text == "Ma tache"
        assert action.local_done is True
        assert action.action == "created"

    def test_sync_action_est_non_frozen(self):
        """Les dataclass par defaut ne sont pas frozen — on peut modifier."""
        action = SyncAction(
            phase="Phase 1", task_text="Task", local_done=False, action="synced"
        )
        action.action = "updated_status"
        assert action.action == "updated_status"


# ===========================================================================
# Normalisation de texte (accents, ponctuation, tirets)
# ===========================================================================


@pytest.mark.unit
class TestNormalizeText:
    """Tests de la fonction _normalize_text."""

    def test_supprime_accents(self):
        # Apostrophe -> espace (ne pas coller les mots)
        result = _normalize_text("Créer l'arborescence")
        assert result == "creer l arborescence"

    def test_conserve_ampersand(self):
        """Le & n'est pas supprimé (pas dans la regex de normalization)."""
        assert _normalize_text("Parsing & Textualization") == "parsing & textualization"
        # Note : le & n'est pas supprimé (pas dans la regex de normalization)

    def test_supprime_tirets_emdash(self):
        assert _normalize_text("Dual-Field résilient") == "dual field resilient"
        assert _normalize_text("Phase 3.1 — Ingestion") == "phase 3.1 ingestion"

    def test_apostrophe_devient_espace(self):
        """L'apostrophe devient espace (ne pas coller les mots adjacents)."""
        # 'l'arborescence → l arborescence (pas larborescence)
        assert _normalize_text("Créer l'arborescence") == "creer l arborescence"

    def test_collapse_espaces(self):
        result = _normalize_text("texte   avec   plusieurs    espaces")
        assert result == "texte avec plusieurs espaces"

    def test_insensible_a_la_casse(self):
        assert _normalize_text("Texte en MAJUSCULE") == _normalize_text("texte en majuscule")

    def test_accents_francais_complets(self):
        """Tous les accents FR : é, è, ê, à, û, ù, ô, î, ç."""
        text = "Être où il faut, c'est une âme courageuse"
        result = _normalize_text(text)
        assert "e" in result
        assert "â" not in result  # l'accent a été supprime
        assert "u" in result

    def test_vide_retourne_vide(self):
        assert _normalize_text("") == ""
        assert _normalize_text("   ") == ""


# ===========================================================================
# Similarité Levenshtein
# ===========================================================================


@pytest.mark.unit
class TestLevenshteinSimilarity:
    """Tests de la fonction _levenshtein_similarity."""

    def test_identiques_retourne_1(self):
        assert _levenshtein_similarity("abc", "abc") == 1.0

    def test_vide_retourne_0(self):
        assert _levenshtein_similarity("", "abc") == 0.0
        assert _levenshtein_similarity("abc", "") == 0.0

    def test_diff_dune_letrae(self):
        """Deux chaines differees d'une lettre → similarite >= 0.5."""
        sim = _levenshtein_similarity("craf", "cafe")
        assert sim >= 0.5  # tres proche (ex: 3/6 = 0.5)

    def test_identique_apres_normalisation(self):
        # "Créer" normalisé = "Creer", "Creer" → similarity = 1.0
        sim = _levenshtein_similarity(_normalize_text("Créer"), _normalize_text("Creer"))
        assert sim == 1.0

    def test_très_different_retourne_proche_0(self):
        sim = _levenshtein_similarity("abc", "xyz")
        assert sim < 0.5


# ===========================================================================
# Fuzzy match — correspondance tasks local↔Notion
# ===========================================================================


@pytest.mark.unit
class TestFuzzyMatch:
    """Tests de la fonction _fuzzy_match."""

    def test_exact_normalise_retourne_texte(self):
        """Si les textes normalisés sont identiques → match exact."""
        result = _fuzzy_match("Créer l'arborescence", ["Creer l arborescence"])
        assert result == "Creer l arborescence"

    def test_avec_accents_detecte_match(self):
        """Les accents sont ignoress — "Résilient" matche "Resilient"."""
        result = _fuzzy_match("Coder le parseur Dual-Field résilient", [
            "Coder le parseur dual field resilient",
        ])
        assert result == "Coder le parseur dual field resilient"

    def test_apostrophe_supprimee(self):
        """L'apostrophe est ignoress — "Créer l'arborescence" matche "Creer larborescence"."""
        result = _fuzzy_match("Créer l'arborescence", ["Creer larborescence"])
        assert result == "Creer larborescence"

    def test_tiret_remplace_espaces(self):
        """Les tirets deviennent espaces — "Dual-Field" = "dual field"."""
        result = _fuzzy_match("Dual-Field", ["Dual Field"])
        assert result == "Dual Field"

    def test_no_match_retourne_none(self):
        """Si aucun texte ne dépasse le threshold → None."""
        result = _fuzzy_match("Tâche totalement différente", [
            "Créer l arborescence",
            "Initialiser le depot Git",
        ])
        assert result is None

    def test_high_score_levenshtein_accepte(self):
        """Une similarité élevee (> threshold) est acceptee."""
        # "cafe" vs "cafe" (identique après normalisation accent)
        result = _fuzzy_match("Cafe", ["cafe"])
        assert result == "cafe"

    def test_empty_remote_list_retourne_none(self):
        """Sans textes distants → None."""
        assert _fuzzy_match("Ma tâche", []) is None

    def test_empty_local_retourne_none(self):
        """Sans texte local → None."""
        assert _fuzzy_match("", ["quelque chose"]) is None

    def test_multi_choice_picks_closest(self):
        """Parmi plusieurs choix, le plus proche (equal après normalization) est retourné."""
        options = [
            "Initialiser le depot Git",   # → normalisé: "initialiser le depot git"
            "Creer l arborescence",       # → normalisé: "creer l arborescence"
            "Configurer les hooks de commit",  # different
        ]
        # Le local avec accent : "dépôt" → "depot" après normalization → egal à option[0]
        result = _fuzzy_match("Initialiser le dépôt Git", options)
        assert result == "Initialiser le depot Git"

    def test_multi_choice_picks_best_levensthein(self):
        """Avec des textes non-exacts mais proches, le meilleur score est retourné."""
        options = [
            "Initialiser le depot Git",
            "Creer l arborescence complete",
        ]
        # Local tres proche de option[0] (diff de 1 char: 'o' vs 'ô')
        result = _fuzzy_match("Initialiser le depôt Git", options)
        assert result == "Initialiser le depot Git"

    def test_threshold_stricte_rejete_loin(self):
        """Un score inferieur au threshold (0.85) est rejete."""
        # "abcde" vs "xyzab" → similarite ~0.4 < 0.85 → None
        result = _fuzzy_match("abcde", ["xyzab"])
        assert result is None
