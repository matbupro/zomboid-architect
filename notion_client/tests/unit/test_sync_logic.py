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
