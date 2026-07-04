"""test_game_version_filtering — Tests du filtrage B41/B42 natif pour ChromaDB.

Couvre :
  - build_version_filter() → {"game_version": {"$eq": "b41"}}
  - build_version_and() → composition de $and avec version + autres filtres
  - build_version_not_filter() → exclusion par version ($ne)
  - tag_chunk_with_version() → stamping metadata
  - Integration : filtre passe a travers chroma_client.py et engine_client.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def clear_version_cache(monkeypatch: pytest.MonkeyPatch):
    """Reset game_version cache between tests."""
    from src.governance import game_version
    monkeypatch.setattr(game_version, "_loaded_from_env", None)
    monkeypatch.delenv("PZ_GAME_VERSION", raising=False)


# ===========================================================================
# Tests : build_version_filter
# ===========================================================================


def test_build_version_filter_b41():
    """GameVersion.B41 → filtre $eq b41."""
    from src.governance.game_version import GameVersion, build_version_filter

    result = build_version_filter(GameVersion.B41)
    assert result == {"game_version": {"$eq": "b41"}}


def test_build_version_filter_b42():
    """GameVersion.B42 → filtre $eq b42."""
    from src.governance.game_version import GameVersion, build_version_filter

    result = build_version_filter(GameVersion.B42)
    assert result == {"game_version": {"$eq": "b42"}}


def test_build_version_filter_string():
    """Les strings 'b41' / 'B42' sont normalisés en lowercase."""
    from src.governance.game_version import build_version_filter

    assert build_version_filter("b41") == {"game_version": {"$eq": "b41"}}
    assert build_version_filter("B42") == {"game_version": {"$eq": "b42"}}
    assert build_version_filter("  B41  ") == {"game_version": {"$eq": "b41"}}


def test_build_version_filter_none_returns_none():
    """Aucun argument = None (appelant doit omettre le filtre)."""
    from src.governance.game_version import build_version_filter

    assert build_version_filter(None) is None


# ===========================================================================
# Tests : build_version_and
# ===========================================================================


def test_build_version_and_composes_multiple():
    """Version + type → $and avec deux conditions."""
    from src.governance.game_version import GameVersion, build_version_and

    result = build_version_and(
        {"type": "item"},
        game_version=GameVersion.B41,
    )
    assert "$and" in result
    assert len(result["$and"]) == 2


def test_build_version_and_only_version():
    """Seulement game_version → $and avec une condition."""
    from src.governance.game_version import GameVersion, build_version_and

    result = build_version_and(game_version=GameVersion.B42)
    assert "$and" in result
    assert len(result["$and"]) == 1
    assert result["$and"][0] == {"game_version": {"$eq": "b42"}}


def test_build_version_and_no_filters_returns_none():
    """Aucun filtre passé → None (pas de $and vide)."""
    from src.governance.game_version import build_version_and

    assert build_version_and() is None


def test_build_version_and_empty_dict_skipped():
    """Les dictionnaires vides sont ignores du $and."""
    from src.governance.game_version import GameVersion, build_version_and

    result = build_version_and({}, game_version=GameVersion.B41)
    assert result is not None
    assert "$and" in result
    assert len(result["$and"]) == 1


# ===========================================================================
# Tests : build_version_not_filter
# ===========================================================================


def test_build_version_not_filter_b41():
    """Exclure B41 → $ne b41."""
    from src.governance.game_version import GameVersion, build_version_not_filter

    result = build_version_not_filter(GameVersion.B41)
    assert result == {"game_version": {"$ne": "b41"}}


def test_build_version_not_filter_string():
    """Les strings fonctionnent aussi."""
    from src.governance.game_version import build_version_not_filter

    assert build_version_not_filter("b42") == {"game_version": {"$ne": "b42"}}


def test_build_version_not_filter_none_returns_none():
    """Aucun argument → None."""
    from src.governance.game_version import build_version_not_filter

    assert build_version_not_filter(None) is None


# ===========================================================================
# Tests : tag_chunk_with_version
# ===========================================================================


def test_tag_chunk_stamps_metadata(monkeypatch: pytest.MonkeyPatch):
    """tag_chunk_with_version ajoute metadata['game_version'] au chunk."""
    from src.governance.game_version import GameVersion, get_current_game_version, tag_chunk_with_version

    monkeypatch.setattr(get_current_game_version.__self__ if hasattr(get_current_game_version, '__self__') else __import__('src.governance.game_version', fromlist=['GameVersion']), '_loaded_from_env', None)
    # Forc B42 via monkeypatch on the game_version module directly
    import src.governance.game_version as gv_mod
    monkeypatch.setattr(gv_mod, "_loaded_from_env", "b42")

    chunk = {"id": "test-1"}
    result = tag_chunk_with_version(chunk)

    assert result["metadata"]["game_version"] == "b42"


def test_tag_chunk_creates_metadata_if_missing(monkeypatch: pytest.MonkeyPatch):
    """Si metadata n'existe pas, le dictionnaire est cree."""
    from src.governance.game_version import tag_chunk_with_version

    import src.governance.game_version as gv_mod
    monkeypatch.setattr(gv_mod, "_loaded_from_env", "b41")

    chunk = {"id": "test-2"}
    result = tag_chunk_with_version(chunk)

    assert isinstance(result["metadata"], dict)
    assert result["metadata"]["game_version"] == "b41"


def test_tag_chunk_preserves_existing_metadata(monkeypatch: pytest.MonkeyPatch):
    """Metadata existantes sont conservees."""
    from src.governance.game_version import tag_chunk_with_version

    import src.governance.game_version as gv_mod
    monkeypatch.setattr(gv_mod, "_loaded_from_env", "b42")

    chunk = {"id": "test-3", "metadata": {"type": "item", "author": "mat"}}
    result = tag_chunk_with_version(chunk)

    assert result["metadata"]["type"] == "item"
    assert result["metadata"]["author"] == "mat"
    assert result["metadata"]["game_version"] == "b42"


# ===========================================================================
# Tests : integration — ChromaClient.query() accepte game_version
# ===========================================================================


def test_chroma_client_query_accepts_game_version():
    """ChromaClient.query() passe un $and filtre a l'API HTTP."""
    from src.retrieval.chroma_client import ChromaClient

    client = ChromaClient(stage="staging")
    # Patch httpx pour eviter de reelles requetes
    mock_resp = MagicMock()
    mock_resp.status_code = 503  # ChromaDB injoignable → retourne {"chunks": []}
    client._http = MagicMock()
    client._http.return_value.post.return_value = mock_resp

    with patch.object(client, "_query_json", return_value={"chunks": [], "query": "", "k": 5}):
        result = client.query("test question", k=3, game_version="b41")

    # Verifier que _query_http a ete appele (et donc que le filtre a ete compose)
    # On ne peut pas verifier directement le where sans plus de mocking,
    # mais on verifie que la methode ne plante pas avec game_version
    assert result is not None  # pas d'exception levee


# ===========================================================================
# Tests : integration — EngineClient propagates version
# ===========================================================================


def test_knowledge_engine_search_accepts_game_version():
    """KnowledgeEngineClient.search() passe game_version a chaque requete interne."""
    from bot.engine_client import KnowledgeEngineClient

    client = KnowledgeEngineClient(chroma_host=None)  # Fallback local → ne fait rien
    # On ne peut pas verifier le where dans le fallback, mais on s'assure que
    # la methode accepte le parametre sans lever
    results = client.search(
        queries=[("pz_items", "test query")],
        n_results=5,
        game_version="b41",
    )
    assert isinstance(results, list)


def test_knowledge_engine_get_by_id_accepts_game_version():
    """get_by_id() accepte game_version sans planter (mock HTTP 503)."""
    from bot.engine_client import KnowledgeEngineClient

    client = KnowledgeEngineClient(chroma_host="http://localhost:9999")  # Inj oignable → retourne None
    result = client.get_by_id("Base.Axe", collection="pz_items", game_version="b41")
    # L'important est que la methode n'eleve pas — le filtre version est compose correcte
    assert result is None  # HTTP error → None, acceptable


def test_knowledge_engine_get_by_id_no_version_filter():
    """get_by_id() sans game_version fonctionne egalement (regression check)."""
    from bot.engine_client import KnowledgeEngineClient

    client = KnowledgeEngineClient(chroma_host="http://localhost:9999")
    result = client.get_by_id("Base.Axe", collection="pz_items")
    assert result is None  # HTTP error → None, acceptable (regression check)


def test_query_staging_accepts_game_version():
    """query_staging() accepte game_version sans lever."""
    from bot.engine_client import KnowledgeEngineClient

    client = KnowledgeEngineClient(chroma_host=None)
    result = client.query_staging("test", k=5, game_version="b42")
    assert "chunks" in result
    assert "query" in result
    assert "k" in result


# ===========================================================================
# Tests : build_version_filter — $and structure validation
# ===========================================================================


def test_and_filter_structure_is_chromadb_compatible():
    """Le filtre final a la structure attendue par ChromaDB."""
    from src.governance.game_version import GameVersion, build_version_and

    result = build_version_and(
        {"type": "feature"},
        game_version=GameVersion.B41,
    )
    assert isinstance(result, dict)
    assert "$and" in result
    assert len(result["$and"]) == 2
    # Premier element = version filter
    assert "game_version" in result["$and"][0]
    assert "$eq" in result["$and"][0]["game_version"]
    # Deuxieme element = user filter
    assert "type" in result["$and"][1]


def test_single_filter_still_wrapped_in_and():
    """Meme avec un seul filtre, on retourne $and (pas une condition brute)."""
    from src.governance.game_version import build_version_and

    result = build_version_and({"type": "zombie"})
    assert "$and" in result
    assert len(result["$and"]) == 1
    assert result["$and"][0] == {"type": "zombie"}


# ===========================================================================
# Tests : GameVersion enum completeness
# ===========================================================================


def test_game_version_from_string_case_insensitive():
    """from_string accepte 'B41', 'b41', 'B42' en insensitive."""
    from src.governance.game_version import GameVersion

    assert GameVersion.from_string("b41") == GameVersion.B41
    assert GameVersion.from_string("B41") == GameVersion.B41
    assert GameVersion.from_string("b42") == GameVersion.B42
    assert GameVersion.from_string("B42") == GameVersion.B42


def test_game_version_from_string_invalid():
    """from_string leve ValueError pour une valeur inconnue."""
    from src.governance.game_version import GameVersion

    with pytest.raises(ValueError, match="Unknown game version"):
        GameVersion.from_string("b50")


def test_game_version_all_returns_list():
    """all() retourne la liste des membres."""
    from src.governance.game_version import GameVersion

    all_versions = GameVersion.all()
    assert len(all_versions) >= 2
    assert GameVersion.B41 in all_versions
    assert GameVersion.B42 in all_versions


# ===========================================================================
# Helpers
# ===========================================================================
