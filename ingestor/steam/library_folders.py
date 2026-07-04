"""
library_folders — Parser du fichier VDF (Valve Data Format) de libraryfolders.vdf.

Ce fichier se trouve dans steamapps/ et liste les bibliotheques Steam multi-disques.
Format binaire simple: magic bytes + paires cle/valeur imbriquees avec nesting.

Structure typique:
    "Libraries" {
        "C:\\Program Files\\Steam\\steamapps" {
            "ContentIter" "2"
        }
        "D:\\SteamLibrary\\steamapps" {
            "ContentIter" "3"
        }
    }
"""

from __future__ import annotations

import struct
from pathlib import Path

from src.governance.logger import get_logger

logger = get_logger(__name__)

# Magic bytes du format VDF binaire (Valve Data Format)
VDF_MAGIC = b"VDF\x0A"


def parse_library_folders(steam_path: Path | str) -> list[Path]:
    """Parse steamapps/libraryfolder.vdf → liste de chemins de bibliotheque.

    Le fichier libraryfolder.vdf est lu depuis le dossier steamapps/.
    Le repertoire contenant ce fichier est toujours inclus en premiere position.

    Args:
        steam_path: Chemin vers le repertoire Steam (ex: C:\\Program Files\\Steam).

    Returns:
        Liste de Path representant les bibliotheques Steam decouvertes.
    """
    steam_path = Path(steam_path)
    vdf_path = steam_path / "steamapps" / "libraryfolder.vdf"

    if not vdf_path.exists():
        logger.warning("libraryfolder.vdf non trouve: %s", vdf_path)
        # Fallback: retourner le repertoire steamapps par defaut
        steamapps = steam_path / "steamapps"
        return [steamapps] if steamapps.exists() else []

    content = vdf_path.read_bytes()
    if len(content) < 4 or content[:4] != VDF_MAGIC:
        logger.warning("libraryfolder.vdf: magic bytes invalides (%s)", content[:8])
        return _fallback_folders(steam_path)

    libraries = _parse_vdf_value(content[4:])  # skip magic bytes
    paths = [Path(steam_path) / "steamapps"]  # always include main steamapps

    for lib_name, lib_data in libraries.items():
        if lib_name == "Libraries":
            # The top-level key contains nested library entries
            if isinstance(lib_data, dict):
                for sub_key in lib_data:
                    try:
                        paths.append(Path(sub_key).resolve())
                    except (OSError, ValueError) as exc:
                        logger.debug("Chemine bibliotheque invalide '%s': %s", sub_key, exc)

    # Remove duplicates while preserving order
    seen = set()
    unique_paths = []
    for p in paths:
        try:
            resolved = p.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique_paths.append(resolved)
        except (OSError, ValueError):
            pass

    return unique_paths


def _parse_vdf_value(data: bytes, offset: int = 0) -> dict[str, object]:
    """Parse a VDF binary value into a dict.

    VDF key-value pairs: length-prefixed string key, then value (string or nested).
    String values are prefixed with their own length.
    Nested dicts start with 0x10 followed by the key.
    """
    result = {}
    pos = offset
    data_len = len(data)

    while pos < data_len:
        # Read key length (u16 LE)
        if pos + 2 > data_len:
            break
        key_len = struct.unpack_from("<H", data, pos)[0]
        pos += 2

        if key_len == 0:
            # Terminator for nested block
            pos += 1  # skip the terminator byte (0x00)
            break

        # Read key string (UTF-8)
        if pos + key_len > data_len:
            break
        key = data[pos : pos + key_len].decode("utf-8", errors="replace")
        pos += key_len

        # Padding to 4-byte boundary
        padding = (4 - key_len % 4) % 4
        if padding < 4:
            pos += padding

        # Check for nested block (0x10 type = dict)
        if pos >= data_len:
            break
        type_byte = data[pos]
        pos += 1

        if type_byte == 0x10:  # Nested dictionary
            child, pos = _parse_vdf_value(data, pos + 1)
            result[key] = child
        elif type_byte == 0x01:  # String value
            str_len = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if pos + str_len > data_len:
                break
            value = data[pos : pos + str_len].decode("utf-8", errors="replace")
            pos += str_len
            # Padding
            padding = (4 - str_len % 4) % 4
            if padding < 4:
                pos += padding
            result[key] = value
        elif type_byte == 0x02:  # String with wider encoding (UTF-16)
            str_len = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if pos + str_len * 2 > data_len:
                break
            value = data[pos : pos + str_len * 2].decode("utf-16le", errors="replace")
            pos += str_len * 2
            padding = (4 - str_len % 4) % 4
            if padding < 4:
                pos += padding
            result[key] = value
        else:
            # Unknown type — skip as empty dict
            logger.debug("Type VDF inconnu 0x%02X pour cle '%s'", type_byte, key)
            result[key] = {}

    return result, pos


def _fallback_folders(steam_path: Path) -> list[Path]:
    """Fallback quand le fichier VDF est corrompu ou absent."""
    paths = [steam_path / "steamapps"]
    # Also check for common libraryfolder naming variants
    for name in ["libraryfolder.vdf", "libraryfolders.vdf", "libraryfolders.vdf"]:
        candidate = steam_path / "steamapps" / name
        if candidate.exists():
            return parse_library_folders(steam_path)  # retry with fallback name
    return paths


# ---------------------------------------------------------------------------
# PZ AppID constant and game path discovery helper
# ---------------------------------------------------------------------------

PZ_APP_ID: int = 1042170
"""Steam AppID pour Project Zomboid."""


def find_pz_game_path(steam_paths: list[Path]) -> Path | None:
    """Recherche le repertoire d'installation de PZ dans toutes les bibliotheques Steam.

    Search order:
        1. steamapps/appmanifest_1042170.acf → GameData key in manifest
        2. steamapps/common/ProjectZomboid

    Args:
        steam_paths: Liste des chemins de bibliotheques Steam (steamapps directories).

    Returns:
        Path vers le dossier du jeu, ou None si non trouve.
    """
    for steamapps in steam_paths:
        # Method 1: Parse appmanifest_1042170.acf for GameData path
        manifest = steamapps / f"appmanifest_{PZ_APP_ID}.acf"
        if manifest.exists():
            game_data = _parse_manifest_game_path(manifest)
            if game_data and Path(game_data).is_dir():
                return Path(game_data)

        # Method 2: Direct common/ProjectZomboid path (classic location)
        pz_path = steamapps / "common" / "ProjectZomboid"
        if pz_path.exists():
            return pz_path

    logger.warning("Project Zomboid non trouve dans %d bibliotheques Steam.", len(steam_paths))
    return None


def _parse_manifest_game_path(manifest_path: Path) -> str | None:
    """Parse an appmanifest_*.acf file to extract the GameData path.

    The ACF file is a key-value text format (not binary VDF).
    We look for the "GameData" key which points to the game directory.
    """
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith('"GameData"'):
                # Extract value between quotes
                parts = line.partition('"')  # skip "GameData"
                val_start = parts[2].strip().strip('"').strip('"')
                if val_start:
                    return val_start
        # Fallback to parent of manifest (common/ location)
        return str(manifest_path.parent.parent / "common" / "ProjectZomboid")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Echec parsing manifest %s: %s", manifest_path.name, exc)
        return None
