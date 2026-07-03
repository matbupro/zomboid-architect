"""
steam — Integration Steam pour Project Zomboid.

Modules:
  path_discovery   → Découverte chemin Steam + PZ (registry, libraryfolders.vdf)
  steamcmd_client  → Wrapper CLI de steamcmd.exe (download game / workshop mods)
  workshop_scanner → Scan des mods installes depuis steamapps/workshop/content/1042170/
  mod_ingester     → Pipeline haut-niveau: scan → extraction → ingestion ChromaDB
"""

from .path_discovery import discover_game_path, find_steam_install_path
from .steamcmd_client import SteamCMDClient
from .workshop_scanner import WorkshopScanner, WorkshopModInfo
from .mod_ingester import ingest_mods_from_directory, ingest_single_mod

__all__ = [
    "discover_game_path",
    "find_steam_install_path",
    "SteamCMDClient",
    "WorkshopScanner",
    "WorkshopModInfo",
    "ingest_mods_from_directory",
    "ingest_single_mod",
]
