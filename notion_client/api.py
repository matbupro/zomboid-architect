"""notion_client/api.py — Wrapper minimal de l'API Notion via httpx.

Endpoints utilises :
- GET  /databases/{id}         -> schema des colonnes
- POST /search                 -> recherche dans la DB
- POST /pages                  -> creer une page (item de base)
- PATCH /pages/{page_id}        -> mettre a jour une page

Toutes les URLs sont relatives au base_url = https://api.notion.com/v1.
Le /v1 est donc UNIQUEMENT dans le base_url, jamais dans les URLs individuelles.
"""

import os
import sys
import time

import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Rate limiting — retry strategy pour le rate limiting Notion (429)
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
INITIAL_BACKOFF: float = 1.0  # secondes, exponential backoff


# ---------------------------------------------------------------------------
# Config : charger NOTION_API_KEY et NOTION_DATABASE_ID depuis .env.notion
# ---------------------------------------------------------------------------

def _load_env_vars() -> dict[str, str]:
    """Charger les variables depuis .env.unified (racine du projet)."""
    env: dict[str, str] = {}
    # Source de vérité : .env.unified à la racine du projet
    env_path = Path(__file__).parent.parent / ".env.unified"
    if not env_path.exists():
        # fallback : cherche .env.notion localement ou .env à la racine
        for alt in [Path(__file__).parent / ".env.notion", Path(__file__).parent.parent / ".env"]:
            if alt.exists():
                env_path = alt
                break
    if not env_path.exists():
        return {}  # aucune source trouvée, les vraies env vars priment
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    # Les vraies variables d'environnement priment sur .env.unified
    for key in ("NOTION_API_KEY", "NOTION_DATABASE_ID"):
        if key not in env:
            env[key] = os.environ.get(key, "")  # fallback vers le systeme
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
            self._schema = self._request("GET", f"/databases/{db_id}")
        return self._schema

    @property
    def _title_col(self) -> str:
        """Nom de la colonne titre."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "title":
                return k
        return "Title"

    @property
    def _status_col(self) -> str:
        """Nom de la colonne Status (select contenant 'status')."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "select" and "status" in k.lower():
                return k
        return "Status"

    @property
    def _phase_col(self) -> str | None:
        """Nom de la colonne Phase (select contenant 'phase'), ou None."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "select" and "phase" in k.lower():
                return k
        return None

    @property
    def _priority_col(self) -> str | None:
        """Nom de la colonne Priority (select contenant 'priorit'), ou None."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "select" and "priorit" in k.lower():
                return k
        return None

    @property
    def _source_col(self) -> str | None:
        """Nom de la colonne Source (select contenant 'source'), ou None."""
        schema = self._ensure_schema()
        for k, v in schema.get("properties", {}).items():
            if v.get("type") == "select" and "source" in k.lower():
                return k
        return None

    # -- low-level helpers ----------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        json_body: dict | None = None,
        retry_count: int = 0,
    ) -> Any:
        """Effectuer une requête HTTP vers Notion API avec gestion du rate limiting.

        En cas de 429 (Too Many Requests), attend et réessaye
        jusqu'à MAX_RETRIES avec exponential backoff.
        """
        try:
            resp = self._client.request(method, url, json=json_body)

            # Rate limiting — retry exponentiel
            if resp.status_code == 429 and retry_count < MAX_RETRIES:
                backoff = INITIAL_BACKOFF * (2 ** retry_count)
                print(
                    f"⚠️  Rate limited. Attente {backoff}s "
                    f"(réessay {retry_count + 1}/{MAX_RETRIES}...)",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                return self._request(method, url, json_body, retry_count + 1)

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Notion API {resp.status_code}: {resp.text!r}"
                )
            return resp.json()

        except httpx.HTTPError as e:
            raise RuntimeError(f"Notion API error ({method} {url}): {e}") from e

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
        status: str = "Not Started",
        priority: str = "P3",
        source: str = "local",
        extra_props: dict | None = None,
    ) -> str:
        """Creer un item et renvoyer son page_id.

        Les colonnes sont detectees par leur type dans le schema :
        - title -> colonne titre
        - select "Phase" -> phase
        - select "Status" (ou contenant "status") -> status
        - select "Priority" (ou contenant "priorit") -> priority
        - select "Source" (ou contenant "source") -> source
        """
        schema = self._ensure_schema()
        props: dict[str, Any] = {}

        # Titre
        props[self._title_col] = {"title": [{"text": {"content": name}}]}

        # Phase (detectee dynamiquement)
        phase_col = self._phase_col
        if phase_col and phase:
            props[phase_col] = {"select": {"name": phase}}

        # Status (detecte via "status" dans le nom)
        if status and self._status_col:
            props[self._status_col] = {"select": {"name": status}}

        # Priority (detectee dynamiquement)
        priority_col = self._priority_col
        if priority_col and priority:
            props[priority_col] = {"select": {"name": priority}}

        # Source (detectee dynamiquement)
        source_col = self._source_col
        if source_col and source:
            props[source_col] = {"select": {"name": source}}

        if extra_props:
            props.update(extra_props)

        parent = parent_db or _get_config().database_id
        result = self._request(
            "POST", "/pages",
            json_body={"parent": {"type": "database_id", "database_id": parent}, "properties": props},
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
        properties: dict[str, Any] = {}
        if name is not None:
            properties[self._title_col] = {"title": [{"text": {"content": name}}]}
        if status is not None and self._status_col:
            properties[self._status_col] = {"select": {"name": status}}
        if extra_props:
            properties.update(extra_props)

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
        result = self._request("POST", "/search", json_body=params)
        return result.get("results", [])

    # -- schema creation (creation d'une nouvelle base) -----------------------

    @staticmethod
    def create_database_schema(name: str = "Zomboid Tasks") -> dict[str, Any]:
        """Renvoyer la definition du schema pour creer une DB Notion.

        Ce dict est destine a etre copier-coller manuellement dans l'API REST Notion :
            POST /databases
            {
              "parent": {"type": "workspace"},
              "title": [...],
              "properties": {...}
            }

        Ou visualiser avec `python -m notion_client --create-schema`.
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
                            {"name": "manuel", "color": "blue"},
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
