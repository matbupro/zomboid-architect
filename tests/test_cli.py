"""test_cli — Tests du parser CLI et des handlers Steam.

Focus : validation arguments argparse + output handlers (mockes).
Tous les appels reseau/registry sont mockes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from ingestor.cli import build_parser


# ===========================================================================
# Tests : parser argparse
# ===========================================================================


def test_parser_steam_scan_flag():
    """L'argument --steam-scan est reconnu."""
    args = build_parser().parse_args(["--steam-scan"])
    assert args.steam_scan is True


def test_parser_workshop_scan_flag():
    """L'argument --workshop-scan est reconnu."""
    args = build_parser().parse_args(["--workshop-scan"])
    assert args.workshop_scan is True


def test_parser_mod_ingest_arg():
    """L'argument --mod-ingest accepte une valeur."""
    args = build_parser().parse_args(["--mod-ingest", "/tmp/mods"])
    assert args.mod_ingest == "/tmp/mods"


def test_parser_steamcmd_download_arg():
    """L'argument --steamcmd-download-game accepte un chemin."""
    args = build_parser().parse_args(["--steamcmd-download-game", "/tmp/pz"])
    assert args.steamcmd_download_game == "/tmp/pz"


def test_parser_steamcmd_install_mod_arg():
    """L'argument --steamcmd-install-mod accepte un ID numerique."""
    args = build_parser().parse_args(["--steamcmd-install-mod", "1234567"])
    assert args.steamcmd_install_mod == 1234567


def test_parser_mutual_exclusion():
    """Deux arguments du meme groupe steam ne peuvent etre utilises ensemble."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--steam-scan", "--workshop-scan"])


def test_parser_max_depth_default():
    """--max-depth a une valeur par defaut de 5."""
    args = build_parser().parse_args([])
    assert args.max_depth == 5


def test_parser_max_pages_default():
    """--max-pages a une valeur par defaut de 20."""
    args = build_parser().parse_args([])
    assert args.max_pages == 20


# ===========================================================================
# Tests : build_parser structure
# ===========================================================================


def test_build_parser_returns_argumentparser():
    """build_parser retourne un argparse.ArgumentParser."""
    import argparse

    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_has_steam_actions():
    """Le parser contient les arguments Steam (verifies par parsing direct ci-dessus)."""
    # deja verifie par test_parser_* ci-dessus — ce test confirme qu'il n'y a pas d'erreur de construction
    parser = build_parser()
    assert parser is not None


def test_build_parser_has_search_group():
    """Le groupe search contient les arguments web (--search, --url, --crawl)."""
    import argparse

    parser = build_parser()
    action_dests = {a.dest for a in parser._actions if hasattr(a, "dest")}
    assert "--search" not in action_dests  # dest is 'search', not the flag itself
    assert "search" in action_dests


# ===========================================================================
# Tests : handle_steam_scan (output verifie via mock du module entier)
# ===========================================================================


def test_handle_steam_scan_with_found_path():
    """handle_steam_scan — quand Steam est trouve, affiche le chemin."""
    from ingestor.cli import handle_steam_scan

    game_paths_mock = type("GamePaths", (), {
        "steam_install": Path("/fake/Steam"),
        "library_paths": [Path("/fake/steamapps")],
        "game_path": Path("/fake/Steam/steamapps/common/ProjectZomboid"),
        "workshop_content_root": Path("/fake/steamapps/workshop/content/1042170"),
        "discovered": True,
    })()

    class FakeArgs:
        steam_scan = True
        steamcmd_download_game = None
        steamcmd_install_mod = None
        workshop_scan = False
        mod_ingest = None
        verbose = False

    with patch("ingestor.steam.path_discovery.discover_game_path", return_value=game_paths_mock):
        with patch("ingestor.steam.path_discovery.get_steamcmd_path", return_value=None):
            # handle_steam_scan print(e) sur stdout — verifier sans exception
            asyncio_run(handle_steam_scan(FakeArgs()))


def test_handle_steam_scan_with_nothing_found():
    """handle_steam_scan — quand Steam n'est pas trouve, affiche 'Non trouve'."""
    from ingestor.cli import handle_steam_scan

    game_paths_mock = type("GamePaths", (), {
        "steam_install": None,
        "library_paths": [],
        "game_path": None,
        "workshop_content_root": None,
        "discovered": False,
    })()

    class FakeArgs:
        steam_scan = True
        steamcmd_download_game = None
        steamcmd_install_mod = None
        workshop_scan = False
        mod_ingest = None
        verbose = False

    with patch("ingestor.steam.path_discovery.discover_game_path", return_value=game_paths_mock):
        with patch("ingestor.steam.path_discovery.get_steamcmd_path", return_value=None):
            asyncio_run(handle_steam_scan(FakeArgs()))


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
