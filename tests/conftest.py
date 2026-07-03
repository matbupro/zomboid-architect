"""conftest -- Fixtures pytest partagees pour les tests Steam.

Toutes les fixtures utilisent tempfile.TemporaryDirectory via tmp_path (pytest builtin).
Aucune dependance externe — tout fonctionne en mode mock.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

# Project root = parent of tests/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_addoninfo(folder: Path, name: str = "Test Mod", author: str = "Tester", description: str = "A test mod") -> Path:
    """Ecrire un addoninfo.txt standard Valve dans un dossier de mod."""
    info_file = folder / "addoninfo.txt"
    content = f'name "{name}"\nauthor "{author}"\ndescription "{description}"\n'
    info_file.write_text(content, encoding="utf-8")
    return info_file


def _run_async(coro):
    """Executer une coroutine async dans un event loop existant ou nouvelle."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Nous sommes deja dans un event loop (ex: pytest-asyncio auto mode)
        # Retourner la coroutine — pytest-asyncio s'en charge.
        return coro  # pragma: no cover
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures principales
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_workshop(tmp_path: Path) -> Path:
    """Racine workshop avec 3 mods valides + 1 dossier ignore (non-numeric).

    Structure :
        ws_root/
          1000001/  (addoninfo.txt + script.lua)
          1000002/  (addoninfo.txt + config.bin)
          1000003/  (README.txt seul, fallback nom dossier)
          not_a_number/  (ignore par le scanner)
    """
    ws_root = tmp_path / "steamapps" / "workshop" / "content" / "1042170"
    ws_root.mkdir(parents=True)

    # Mod 1 — avec addoninfo
    mod1 = ws_root / "1000001"
    mod1.mkdir()
    _write_addoninfo(mod1, name="Test Mod Alpha", author="TestAuthor1", description="First test mod.")
    (mod1 / "script.lua").write_text("-- Test Lua\ndesc = 'alpha'", encoding="utf-8")

    # Mod 2 — avec addoninfo
    mod2 = ws_root / "1000002"
    mod2.mkdir()
    _write_addoninfo(mod2, name="Test Mod Beta", author="TestAuthor2", description="Second test mod.")
    (mod2 / "config.bin").write_text("config_key = 42", encoding="utf-8")

    # Mod 3 — sans addoninfo (fallback to folder name)
    mod3 = ws_root / "1000003"
    mod3.mkdir()
    (mod3 / "README.txt").write_text("# Readme Only\nNo addoninfo", encoding="utf-8")

    # Dossier invalide — doit etre ignore par le scanner
    bad_dir = ws_root / "not_a_number"
    bad_dir.mkdir()
    (bad_dir / "anything.lua").write_text("text", encoding="utf-8")

    return ws_root


@pytest.fixture()
def fake_empty_workshop(tmp_path: Path) -> Path:
    """Racine workshop vide — utile pour tester le cas 'aucun mod'."""
    ws_root = tmp_path / "steamapps" / "workshop" / "content" / "1042170"
    ws_root.mkdir(parents=True)
    return ws_root


@pytest.fixture()
def fake_steam_root(tmp_path: Path) -> Path:
    """Structure Steam minimal avec ProjectZomboid detectable.

    Structure :
        steamapps/
          common/ProjectZomboid/ProjectZomboid.exe
    """
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)

    pz_dir = steamapps / "common" / "ProjectZomboid"
    pz_dir.mkdir(parents=True)
    (pz_dir / "ProjectZomboid.exe").write_bytes(b"\x00")

    return steam_root


@pytest.fixture()
def fake_pz_manifest(tmp_path: Path) -> Path:
    """appmanifest_1042170.acf avec GameData → chemin du jeu."""
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir(parents=True)
    manifest = steamapps / "appmanifest_1042170.acf"
    manifest.write_text(
        '"AppData"\n{\n\t"GameData"  "common/ProjectZomboid"\n}\n',
        encoding="utf-8",
    )
    return manifest


@pytest.fixture()
def cmd_result_factory():
    """Factory pour creer des CmdResult facilement."""

    def _make(success: bool = True, output: str = "", error: str | None = None, exit_code: int = 0) -> Any:
        from ingestor.steam.steamcmd_client import CmdResult

        return CmdResult(success=success, output=output, exit_code=exit_code, error=error)

    return _make
