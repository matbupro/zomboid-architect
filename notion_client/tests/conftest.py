"""Fixtures pytest partagées pour notion_client.

Definit les donnees de test, mocks httpx, et helpers utilitaires.
"""

import json
import pathlib
import pytest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Fixtures : donnees todo.md sample
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_todo_content() -> str:
    """Contenu sample d'un fichier todo.md valide (3 phases, 12 taches)."""
    return (
        "## Phase 1 : Environnement & Fondations\n"
        "\n"
        "- [x] Initialiser le repo Git\n"
        "- [x] Configurer Python 3.10+\n"
        "- [ ] Installer les dependances (pip install -r requirements.txt)\n"
        "- [ ] Creer la structure de base\n"
        "\n"
        "## Phase 2 : Integration IA\n"
        "\n"
        "- [x] *Implémenter* le parser Markdown\n"
        "- [ ] Connecter l'API Notion (urgent bloquant)\n"
        "- [ ] Tests unitaires pour le sync\n"
        "- [ ] `test_api_client.py` - verifier rate limiting\n"
        "\n"
        "## Phase 3 : Gouvernance & Déploiement\n"
        "\n"
        "- [ ] Docker containerization\n"
        "- [ ] GitHub Actions CI/CD (prioritaire essentiel)\n"
        "- [ ] Documenter l'architecture\n"
        "- [ ] Review de securité\n"
    )


@pytest.fixture
def sample_todo_file(tmp_path: pathlib.Path, sample_todo_content: str) -> pathlib.Path:
    """Creer un fichier todo.md temporaire."""
    todo = tmp_path / "todo.md"
    todo.write_text(sample_todo_content, encoding="utf-8")
    return todo


@pytest.fixture
def parsed_phases(sample_todo_file: pathlib.Path):
    """Parser le sample et retourner la liste de Phase."""
    from notion_client import parser

    return parser.parse_todo(str(sample_todo_file))


# ---------------------------------------------------------------------------
# Fixtures : config Notion mockée
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Injecter une clé API test dans les variables d'environnement."""
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test_key_1234567890abcdefghijklmnop")
    monkeypatch.setenv("NOTION_DATABASE_ID", "39141972-c0be-807d-b3f0-c1357997348f")
    return "ntn_test_key_1234567890abcdefghijklmnop"


@pytest.fixture
def mock_config(mock_api_key: str):
    """Retourner un NotionConfig directement (bypass _load_env_vars)."""
    from notion_client.api import NotionConfig

    return NotionConfig(
        api_key=mock_api_key,
        database_id="39141972-c0be-807d-b3f0-c1357997348f",
    )


# ---------------------------------------------------------------------------
# Fixtures : mocks httpx
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_httpx_response(mocker: pytest.MockFixture):
    """Helper pour créer des réponses httpx simulées."""
    def _make(status_code: int = 200, body: dict | None = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body or {}
        return resp

    return _make


# ---------------------------------------------------------------------------
# Fixtures : reponses API Notion simulées
# ---------------------------------------------------------------------------

_SCHEMA_MOCK = {
    "object": "database",
    "id": "39141972-c0be-807d-b3f0-c1357997348f",
    "properties": {
        "Name": {"type": "title"},
        "Phase": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "Phase 1", "id": "s0"},
                    {"name": "Phase 2", "id": "s1"},
                ]
            },
        },
        "Status": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "Not Started", "id": "st0"},
                    {"name": "In Progress", "id": "st1"},
                    {"name": "Done", "id": "st2"},
                ]
            },
        },
        "Priority": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "P0", "id": "p0"},
                    {"name": "P1", "id": "p1"},
                    {"name": "P2", "id": "p2"},
                    {"name": "P3", "id": "p3"},
                ]
            },
        },
        "Source": {
            "type": "select",
            "select": {
                "options": [
                    {"name": "local", "id": "src0"},
                    {"name": "manuel", "id": "src1"},
                ]
            },
        },
    },
}

_ITEM_MOCK = {
    "id": "page_id_12345",
    "object": "page",
    "created_time": "2026-07-05T00:00:00.000Z",
    "last_edited_time": "2026-07-05T00:00:00.000Z",
    "properties": {
        "Name": {
            "id": "title",
            "type": "title",
            "title": [{"type": "text", "text": {"content": "Initialiser le repo Git"}}],
        },
        "Phase": {
            "id": "phase",
            "type": "select",
            "select": {"name": "Phase 1", "id": "s0"},
        },
        "Status": {
            "id": "status",
            "type": "select",
            "select": {"name": "Done", "id": "st2"},
        },
        "Priority": {
            "id": "priority",
            "type": "select",
            "select": {"name": "P2", "id": "p2"},
        },
        "Source": {
            "id": "source",
            "type": "select",
            "select": {"name": "local", "id": "src0"},
        },
    },
}


@pytest.fixture
def schema_mock():
    """Réponse de GET /databases/{id}."""
    return _SCHEMA_MOCK.copy()


@pytest.fixture
def item_mock():
    """Item Notion simulé (une page)."""
    return _ITEM_MOCK.copy()


@pytest.fixture
def query_response_mock(item_mock):
    """Réponse de POST /databases/{id}/query."""
    return {
        "object": "list",
        "results": [item_mock],
        "has_more": False,
        "next_cursor": None,
    }


# ---------------------------------------------------------------------------
# Helpers : reset singleton config pour tests propres
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_config_cache(monkeypatch: pytest.MonkeyPatch):
    """Reset le cache singleton api._get_config() après chaque test."""
    yield
    # Nettoyer le singleton entre les tests
    from notion_client import api as api_module

    api_module._config_instance = None


# ---------------------------------------------------------------------------
# Helper : créer un client Notion avec httpx mocké
# ---------------------------------------------------------------------------


@pytest.fixture
def notion_client_fixture(mock_config, mocker):
    """Creer un NotionClient avec _request et _ensure_schema mockés.

    Usage dans les tests :
        client = notion_client_fixture()
    """
    from notion_client.api import NotionClient

    # Bypasser le vrai _get_config pour toute la session de test
    mocker.patch("notion_client.api._get_config", return_value=mock_config)

    def _make(schema_override: dict | None = None):
        if schema_override is not None:
            mocker.patch.object(NotionClient, "_ensure_schema", return_value=schema_override)
        else:
            mocker.patch.object(NotionClient, "_ensure_schema", return_value=_SCHEMA_MOCK)
        return NotionClient(mock_config)

    return _make
