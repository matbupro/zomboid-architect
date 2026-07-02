"""
search — Modules de recherche pour le web crawling.

Order : DuckDuckGo (no API key, prioritaire) → Brave (fallback, requires key).
"""

from .duckduckgo import SearchResult, search, search_and_crawl
from .brave import search as brave_search

__all__ = ["search", "search_and_crawl", "brave_search", "SearchResult"]
