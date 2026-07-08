"""test_steamcmd_client — Tests du module steamcmd_client.

Mode mock total — aucun appel reseau ni subprocess reel.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio
import pytest

from ingestor.steam.steamcmd_client import CmdResult, SteamCMDClient


# ===========================================================================
# Tests : discovery
# ===========================================================================


def test_discover_steamcmd_returns_none_when_not_found():
    """Le discover retourne None quand aucun steamcmd.exe n'existe."""
    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=None):
        client = SteamCMDClient()
        assert client.steamcmd_exe is None


def test_discover_steamcmd_uses_provided_path():
    """Le chemin fourni en parametre surcharge la decouverte automatique."""
    fake = Path("C:/custom/steamcmd.exe")
    client = SteamCMDClient(steamcmd_path=fake)
    assert client.steamcmd_exe == fake


# ===========================================================================
# Tests : CmdResult properties
# ===========================================================================


def test_cmd_result_lines():
    """Propriete lines retourne les lignes de output splittees."""
    r = CmdResult(success=True, output="line1\nline2\nline3", exit_code=0)
    assert r.lines == ["line1", "line2", "line3"]


def test_cmd_result_success_property():
    """success est base sur returncode et contenu du message."""
    r = CmdResult(success=False, output="error", exit_code=1)
    assert r.success is False


def test_cmd_result_progress_lines_contains_ok():
    """progress_lines filtre les lignes de progression."""
    r = CmdResult(
        success=True,
        output="[  OK  ]\ndownloading...\nprogress 50%\ninfo",
        exit_code=0,
    )
    assert len(r.progress_lines) == 3


def test_cmd_result_progress_lines_filters_irrelevant():
    """progress_lines ignore les lignes sans mot-cle de progression."""
    r = CmdResult(
        success=True,
        output="info log line\nanother log line",
        exit_code=0,
    )
    assert len(r.progress_lines) == 0


# ===========================================================================
# Tests : _run_cmd (success case)
# ===========================================================================


@pytest.mark.asyncio
async def test_run_cmd_success():
    """Reussite steamcmd → CmdResult.success=True."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    async def mock_communicate(*_a, **_kw):
        return b"[  OK  ] - Downloaded!\nDone!", b""

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"[  OK  ] - Downloaded!\nDone!", b""))
    mock_proc.returncode = 0

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client._run_cmd("+login", "anonymous")
            assert result.success is True
            assert result.exit_code == 0


@pytest.mark.asyncio
async def test_run_cmd_failure_exit_code():
    """Echec steamcmd (exit != 0) → success=False."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"error", b""))
    mock_proc.returncode = 1

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client._run_cmd("+login", "anonymous")
            assert result.success is False


@pytest.mark.asyncio
async def test_run_cmd_error_stream():
    """Le stderr est capture dans CmdResult.error."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"output", b"stderr error msg"))
    mock_proc.returncode = 0

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client._run_cmd("+login", "anonymous")
            assert result.error == "stderr error msg"


@pytest.mark.asyncio
async def test_run_cmd_timeout():
    """Timeout → CmdResult.success=False avec message d'erreur."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.returncode = -1

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client._run_cmd("+login", "anonymous")
            assert result.success is False
            assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_run_cmd_no_steamcmd():
    """steamcmd.exe inexistant → CmdResult.success=False immediat."""
    client = SteamCMDClient(steamcmd_path=None)
    result = await client._run_cmd("+login", "anonymous")
    assert result.success is False
    assert result.error == "steamcmd.exe non trouve"


# ===========================================================================
# Tests : download_game (wrapper)
# ===========================================================================


@pytest.mark.asyncio
async def test_download_game_builds_correct_command():
    """download_game assemble la bonne sequence de commandes steamcmd."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"[  OK  ]", b""))
    mock_proc.returncode = 0

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = mock_proc
            await client.download_game("/tmp/pz", validate=True)

            # Verifier que la commande contient les bons arguments
            call_args = mock_exec.call_args[0]  # positional args to create_subprocess_exec
            full_cmd = " ".join(str(a) for a in call_args)
            assert "steamcmd.exe" in full_cmd
            assert "+app_update" in call_args
            assert "1042170" in call_args
            assert "validate" in call_args


# ===========================================================================
# Tests : install_workshop_item (wrapper)
# ===========================================================================


@pytest.mark.asyncio
async def test_install_workshop_success():
    """Installation reussie → success=True."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"[  OK  ] - Done!", b""))
    mock_proc.returncode = 0

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client.install_workshop_item(1234567890)
            assert result.success is True


@pytest.mark.asyncio
async def test_install_workshop_failure():
    """Installation echouee → success=False."""
    fake_exe = Path("C:/fake/steamcmd.exe")

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"download failed"))
    mock_proc.returncode = 1

    with patch("ingestor.steam.steamcmd_client._discover_steamcmd_path", return_value=fake_exe):
        client = SteamCMDClient()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client.install_workshop_item(1234567890)
            assert result.success is False


# ===========================================================================
# Tests : parse_progress_line (static method)
# ===========================================================================


def test_parse_progress_line_ok():
    """Detecte les lignes [  OK  ]."""
    result = SteamCMDClient.parse_progress_line("[  OK  ] - Downloaded update")
    assert result is not None
    assert "OK" in result.get("raw", "")


def test_parse_progress_line_percentage():
    """Detecte les lignes de progression percentage."""
    result = SteamCMDClient.parse_progress_line("10.50% of 1234.5 MB")
    assert result is not None


def test_parse_progress_line_unknown_format():
    """Format inconnu → None."""
    result = SteamCMDClient.parse_progress_line("random log line without pattern")
    assert result is None


def test_parse_progress_line_empty():
    """Chaine vide → None."""
    result = SteamCMDClient.parse_progress_line("")
    assert result is None
