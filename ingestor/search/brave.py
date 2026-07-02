"""
brave — Moteur de recherche Brave Search en fallback (gratuit, API key nécessaire).

Le plan gratuit donne 2000 requêtes/mois. Si pas de clé Brave, on retourne une liste vide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Un seul résultat Brave Search."""
    title: str
    url: str
    description: str
    body: str = ""


async def search(
    query: str,
    max_results: int = 10,
    api_key: str | None = None,
) -> list[SearchResult]:
    """Recherche via Brave Search API (fallback quand DDG échoue).

    Args:
        query: Terme de recherche.
        max_results: Nombre max de résultats.
        api_key: Clé API Brave (optionnelle — si None, retourne [].

    Returns:
        Liste de SearchResult.
    """
    if not api_key:
        logger.info("Brave Search : pas de clé API configurée.")
        return []

    max_results = min(max_results, 50)

    try:
        import httpx

        url = "https://api.search.brave.com/res/v1/web/search"
        params = {
            "q": query,
            "count": max_results,
            "freshness": "pw",  # past week
        }
        headers = {
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        web_results = data.get("web", {}).get("results", [])

        for item in web_results[:max_results]:
            title = item.get("title", "")
            url = item.get("url", "")
            description = item.get("description", "")

            if not url:
                continue

            results.append(SearchResult(
                title=title,
                url=url,
                description=description[:500],
            ))

        return results

    except ImportError:
        logger.warning("httpx manquant pour Brave Search.")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Brave Search error: %s", exc)
        return []


def check_brave_installed() -> bool:
    """Vérifie si une clé API Brave est configurée."""
    import os
    return bool(os.getenv("BRAVE_API_KEY"))
