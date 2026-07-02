"""notion_client/api.py — Wrapper minimal de l'API Notion via httpx.

Endpoints utilises :
- GET  /databases/{id}         → schema des colonnes
- POST /search                 → recherche dans la DB
- POST /pages                  → creer une page (item de base)
- PATCH /pages/{page_id}        → mettre a jour une page

Toutes les URLs sont relatives au base_url = https://api.notion.com/v1.
Le /v1 est donc UNIQUEMENT dans le base_url, jamais dans les URLs individuelles.
"""

import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config : charger NOTION_API_KEY et NOTION_DATABASE_ID depuis .env.notion
# ---------------------------------------------------------------------------

def _load_env_vars() -> dict[str, str]:
    """Charger les variables d'environnement depuis .env.notion si dispos."""
    env_path = Path(__file__).parent / ".env.notion"
    env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    # Les vraies variables d'environnement priment sur .env.notion
    for key in ("NOTION_API_KEY", "NOTION_DATABASE_ID"):
        if key not in env:
            env[key] = ""  # laisser vide si non defini - le caller gere
    return env


@dataclass
class NotionConfig:
    api_key: str
    database_id: str


def get_config() -> NotionConfig:
    """Charger la config, lever une erreur si les variables sont manquantes."""
    raw = _load_env_vars()
    key = raw.get("NOTION_API_KEY", "")
    db_id = raw.get("NOTION_DATABASE_ID", "")
    if not key or not db_id:
        raise RuntimeError(
            "NOTION_API_KEY et NOTION_DATABASE_ID sont requis. "
            "Copier .env.notion.example en .env.notion et remplir les valeurs."
        )
    return NotionConfig(api_key=key, database_id=db_id)


# ---------------------------------------------------------------------------
# Client API
# ---------------------------------------------------------------------------

class NotionClient:
    BASE = "https://api.notion.com/v1"

    def __init__(self, config: NotionConfig):
        self._client = httpx.Client(
            base_url=self.BASE,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )
        self._schema: dict | None = None

    # -- schema ---------------------------------------------------------------

    def _ensure_schema(self) -> dict[str, Any]:
        """Charger le schema de la DB (cache au niveau instance)."""
        if self._schema is None:
            db_id = _get_config().database_id
            # URL relative → base_url ajoute /v1 automatiquement
            self._schema = self._request("GET", f"/databases/{db_id}")
        return self._schema

    @property
    def _title_col(self) -> str:
        """Nom de la colonne titre (souvent 'Name' ou 'Nom')."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "title":
                return k
        return "Title"

    @property
    def _status_col(self) -> str:
        """Nom de la colonne Status (souvent 'Status' ou 'Statut')."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "select" and "status" in k.lower():
                return k
        return "Status"

    # -- low-level helpers ----------------------------------------------------

    def _request(self, method: str, url: str, json_body: dict | None = None) -> Any:
        resp = self._client.request(method, url, json=json_body)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Notion API {resp.status_code}: {resp.text!r}"
            )
        return resp.json()

    # -- database ------------------------------------------------------------

    def get_schema(self, database_id: str | None = None) -> dict[str, Any]:
        """Renvoyer le schema complet de la database."""
        target = database_id or _get_config().database_id
        return self._request("GET", f"/databases/{target}")

    def query_items(
        self,
        database_id: str | None = None,
        filter_props: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Renvoyer tous les items de la base (gestion automatique de la pagination)."""
        target = database_id or _get_config().database_id
        items: list[dict[str, Any]] = []
        has_more = False
        start_cursor: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": 100}
            if filter_props is not None:
                params["filter"] = filter_props
            if start_cursor is not None:
                params["start_cursor"] = start_cursor
            # URL relative → base_url ajoute /v1 automatiquement
            result = self._request("POST", f"/databases/{target}/query", json_body=params)
            items.extend(result.get("results", []))
            has_more = result.get("has_more", False)
            if not has_more:
                break
            start_cursor = result.get("next_cursor")

        return items

    # -- pages (items de la DB) ----------------------------------------------

    def create_item(
        self,
        parent_db: str | None = None,
        name: str = "",
        phase: str = "",
        status: str = "En Attente",
        priority: str = "P2",
        source: str = "local",
        extra_props: dict | None = None,
    ) -> str:
        """Creer un item et renvoyer son page_id."""
        title_col = self._title_col
        status_col = self._status_col
        schema = self._ensure_schema()

        # Colonnes optionnelles disponibles dans le schema
        properties: dict[str, Any] = {
            title_col: {"title": [{"text": {"content": name}}]},
        }
        if "Phase" in schema.get("properties", {}):
            properties["Phase"] = {"select": {"name": phase}}
        if status_col in schema.get("properties", {}):
            properties[status_col] = {"select": {"name": status}}
        if "Priority" in schema.get("properties", {}):
            properties["Priority"] = {"select": {"name": priority}}
        if "Source" in schema.get("properties", {}):
            properties["Source"] = {"select": {"name": source}}

        if extra_props:
            properties.update(extra_props)

        parent = parent_db or _get_config().database_id
        # URL relative → base_url ajoute /v1 automatiquement
        result = self._request(
            "POST", "/pages",
            json_body={"parent": {"type": "database_id", "database_id": parent}, "properties": properties},
        )
        return result["id"]

    def update_item(
        self,
        page_id: str,
        name: str | None = None,
        status: str | None = None,
        extra_props: dict | None = None,
    ) -> str:
        """Mettre a jour un item. Renvoie le page_id mis a jour."""
        title_col = self._title_col
        status_col = self._status_col
        properties: dict[str, Any] = {}
        if name is not None:
            properties[title_col] = {"title": [{"text": {"content": name}}]}
        if status is not None and status_col in (self._ensure_schema().get("properties", {})):
            properties[status_col] = {"select": {"name": status}}
        if extra_props:
            properties.update(extra_props)

        # URL relative → base_url ajoute /v1 automatiquement
        self._request(
            "PATCH", f"/pages/{page_id}",
            json_body={"properties": properties},
        )
        return page_id

    # -- search ---------------------------------------------------------------

    def search(self, query: str | None = None, filter_db: dict | None = None) -> list[dict[str, Any]]:
        """Rechercher des pages/documents dans les espaces accessibles."""
        params: dict[str, Any] = {"page_size": 100}
        if query is not None:
            params["query"] = query
        if filter_db is not None:
            params["filter"] = filter_db
        # URL relative → base_url ajoute /v1 automatiquement
        result = self._request("POST", "/search", json_body=params)
        return result.get("results", [])

    # -- schema creation (creation d'une nouvelle base) -----------------------

    @staticmethod
    def create_database_schema(name: str = "Zomboid Tasks") -> dict[str, Any]:
        """Renvoyer le body API pour creer une DB avec le schema recommande.

        Pour l'utiliser :
            client.create_page(parent={"type": "page_id", "page_id": "<parent_page_id>"}, properties={...})

        Ou copier-coller manuellement dans Notion.
        """
        return {
            "parent": {"type": "database"},  # le caller doit ajouter page_id ou parent_db
            "title": [{"type": "text", "text": {"content": name}}],
            "properties": {
                "Name": {"title": {}},
                "Phase": {
                    "select": {
                        "options": [
                            {"name": f"Phase {i}", "color": "blue"} for i in range(1, 12)
                        ] + [{"name": "N/A", "color": "gray"}],
                    }
                },
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Not Started", "color": "red"},
                            {"name": "In Progress", "color": "yellow"},
                            {"name": "Done", "color": "green"},
                        ]
                    }
                },
                "Priority": {
                    "select": {
                        "options": [
                            {"name": "P0", "color": "red"},
                            {"name": "P1", "color": "orange"},
                            {"name": "P2", "color": "blue"},
                            {"name": "P3", "color": "gray"},
                        ]
                    }
                },
                "Source": {
                    "select": {
                        "options": [
                            {"name": "local", "color": "green"},
                            {"name": "manual", "color": "blue"},
                        ]
                    }
                },
            },
        }

    def close(self):
        self._client.close()


# Module-level helper (evite recreation)
_config_instance: NotionConfig | None = None


def _get_config() -> NotionConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = get_config()
    return _config_instance
