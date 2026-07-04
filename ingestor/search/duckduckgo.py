"""
duckduckgo — Moteur de recherche DuckDuckGo (no API key required).

Utilise l'API non-officielle DDG via python-duckduckgo-search pour obtenir des URLs,
puis le crawler web (playwright) extrait le contenu de chaque résultat.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.governance.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Un seul résultat de recherche DuckDuckGo."""
    title: str           # Titre de la page
    url: str             # URL source
    description: str     # Extrait/description DDG
    body: str = ""       # Contenu extrait (après crawl, vide par défaut)

    @property
    def domain(self) -> str:
        """Extrait le domaine pour logging et filtering."""
        return urlparse(self.url).netloc


async def search(
    query: str,
    max_results: int = 10,
    region: str | None = None,
) -> list[SearchResult]:
    """Recherche avec DuckDuckGo et retourne les résultats.

    Args:
        query: Terme de recherche.
        max_results: Nombre max de résultats (max 20 pour DDG).
        region: Région DDG (ex: "fr-fr"). None = auto.

    Returns:
        Liste de SearchResult triée par pertinence (ordre DDG).
    """
    max_results = min(max_results, 20)  # DDG max
    logger.info("Recherche DuckDuckGo : '%s' (max=%d)", query, max_results)

    try:
        # ddgs est le nouveau nom de duckduckgo_search (v8+)
        from ddgs import DDGS  # type: ignore[import-not-found]

        results = []
        with DDGS() as ddgs:
            for result in ddgs.text(
                query,  # query en premier arg positionnel (ddgs 9.x)
                max_results=max_results,
                region=region,
                safesearch="moderate",
            ):
                title = result.get("title", "")
                url = result.get("href", "")
                description = result.get("body", result.get("description", ""))

                if not url or not url.startswith(("http://", "https://")):
                    continue

                # Filtrer les résultats évidemment non pertinents (liens raccourcis internes)
                parsed = urlparse(url)
                if not parsed.hostname:
                    logger.warning("URL invalide ignorée : %s", url)
                    continue

                results.append(SearchResult(
                    title=title,
                    url=url,
                    description=description[:500],  # tronquer description DDG
                ))

        logger.info("DuckDuckGo → %d résultats pour '%s'", len(results), query)
        return results

    except ImportError:
        logger.error("duckduckgo-search non installé. pip install duckduckgo-search")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erreur DuckDuckGo : %s", exc)
        raise


async def search_and_crawl(
    query: str,
    max_results: int = 5,
    crawler=None,  # WebProcessor instance (lazy import)
) -> list[SearchResult]:
    """Recherche + extraction de contenu pour chaque résultat DDG.

    Args:
        query: Terme de recherche.
        max_results: Nombre max de pages à extraire.
        crawler: Instance de WebProcessor (pour l'extraction).

    Returns:
        Liste de SearchResult avec body = contenu extrait.
    """
    # Phase 1 : recherche DDG
    results = await search(query, max_results=max_results)

    if not results:
        return []

    # Phase 2 : extraction de chaque URL (crawling séquentiel pour respecter le rate limit)
    if crawler is None:
        from ..processors import web as web_proc  # lazy import — web est dans processors/
        crawler = web_proc.WebProcessor(None)  # type: ignore[arg-type]

    crawled_results: list[SearchResult] = []
    for i, result in enumerate(results):
        if i >= max_results:
            break

        try:
            content = await crawler.extract_url_content(result.url)
            extracted_result = SearchResult(
                title=result.title,
                url=result.url,
                description=result.description,
                body=content[:10_000],  # tronquer à 10k chars pour éviter les OOM
            )
            crawled_results.append(extracted_result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crawl échoué : %s → %s", result.url, exc)

    return crawled_results


def check_ddg_installed() -> bool:
    """Vérifie si la dépendance ddgs (DuckDuckGo) est installée."""
    try:
        from ddgs import DDGS  # noqa: F401
        return True
    except ImportError:
        return False
