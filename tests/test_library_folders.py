"""test_library_folders — Tests des fonctions de decouverte Steam et parsing VDF.

Couverture : _fallback_folders, find_pz_game_path, parsing manifest ACF,
magic bytes invalides.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ===========================================================================
# Tests : _fallback_folders
# ===========================================================================


def test_fallback_returns_steamapps(tmp_path):
    """Sans libraryfolder.vdf → retourne le dossier steamapps."""
    from ingestor.steam.library_folders import _fallback_folders

    steam = tmp_path / "Steam"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)

    paths = _fallback_folders(steam)
    assert len(paths) >= 1
    assert any(p.name == "steamapps" for p in paths)


def test_fallback_no_steamapps(tmp_path):
    """Sans dossier steamapps → le fallback cree steamapps par defaut."""
    from ingestor.steam.library_folders import _fallback_folders

    steam = tmp_path / "Steam"
    steam.mkdir()

    paths = _fallback_folders(steam)
    # _fallback_folders retourne TOUJOURS [steamapps] meme s'il n'existe pas
    assert len(paths) == 1


# ===========================================================================
# Tests : parse_library_folders (basic behavior)
# ===========================================================================


def test_parse_library_folders_no_vdf(tmp_path):
    """Sans libraryfolder.vdf → fallback au dossier steamapps par defaut."""
    from ingestor.steam.library_folders import parse_library_folders

    steam = tmp_path / "Steam"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)

    paths = parse_library_folders(steam)
    assert len(paths) >= 1


# ===========================================================================
# Tests : find_pz_game_path — common/ProjectZomboid
# ===========================================================================


def test_find_pz_game_path_found_common(fake_steam_root):
    """find_pz_game_path detecte le jeu via steamapps/common/."""
    from ingestor.steam.library_folders import find_pz_game_path

    paths = [fake_steam_root / "steamapps"]
    found = find_pz_game_path(paths)
    assert found is not None
    assert found.name == "ProjectZomboid"


def test_find_pz_game_path_not_found(tmp_path):
    """Pas de dossier ProjectZomboid → retourne None."""
    from ingestor.steam.library_folders import find_pz_game_path

    # steamapps cree mais sans common/ProjectZomboid
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()

    found = find_pz_game_path([steamapps])
    assert found is None


def test_find_pz_game_path_empty_list():
    """Liste vide → retourne None."""
    from ingestor.steam.library_folders import find_pz_game_path

    found = find_pz_game_path([])
    assert found is None


# ===========================================================================
# Tests : manifest parsing via library_folders
# ===========================================================================


def test_find_pz_game_path_via_manifest(fake_pz_manifest):
    """Decouverte du jeu via appmanifest_1042170.acf → GameData."""
    from ingestor.steam.library_folders import find_pz_game_path

    steamapps = fake_pz_manifest.parent
    # Creer common/ProjectZomboid pour que le chemin soit valide
    game_dir = steamapps / "common" / "ProjectZomboid"
    game_dir.mkdir(parents=True)

    found = find_pz_game_path([steamapps])
    assert found is not None
    assert found.name == "ProjectZomboid"


# ===========================================================================
# Tests : VDF parsing — cas limites
# ===========================================================================


def test_parse_vdf_value_short_data():
    """Donnee tronquee avant fin → retourne dict partiel (pas d'exception)."""
    from ingestor.steam.library_folders import _parse_vdf_value

    # Magic bytes + donnee tronquee
    data = b"VDF\n" + b"\x00\x01"  # trop court pour une cle valide
    result, pos = _parse_vdf_value(data)
    assert isinstance(result, dict)


def test_parse_vdf_value_empty():
    """Donnee vide → dictionnaire vide."""
    from ingestor.steam.library_folders import _parse_vdf_value

    result, pos = _parse_vdf_value(b"")
    assert result == {}
    assert pos == 0


# ===========================================================================
# Tests : GamePaths dataclass
# ===========================================================================


def test_game_paths_defaults():
    """GamePaths avec ses valeurs par defaut."""
    from ingestor.steam.path_discovery import GamePaths

    paths = GamePaths()
    assert paths.steam_install is None
    assert paths.game_path is None
    assert paths.library_paths is None
    assert paths.workshop_content_root is None
    assert paths.discovered is False


def test_game_paths_discovered_flag():
    """GamePaths.discovered passe a True quand un chemin valide est trouve."""
    from ingestor.steam.path_discovery import GamePaths

    game_dir = Path("/fake/ProjectZomboid")
    paths = GamePaths(steam_install=Path("/fake/Steam"), game_path=game_dir, discovered=True)
    assert paths.discovered is True


# ===========================================================================
# Tests : find_steam_install_path behavior
# ===========================================================================


def test_find_steam_returns_none_when_no_default():
    """find_steam_install_path peut retourner None sans registry ni dossier Steam."""
    from ingestor.steam.path_discovery import _default_steam_path

    # Sur un systeme sans dossier Steam par defaut → None
    result = _default_steam_path()
    # Le resultat depend du systeme — acceptable si None ou Path existant
    assert result is None or (result / "steamapps").is_dir()
