"""Tests unitaires pour notion_client.api.

Verifie le chargement de config, l'initialisation du client, la detection
de schema/columnes, create_item, query_items, update_item, et les erreurs.
Tous les tests utilisent des mocks — aucun appel HTTP reel n'est effectue.
"""

import httpx
import pytest
from unittest.mock import MagicMock

from notion_client.api import (
    NotionClient,
    NotionConfig,
    get_config,
)


# ===========================================================================
# Config : get_config / _load_env_vars
# ===========================================================================


@pytest.mark.unit
class TestConfig:
    """Tests du chargement de configuration."""

    def test_get_config_lit_variables_environnement(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ):
        """get_config() retourne un NotionConfig depuis les variables d'environnement."""
        # Creer un .env.notion fake vide pour eviter le fichier reel
        fake_env = tmp_path / "fake"
        fake_env.write_text("", encoding="utf-8")

        from notion_client.api import _load_env_vars as real_load

        def fake_load():
            """Retourne les valeurs test."""
            return {
                "NOTION_API_KEY": "ntn_from_env",
                "NOTION_DATABASE_ID": "db_id_from_env",
            }

        monkeypatch.setattr("notion_client.api._load_env_vars", fake_load)

        config = get_config()
        assert isinstance(config, NotionConfig)
        assert config.api_key == "ntn_from_env"
        assert config.database_id == "db_id_from_env"

    def test_get_config_leve_si_manchant(self, monkeypatch: pytest.MonkeyPatch):
        """get_config() leve RuntimeError si une variable est manquante."""
        # Supprimer les variables et simuler absence de fichier .env.notion
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
        from pathlib import Path

        monkeypatch.setattr(Path, "exists", lambda self: False)

        with pytest.raises(RuntimeError, match="requis"):
            get_config()


# ===========================================================================
# Initialisation du client NotionClient
# ===========================================================================


@pytest.mark.unit
class TestNotionClientInit:
    """Tests d'initialisation de NotionClient."""

    def test_init_stocke_config(self, mock_config):
        """Le client cree un _client (httpx) et initialise _schema a None."""
        client = NotionClient(mock_config)
        assert client._client is not None  # httpx.Client cree
        assert client._schema is None  # schema non charge

    def test_init_cree_httpx_client(self, mock_config, mocker):
        """L'initialisation cree un httpx.Client."""
        mock_httpx = MagicMock()
        mocker.patch("httpx.Client", return_value=mock_httpx)
        client = NotionClient(mock_config)
        assert client._client is not None

    def test_init_schema_initiallement_none(self, mock_config):
        """Avant toute requête, _schema est None."""
        client = NotionClient(mock_config)
        assert client._schema is None


# ===========================================================================
# Detection des colonnes via le schema
# ===========================================================================


@pytest.mark.unit
class TestColumnDetection:
    """Tests de detection dynamique des colonnes (title, status, phase...)."""

    def test_title_col_detecte_par_type(self, notion_client_fixture):
        """_title_col detecte la colonne de type 'title'."""
        client = notion_client_fixture()
        assert client._title_col == "Name"  # dans _SCHEMA_MOCK, Name a type= title

    def test_status_col_detecte_par_nom(self, notion_client_fixture):
        """_status_col detecte la colonne select contenant 'status'."""
        client = notion_client_fixture()
        assert client._status_col == "Status"

    def test_phase_col_detecte_par_nom(self, notion_client_fixture):
        """_phase_col detecte la colonne select contenant 'phase'."""
        client = notion_client_fixture()
        assert client._phase_col == "Phase"

    def test_priority_col_detecte_par_nom(self, notion_client_fixture):
        """_priority_col detecte la colonne select contenant 'priorit'."""
        client = notion_client_fixture()
        assert client._priority_col == "Priority"

    def test_source_col_detecte_par_nom(self, notion_client_fixture):
        """_source_col detecte la colonne select contenant 'source'."""
        client = notion_client_fixture()
        assert client._source_col == "Source"

    def test_fallback_title_sans_type(self, notion_client_fixture, mocker):
        """Si aucune colonne de type title, fallback sur 'Title'."""
        fake_schema = {
            "properties": {
                "Nom": {"type": "rich_text"},  # pas title!
                "Statut": {"type": "select", "select": {"options": []}},
            }
        }
        client = notion_client_fixture(fake_schema)
        assert client._title_col == "Title"


# ===========================================================================
# create_item — creation d'une page
# ===========================================================================


@pytest.mark.unit
class TestCreateItem:
    """Tests de la methode create_item."""

    def test_create_item_appele_request_POST(self, notion_client_fixture, mocker):
        """create_item appelle _request avec method POST."""
        client = notion_client_fixture()
        mocker.patch.object(client, "_request", return_value={"id": "new_page_id"})

        client.create_item(name="Nouvelle tache")

        client._request.assert_called_once()
        args = client._request.call_args
        assert args[0] == ("POST", "/pages")

    def test_create_item_build_properties_correctly(self, notion_client_fixture, mocker):
        """create_item construit les proprietes en fonction du schema."""
        client = notion_client_fixture()
        mocker.patch.object(client, "_request", return_value={"id": "new_page_id"})

        client.create_item(
            name="Tache test",
            phase="Phase 1 : Environnement",
            status="In Progress",
            priority="P1",
            source="local",
        )

        call_args = client._request.call_args
        json_body = call_args.kwargs["json_body"]
        props = json_body["properties"]

        # Titre
        assert "Name" in props or any("title" in str(k) for k in props.keys())
        assert "Phase" in props or any("phase" in str(k).lower() for k in props.keys())
        assert "Status" in props or any("status" in str(k).lower() for k in props.keys())

    def test_create_item_retourne_page_id(self, notion_client_fixture, mocker):
        """create_item retourne l'id de la page creee."""
        client = notion_client_fixture()
        mocker.patch.object(client, "_request", return_value={"id": "page_new_123"})

        page_id = client.create_item(name="Nouvelle tache")
        assert page_id == "page_new_123"


# ===========================================================================
# query_items — requête et pagination
# ===========================================================================


@pytest.mark.unit
class TestQueryItems:
    """Tests de la methode query_items."""

    def test_query_items_retourne_liste(self, notion_client_fixture, mocker, item_mock):
        """query_items retourne une liste d'items."""
        response = {
            "object": "list",
            "results": [item_mock],
            "has_more": False,
            "next_cursor": None,
        }
        mocker.patch.object(NotionClient, "_ensure_schema", return_value={})
        client = notion_client_fixture()
        mocker.patch.object(client, "_request", return_value=response)

        items = client.query_items()
        assert isinstance(items, list)
        assert len(items) == 1

    def test_query_items_gere_pagination(self, notion_client_fixture, mocker):
        """query_items gere la pagination (has_more + next_cursor)."""
        page1 = {
            "results": [{"id": "page_1"}, {"id": "page_2"}],
            "has_more": True,
            "next_cursor": "cursor_abc",
        }
        page2 = {
            "results": [{"id": "page_3"}],
            "has_more": False,
            "next_cursor": None,
        }
        client = notion_client_fixture()
        mocker.patch.object(NotionClient, "_ensure_schema", return_value={})
        mocker.patch.object(client, "_request", side_effect=[page1, page2])

        items = client.query_items()
        assert len(items) == 3
        # Appele _request 2 fois (page 1 + page 2)
        assert client._request.call_count == 2

    def test_query_items_applique_filter(self, notion_client_fixture, mocker):
        """query_items transmet le filtre a l'API."""
        response = {"results": [], "has_more": False}
        client = notion_client_fixture()
        mocker.patch.object(NotionClient, "_ensure_schema", return_value={})
        mocker.patch.object(client, "_request", return_value=response)

        filter_spec = {"property": "Status", "select": {"equals": "Done"}}
        client.query_items(filter_props=filter_spec)

        call_args = client._request.call_args
        json_body = call_args.kwargs["json_body"]
        assert json_body["filter"] == filter_spec


# ===========================================================================
# update_item — mise a jour
# ===========================================================================


@pytest.mark.unit
class TestUpdateItem:
    """Tests de la methode update_item."""

    def test_update_item_appele_PATCH(self, notion_client_fixture, mocker):
        """update_item appelle _request avec method PATCH."""
        client = notion_client_fixture()
        mocker.patch.object(client, "_request", return_value={"id": "page_id"})

        client.update_item("page_id", status="Done")

        args = client._request.call_args
        assert args[0] == ("PATCH", "/pages/page_id")

    def test_update_item_transmet_statut(self, notion_client_fixture, mocker):
        """update_item inclut le statut dans les proprietes."""
        client = notion_client_fixture()
        mocker.patch.object(client, "_request", return_value={"id": "page_id"})

        client.update_item("page_id", status="In Progress")

        call_args = client._request.call_args
        props = call_args.kwargs["json_body"]["properties"]
        assert "Status" in props or any("status" in str(k).lower() for k in props.keys())


# ===========================================================================
# Gestion des erreurs et rate limiting
# ===========================================================================


@pytest.mark.unit
class TestErrorHandling:
    """Tests de gestion des erreurs et du rate limiting."""

    def test_request_leve_runtime_error_sur_4xx(self, mock_config, mocker):
        """_request leve RuntimeError pour les codes 4xx."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Database not found"
        mock_client = MagicMock()
        mock_client.request.return_value = mock_resp

        client = NotionClient(mock_config)
        mocker.patch.object(client, "_client", mock_client)
        with pytest.raises(RuntimeError, match="Notion API 404"):
            client._request("GET", "/databases/nonexistent")

    def test_request_leve_runtime_error_httpx(self, mock_config, mocker):
        """_request enveloppe les erreurs httpx dans RuntimeError."""
        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.HTTPError("Network unreachable")

        client = NotionClient(mock_config)
        mocker.patch.object(client, "_client", mock_client)
        with pytest.raises(RuntimeError, match="Notion API error"):
            client._request("GET", "/databases/test")

    def test_rate_limiting_429_retry(self, mock_config, mocker, mock_httpx_response):
        """En cas de 429, le client retry avec exponential backoff."""
        import time

        resp_429 = mock_httpx_response(429)
        resp_ok = mock_httpx_response(200, {"success": True})

        mock_client = MagicMock()
        mock_client.request.side_effect = [resp_429, resp_ok]

        client = NotionClient(mock_config)
        mocker.patch.object(client, "_client", mock_client)
        mocker.patch("time.sleep")  # ne pas attendre reellement
        result = client._request("GET", "/test")

        assert result == {"success": True}
        assert mock_client.request.call_count == 2

    def test_rate_limiting_epuise_leve_error(self, mock_config, mocker, mock_httpx_response):
        """Apres MAX_RETRIES tentatives de 429, une erreur est levee."""
        from notion_client.api import MAX_RETRIES

        resp_429 = mock_httpx_response(429)

        mock_client = MagicMock()
        # Toujours 429 — jamais de reussite
        mock_client.request.return_value = resp_429

        client = NotionClient(mock_config)
        mocker.patch.object(client, "_client", mock_client)
        mocker.patch("time.sleep")
        with pytest.raises(RuntimeError, match="Notion API 429"):
            client._request("GET", "/test")

        # MAX_RETRIES + 1 (la premiere tentative + MAX_RETRIES retries)
        assert mock_client.request.call_count == MAX_RETRIES + 1

    def test_close_ferme_httpx_client(self, mock_config):
        """close() appelle _client.close()."""
        client = NotionClient(mock_config)
        client._client.close = MagicMock()
        client.close()
        client._client.close.assert_called_once_with()
