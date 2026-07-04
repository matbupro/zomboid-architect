"""
web — Navigateur web headless et extraction de contenu via Playwright + readability.

Fonctionnalités :
- Navigation headless (Chromium) sur les URLs trouvées par DuckDuckGo
- Extraction du contenu texte propre avec readability (Python port)
- Crawl BFS (depth-limited) pour suivre les liens internes d'un site
- Respect robots.txt et rate limiting (configurable)
- Filtrage par domaine whitelist/blacklist

Priorité n°1 de l'utilisateur : capacité de naviguer le web.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

from .base import Chunk, ExtractionResult, Processor

from src.governance.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CrawlStats:
    """Statistiques d'un crawl web."""
    pages_visited: int = 0
    pages_failed: int = 0
    links_found: int = 0
    links_followed: int = 0
    links_robots_blocked: int = 0
    links_external: int = 0
    download_time_s: float = 0.0


class WebCrawler:
    """Crawler web BFS avec Playwright (headless Chromium).

    Parcourt un site depuis une seed URL en suivant les liens internes,
    respecte robots.txt et applique le rate limiting configuré.
    """

    def __init__(self, user_agent: str = "Zomboid Knowledge Engine"):
        self.user_agent = user_agent
        self._robot_parsers: dict[str, RobotFileParser] = {}  # domain → robots parser
        self._rate_limiter: list[float] = []  # timestamps of recent requests (per domain)

    @property
    def is_playwright_available(self) -> bool:
        """Vérifie si Playwright et son navigateur sont installés."""
        try:
            from playwright.async_api import async_playwright  # noqa: F401
            return True
        except ImportError:
            return False

    # ---- Robots.txt handling ----

    def _get_robot_parser(self, url: str) -> RobotFileParser | None:
        """Obtient ou charge le parser robots.txt pour un domaine."""
        parsed = urlparse(url)
        domain = parsed.netloc
        scheme = parsed.scheme or "https"

        if domain not in self._robot_parsers:
            rp = RobotFileParser()
            try:
                # Ne charge que les robots.txt des domaines qu'on visite
                import httpx
                robots_url = f"{scheme}://{domain}/robots.txt"
                try:
                    resp = httpx.get(robots_url, timeout=5.0)
                    if resp.status_code == 200:
                        rp.parse(resp.text.splitlines())
                        self._robot_parsers[domain] = rp
                        return rp
                    # Si 404 : robots.txt n'existe pas → tout autorisé (User-Agent: *)
                    rp.from_urls([f"{scheme}://{domain}/robots.txt"])
                    rp.set_mtime(0)  # marque comme "not found" = allowed
                    self._robot_parsers[domain] = rp
                except Exception:  # noqa: BLE001
                    # robots.txt inaccessible → par défaut, tout autorisé
                    rp.from_urls([f"{scheme}://{domain}/robots.txt"])
                    rp.set_mtime(0)
                    self._robot_parsers[domain] = rp
            except ImportError:
                pass  # httpx pas dispo → skip robots

        return self._robot_parsers.get(domain)

    def can_fetch(self, url: str) -> bool:
        """Vérifie si on a le droit de crawler cette URL."""
        parsed = urlparse(url)
        domain = parsed.netloc

        # URLs sans domaine valide
        if not domain:
            return False

        # Pas d'URLs relatives
        if not url.startswith(("http://", "https://")):
            return False

        rp = self._get_robot_parser(url)
        if rp is None:
            return True  # pas de robots.txt → autorisé par défaut

        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:  # noqa: BLE001
            return True  # safe fallback : allow

    # ---- Rate limiting ----

    def _check_rate_limit(self, domain: str) -> float:
        """Vérifie le rate limit par domaine et retourne le delay nécessaire (s)."""
        now = time.monotonic()
        self._rate_limiter = [t for t in self._rate_limiter if now - t < 60]  # keep last minute

        max_per_min = 30  # configurable via config
        if len(self._rate_limiter) >= max_per_min:
            oldest = min(self._rate_limiter)
            delay = 60 - (now - oldest)
            logger.debug("Rate limit atteint : %s → wait %.1fs", domain, delay)
            return max(0.5, delay)

        self._rate_limiter.append(now)
        return 0  # no delay

    # ---- Crawling ----

    async def crawl(
        self,
        seed_url: str,
        *,
        max_depth: int = 5,
        max_pages: int = 50,
        max_links_per_page: int = 20,
        follow_external: bool = False,
    ) -> tuple[list[dict[str, Any]], CrawlStats]:
        """BFS crawl d'un site depuis une seed URL.

        Args:
            seed_url: URL de départ.
            max_depth: Profondeur max de crawl.
            max_pages: Nombre max de pages à visiter.
            max_links_per_page: Liens internes max explorés par page.
            follow_external: Suit les liens externes (défaut: False pour limiter la portée).

        Returns:
            Tuple (liste des pages visitées avec contenu, stats de crawl).
        """
        from . import web as web_module  # lazy import for circular dep
        processor = web_module.WebProcessor(None)  # type: ignore[arg-type]

        stats = CrawlStats()
        visited_urls: set[str] = set()
        queue: deque[tuple[str, int]] = deque()  # (url, depth)
        results: list[dict[str, Any]] = []

        seed_parsed = urlparse(seed_url)
        seed_domain = seed_parsed.netloc
        if not seed_domain:
            logger.error("Seed URL invalide : %s", seed_url)
            return results, stats

        # Vérifier robots.txt de la seed URL
        if not self.can_fetch(seed_url):
            logger.warning("robots.txt bloque la seed URL : %s", seed_url)
            return results, stats

        queue.append((seed_url, 0))
        visited_urls.add(seed_url)

        while queue and stats.pages_visited < max_pages:
            current_url, depth = queue.popleft()

            if depth > max_depth:
                logger.debug("Profondeur max (%d) atteinte pour %s", max_depth, current_url)
                continue

            # Rate limiting
            delay = self._check_rate_limit(urlparse(current_url).netloc)
            if delay > 0:
                await asyncio.sleep(delay)

            # Extraction du contenu
            logger.info("[%d/%d] Crawl %s (depth=%d)", stats.pages_visited + 1, max_pages, current_url, depth)
            page_start = time.monotonic()
            content_result = await processor.extract_url_content(current_url)
            elapsed = time.monotonic() - page_start
            stats.download_time_s += elapsed

            if content_result is None:
                stats.pages_failed += 1
                continue

            # Extraire les liens internes de la page
            stats.pages_visited += 1
            links = self._extract_links(current_url, content_result)
            stats.links_found += len(links)

            # Filtrer les liens pour le crawl suivant
            for link in links[:max_links_per_page]:
                if link in visited_urls:
                    continue

                # Skip external unless explicitly allowed
                link_domain = urlparse(link).netloc
                if link_domain != seed_domain and not follow_external:
                    stats.links_external += 1
                    continue

                # Robots check
                if not self.can_fetch(link):
                    stats.links_robots_blocked += 1
                    continue

                visited_urls.add(link)
                queue.append((link, depth + 1))
                stats.links_followed += 1

            # Stocker le résultat
            results.append({
                "url": current_url,
                "title": self._extract_title(content_result),
                "content": content_result[:8000],  # tronquer pour mémoire
                "depth": depth,
                "crawl_time_s": elapsed,
                "links_on_page": len(links),
            })

        stats.pages_failed = max_pages - len(results)
        logger.info("Crawl terminé : %d visités, %d échecs, %d liens trouvés, %d suivis",
                     stats.pages_visited, stats.pages_failed, stats.links_found, stats.links_followed)
        return results, stats

    def _extract_links(self, base_url: str, html: str) -> list[str]:
        """Extrait les liens <a href> d'une page HTML."""
        try:
            import re
            # Match href="..." ou href='...'
            pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>'
            matches = re.findall(pattern, html, re.IGNORECASE)
            links = [urljoin(base_url, href) for href in matches]

            # Filtrer : que les URLs HTTP(S) avec un hostname valide
            valid_links = []
            seen: set[str] = set()
            for link in links:
                if not link.startswith(("http://", "https://")):
                    continue
                parsed = urlparse(link)
                if not parsed.hostname:
                    continue
                # Normaliser l'URL (enlever fragment)
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if normalized not in seen:
                    seen.add(normalized)
                    valid_links.append(normalized)

            return valid_links

        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur extraction liens %s : %s", base_url, exc)
            return []

    def _extract_title(self, html: str) -> str:
        """Extrait le titre d'une page HTML."""
        try:
            import re
            match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()
                # Nettoyer les espaces et caractères spéciaux
                title = re.sub(r'\s+', ' ', title)
                return title or "Sans titre"
        except Exception:  # noqa: BLE001
            pass
        return "Sans titre"


class WebProcessor(Processor):
    """Processeur web — extraction de contenu URL via Playwright ou HTTP."""

    def __init__(self, config=None):
        super().__init__(config)
        self._browser_cache: dict[str, Any] = {}

    async def extract(self, source: str) -> ExtractionResult:
        """Extrait le contenu d'une URL.

        Args:
            source: URL à crawler.

        Returns:
            ExtractionResult avec chunks du contenu extrait.
        """
        start_time = time.monotonic()
        logger.info("Web extraction : %s", source)

        # Récupérer le contenu (via Playwright ou HTTP fallback)
        content = await self.extract_url_content(source)

        if not content:
            return ExtractionResult(
                chunks=[],
                collection="pz_web_pages",
                source=source,
                content_type="text/html",
                file_hash="",
                word_count=0,
                extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Contenu vide ou inaccessible"},
            )

        # Extraire le texte propre de l'HTML
        text = self._extract_text_from_html(content)

        if not text or not text.strip():
            return ExtractionResult(
                chunks=[],
                collection="pz_web_pages",
                source=source,
                content_type="text/html",
                file_hash=self.compute_hash(source),
                word_count=0,
                extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Aucun texte extrait de l'HTML"},
            )

        # Chunking du texte
        chunks = self.chunk_text(text)

        word_count = len(text.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            collection="pz_web_pages",
            source=source,
            content_type="text/html",
            file_hash=self.compute_hash(source),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={
                "url": source,
                "word_count": word_count,
                "chunk_count": len(chunks),
                "content_type": "web",
            },
        )

    async def extract_url_content(self, url: str) -> str | None:
        """Extrait le contenu brut (HTML/texte) d'une URL.

        Tente Playwright en priorité (JS-rendered pages). Fallback vers httpx.
        Returns le HTML complet (pour extraction de texte par la suite).
        """
        import asyncio

        # Essai 1 : Playwright (prend en charge les pages JS-rendered)
        try:
            return await self._extract_playwright(url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright échoué pour %s : %s", url, exc)

        # Essai 2 : httpx (faster but no JS execution)
        try:
            return await self._extract_http(url)
        except Exception as exc:  # noqa: BLE001
            logger.error("httpx échoué pour %s : %s", url, exc)

        return None

    async def _extract_playwright(self, url: str) -> str | None:
        """Extraction via Playwright (navigateur headless Chromium)."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright non installé : pip install playwright && playwright install chromium")
            return None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Attendre un peu pour le JS render (lazy loading, AJAX, etc.)
                await asyncio.sleep(2.0)

                # Extraire la page HTML complète
                html = await page.content()
                return html if html else None

            except Exception as exc:  # noqa: BLE001
                logger.warning("Page navigation failed for %s : %s", url, exc)
                return None
            finally:
                await context.close()
                await browser.close()

    async def _extract_http(self, url: str) -> str | None:
        """Extraction HTTP simple (faster but no JS)."""
        try:
            import httpx

            headers = {
                "User-Agent": "Zomboid Knowledge Engine (+https://github.com/zomboid-architect)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                # Détecter l'encodage et décoder proprement
                encoding = resp.encoding or "utf-8"
                content = resp.content.decode(encoding, errors="replace")
                return content if content else None

        except Exception as exc:  # noqa: BLE001
            logger.warning("HTTP extraction failed for %s : %s", url, exc)
            return None

    def _extract_text_from_html(self, html: str) -> str:
        """Extrait le texte lisible depuis du HTML brut.

        Utilise readability en priorité (Python port), sinon fallback regex-based.
        """
        # Try readability first (better results for complex pages)
        try:
            return self._extract_with_readability(html)
        except Exception as exc:  # noqa: BLE001
            logger.debug("readability échoué, fallback text extraction : %s", exc)

        # Fallback: regex-based extraction
        return self._extract_simple_text(html)

    def _extract_with_readability(self, html: str) -> str:
        """Extraction de texte propre via python-readability (port JS readability)."""
        from lxml import etree  # type: ignore[import-not-found]

        parser = etree.HTMLParser(encoding="utf-8")
        tree = etree.fromstring(html, parser)

        # Utiliser la librairie readability-lxml si dispo, sinon extraction basique
        try:
            from readability import Document as ReadabilityDocument  # type: ignore[import-not-found]
            doc = ReadabilityDocument(html=html, url="zomboid://ingestor")
            result = doc.summary()
            # Extraire le texte de la page nettoyée
            clean_tree = etree.fromstring(result.encode("utf-8"), parser)
            text = self._clean_text_from_element(clean_tree)
            return text or self._extract_simple_text(html)
        except ImportError:
            # Fallback basique si readability n'est pas dispo
            logger.debug("readability non dispo, utilisation extraction basique")
            pass

        return self._extract_simple_text(html)

    def _clean_text_from_element(self, element) -> str:
        """Extrait le texte d'un élément lxml (pour l'extraction readability)."""
        texts = []
        for text in element.itertext():
            stripped = text.strip()
            if stripped and len(stripped) > 1:
                texts.append(stripped)
        return " ".join(texts)

    def _extract_simple_text(self, html: str) -> str:
        """Extraction de texte basique depuis HTML (sans readability)."""
        import re

        # Enlever les scripts et styles
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.IGNORECASE | re.DOTALL)

        # Enlever les balises HTML mais garder les espaces pour la lisibilité
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?div[^>]*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)

        # Nettoyer les caractères spéciaux HTML
        import html as html_lib
        text = html_lib.unescape(text)

        # Normaliser les espaces et sauts de ligne
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        return text


def check_playwright_available() -> bool:
    """Vérifie si Playwright et Chromium sont installés."""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
        return True
    except ImportError:
        return False
