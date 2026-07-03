"""
path_discovery — Decouverte du chemin d'installation Steam + Project Zomboid.

Sur Windows: lit la base de registre pour trouver l'instalation Steam,
puis scanne les bibliotheques pour PZ. Fallback aux chemins par defaut.

Chemin standard: C:\\Program Files (x86)\\Steam\\steamapps\\common\\ProjectZomboid
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if sys.platform != "win32":
    # On non-Windows, winreg is unavailable — path discovery returns None.
    # This module still exports the public API for cross-platform compatibility.
    winreg = None  # type: ignore[assignment]
else:
    try:
        import winreg as _winreg

        class _LazyWinreg:
            """Lazy wrapper to avoid hard import of winreg (Windows only)."""

            def __getattribute__(self, name: str) -> object:
                return getattr(_winreg, name)

        winreg = _LazyWinreg()
    except ImportError:
        winreg = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from .library_folders import find_pz_game_path  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class for discovered paths
# ---------------------------------------------------------------------------

@dataclass
class GamePaths:
    """Resultat de la decouverte des chemins Steam + PZ."""

    steam_install: Path | None = None
    game_path: Path | None = None
    library_paths: list[Path] | None = None
    workshop_content_root: Path | None = None
    discovered: bool = False  # True si un chemin valide a ete trouve


# ---------------------------------------------------------------------------
# Steam install path discovery
# ---------------------------------------------------------------------------

def find_steam_install_path() -> Path | None:
    """Decouvre le chemin d'installation de Steam via la base de registre Windows.

    Ordre de priorite:
        1. HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam → InstallPath (Steam 64-bit)
        2. HKCU\\SOFTWARE\\Valve\\Steam → InstallPath (installation utilisateur)

    Returns:
        Path vers le repertoire Steam, ou None si non trouve.
    """
    if winreg is None:
        logger.info("Non-Windows: decouverte Steam via registre impossible.")
        return _default_steam_path()

    # Key 1: HKLM (64-bit Steam)
    for root_key, subkey in [
        (_winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (_winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam"),
    ]:
        try:
            with _winreg.OpenKey(root_key, subkey, 0, _winreg.KEY_READ) as key:
                value, _ = _winreg.QueryValueEx(key, "InstallPath")
                path = Path(value.strip()).resolve()
                if (path / "steamapps").is_dir():
                    logger.info("Steam decouvert via registre (%s): %s", subkey.split("\\")[-1], path)
                    return path
        except OSError as exc:
            logger.debug("Registre non accessible (%s\\%s): %s", root_key, subkey, exc)

    # Fallback to default locations
    return _default_steam_path()


def _default_steam_path() -> Path | None:
    """Fallback aux chemins par defaut de Steam sur Windows."""
    for candidate in [
        Path("C:\\Program Files (x86)\\Steam"),
        Path("C:\\Steam"),
        Path("$HOME").expanduser() / "Steam",
    ]:
        if (candidate / "steamapps").is_dir():
            logger.info("Steam decouvert par defaut: %s", candidate)
            return candidate.resolve()
    return None


# ---------------------------------------------------------------------------
# Combined game path discovery
# ---------------------------------------------------------------------------

def discover_game_path(steam_install: Path | None = None) -> GamePaths:
    """Decouverte complete: Steam → bibliotheques → PZ.

    Args:
        steam_install: Chemin Steam force (optionnel). Si None, auto-decouverte via registre.

    Returns:
        GamePaths avec tous les chemins decouverts.
    """
    from .library_folders import find_pz_game_path, parse_library_folders

    paths = GamePaths()

    # Step 1: Find Steam install
    if steam_install is None:
        steam_install = find_steam_install_path()

    if steam_install is None:
        logger.warning("Steam non trouve — verification manuelle necessaire.")
        return paths

    paths.steam_install = steam_install

    # Step 2: Parse library folders (multi-library support)
    steam_paths = parse_library_folders(steam_install)
    paths.library_paths = steam_paths
    logger.info("%d bibliotheques Steam decouvertes.", len(steam_paths))

    # Step 3: Find PZ game path
    pz_path = find_pz_game_path(steam_paths)
    if pz_path is not None:
        paths.game_path = pz_path
        paths.discovered = True
        logger.info("Project Zomboid trouve: %s", pz_path)

    # Step 4: Set workshop content root
    if paths.game_path is not None:
        # Workshop content is in steamapps/workshop/content/1042170/ relative to Steam root
        # But also check from the game's parent directory
        for sp in steam_paths:
            ws_root = sp / "workshop" / "content" / "1042170"
            if ws_root.exists():
                paths.workshop_content_root = ws_root
                logger.info("Root Workshop trouve: %s", ws_root)
                break

    return paths


def get_steamcmd_path(steam_install: Path | None = None) -> Path | None:
    """Decouvre le chemin de steamcmd.exe.

    Ordre de priorite:
        1. $STEAMCMD_DIR env variable
        2. steam_install/steamcmd/steamcmd.exe
        3. common Steam directory (rare but possible)

    Returns:
        Path vers steamcmd.exe, ou None si non trouve.
    """
    import os

    # Check environment variable first
    steamcmd_dir = os.getenv("STEAMCMD_DIR")
    if steamcmd_dir:
        exe = Path(steamcmd_dir) / "steamcmd.exe"
        if exe.exists():
            return exe.resolve()

    # Check Steam directory
    si = steam_install or find_steam_install_path()
    if si is None:
        return None

    candidates = [
        si / "steamcmd" / "steamcmd.exe",       # standalone steamcmd
        si / "steamapps" / "common" / "SteamCMD" / "steamcmd.exe",  # Steam-workshop installed
        si / "bin" / "steamcmd.exe",              # old location
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    logger.warning("steamcmd.exe non trouve.")
    return None
