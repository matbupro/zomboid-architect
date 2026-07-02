"""notion_client/api.py — Wrapper minimal de l'API Notion via httpx.

Endpoints utilis&#233;s :
- GET  /v1/databases/{id}          → sch&#233;ma des colonnes
- POST /v1/search                 → recherche dans la DB
- POST /v1/pages                  → cr&#233;er une page (item de base)
- PATCH /v1/pages/{page_id}        → mettre &#224; jour une page

Pas besoin d'un SDK complet : l'API Notion est simple et bien document&#233;e.
On g&#232;re la pagination manuellement (page_size=100 par d&#233;faut).
"""

import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config : charger NOTION_API_KEY et NOTION_DATABASE_ID depuis .env.notion
# ---------------------------------------------------------------------------

def _load_env_vars() -> dict[str, str]:
    """Charger les variables d'environnement depuis .env.notion si dispo."""
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
            env[key] = ""  # laisser vide si non d&#233;fini — le caller g&#232;re
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
        """Renvoyer le sch&#233;ma complet de la database."""
        target = database_id or _get_config().database_id
        return self._request("GET", f"/v1/databases/{target}")

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
            result = self._request("POST", f"/v1/databases/{target}/query", json_body=params)
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
        status: str = "Not Started",
        priority: str = "P2",
        source: str = "local",
        extra_props: dict | None = None,
    ) -> str:
        """Cr&#233;er un item et renvoyer son page_id."""
        parent = parent_db or _get_config().database_id
        properties: dict[str, Any] = {
            "Name": {"title": [{"text": {"content": name}}]},
            "Phase": {"select": {"name": phase}},
            "Status": {"select": {"name": status}},
            "Priority": {"select": {"name": priority}},
            "Source": {"select": {"name": source}},
        }
        if extra_props:
            properties.update(extra_props)

        result = self._request(
            "POST", "/v1/pages",
            json_body={"parent": {"type": "database", "database_id": parent}, "properties": properties},
        )
        return result["id"]

    def update_item(
        self,
        page_id: str,
        name: str | None = None,
        status: str | None = None,
        extra_props: dict | None = None,
    ) -> str:
        """Mettre &#224; jour un item. Renvoie le page_id mis &#224; jour."""
        properties: dict[str, Any] = {}
        if name is not None:
            properties["Name"] = {"title": [{"text": {"content": name}}]}
        if status is not None:
            properties["Status"] = {"select": {"name": status}}
        if extra_props:
            properties.update(extra_props)

        self._request(
            "PATCH", f"/v1/pages/{page_id}",
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
        result = self._request("POST", "/v1/search", json_body=params)
        return result.get("results", [])

    # -- schema creation (cr&#233;ation d'une nouvelle base) -------------------

    @staticmethod
    def create_database_schema(name: str = "Zomboid Tasks") -> dict[str, Any]:
        """Renvoyer le body API pour cr&#233;er une DB avec le sch&#233;ma recommand&#233;.

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


# Module-level helper (avite recration)
_config_instance: NotionConfig | None = None


def _get_config() -> NotionConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = get_config()
    return _config_instance
