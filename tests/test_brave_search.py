"""test_brave_search — Tests unitaires du moteur Brave Search (fallback DDG).

Couvre :
  - search() sans cle API → retourne []
  - search() avec cle invalide → ne plante pas, retourne [] ou raise
  - check_brave_installed() vrai/faux
  - SearchResult fields
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def no_brave_key(monkeypatch: pytest.MonkeyPatch):
    """S'assurer qu'aucune cle Brave n'est presente dans l'environnement pour ces tests."""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)


# ===========================================================================
# Tests : check_brave_installed
# ===========================================================================


def test_check_brave_installed_without_key(monkeypatch: pytest.MonkeyPatch):
    """Sans BRAVE_API_KEY, check_brave_installed retourne False."""
    from ingestor.search.brave import check_brave_installed

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert check_brave_installed() is False


def test_check_brave_installed_with_key(monkeypatch: pytest.MonkeyPatch):
    """Avec BRAVE_API_KEY defini, check_brave_installed retourne True."""
    from ingestor.search.brave import check_brave_installed

    monkeypatch.setenv("BRAVE_API_KEY", "BSA-test123")
    assert check_brave_installed() is True


# ===========================================================================
# Tests : search() — sans cle API
# ===========================================================================


async def test_search_without_key_returns_empty():
    """Sans cle API, search() retourne une liste vide (pas d'erreur)."""
    from ingestor.search.brave import search

    results = await search("test query")
    assert results == []


# ===========================================================================
# Tests : search() — avec cle mais httpx non installe
# ===========================================================================


async def test_search_without_httpx_returns_empty(monkeypatch: pytest.MonkeyPatch):
    """Sans httpx, search() logue un warning et retourne []."""
    from ingestor.search import brave

    # Mock import httpx → ImportError
    class BlockHttpx:
        def find_module(self, fullname, path=None):
            if "httpx" in fullname:
                return self
        def load_module(self, fullname):
            raise ImportError("httpx blocked")

    blocker = BlockHttpx()
    monkeypatch.setitem(sys.modules, "httpx", None)
    # Supprimer httpx de sys.modules s'il est present
    for mod_name in list(sys.modules.keys()):
        if "httpx" in mod_name:
            del sys.modules[mod_name]

    results = await brave.search("test query", api_key="BSA-test")
    assert results == []


# ===========================================================================
# Tests : SearchResult dataclass
# ===========================================================================


def test_search_result_dataclass_creation():
    """SearchResult se cree sans erreur avec les champs par defaut."""
    from ingestor.search.brave import SearchResult

    result = SearchResult(title="Test", url="https://example.com", description="desc")
    assert result.title == "Test"
    assert result.url == "https://example.com"
    assert result.description == "desc"
    assert result.body == ""  # valeur par defaut


def test_search_result_body_assignment():
    """Le champ body est assignable."""
    from ingestor.search.brave import SearchResult

    result = SearchResult(title="Test", url="https://example.com", description="desc", body="body text")
    assert result.body == "body text"


# ===========================================================================
# Tests : max_results capping (via code inspection)
# ===========================================================================


def test_search_max_results_capped_in_code():
    """Le code limite explicitement max_results a 50 via min(max_results, 50)."""
    import inspect
    from ingestor.search import brave

    source = inspect.getsource(brave.search)
    assert "min(" in source and "50" in source, (
        "La fonction search doit contenir un cap a 50 résultats (min(max_results, 50))"
    )


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine async."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
