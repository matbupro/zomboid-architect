"""tests/test_watchdog.py — Tests du watchdog (monitoring + auto-restart).

Couvre :
  - WatchdogConfig.from_env() (lecture .env, fallback default)
  - WatchdogState (sérialisation, recent_crashes detection)
  - ServerWatchdog.start/stop/restart (fichiers PID)
  - _is_process_alive (PID existant vs inexistant)
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def temp_state_dir(tmp_path: Path) -> Path:
    """Répertoire temporaire pour l'état du watchdog."""
    d = tmp_path / "watchdog"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def temp_pid_file(temp_state_dir: Path) -> Path:
    return temp_state_dir / "server.pid"


# ===========================================================================
# WatchdogConfig
# ===========================================================================


def test_config_from_env_uses_defaults_when_no_env(tmp_path: Path):
    """Pas de .env → valeurs par défaut."""
    from ingestor.watchdog import WatchdogConfig

    with patch.object(WatchdogConfig, "CONFIG_PATH", tmp_path / ".nonexistent"):
        config = WatchdogConfig.from_env()

    assert config.PID_FILE == tmp_path / "data" / "watchdog" / "server.pid"  # default
    assert config.HEALTH_CHECK_URL is None
    assert config.MAX_RESTARTS_PER_HOUR == 10
    assert config.RESTART_COOLDOWN_S == 30.0


def test_config_from_env_reads_custom_values(tmp_path: Path):
    """Variables WATCHDOG_* lues depuis .env."""
    from ingestor.watchdog import WatchdogConfig

    env_file = tmp_path / ".env"
    env_file.write_text(
        "WATCHDOG_PID_FILE=/custom/pid.pid\n"
        "WATCHDOG_HEALTH_URL=http://localhost:3000/health\n"
        "WATCHDOG_MAX_RESTARTS=5\n"
        "WATCHDOG_RESTART_COOLDOWN_S=60\n",
        encoding="utf-8",
    )

    with patch.object(WatchdogConfig, "CONFIG_PATH", env_file):
        config = WatchdogConfig.from_env()

    assert str(config.PID_FILE) == "/custom/pid.pid"
    assert config.HEALTH_CHECK_URL == "http://localhost:3000/health"
    assert config.MAX_RESTARTS_PER_HOUR == 5
    assert config.RESTART_COOLDOWN_S == 60.0


# ===========================================================================
# WatchdogState
# ===========================================================================


def test_state_serialization():
    """to_dict retourne un dict serializable."""
    from ingestor.watchdog import WatchdogState

    state = WatchdogState()
    state.pid = 12345
    state.status = "running"
    d = state.to_dict()

    assert d["pid"] == 12345
    assert d["status"] == "running"
    assert d["crash_count"] == 0
    assert "recent_crashes_in_1h" in d


def test_state_recent_crashes_threshold():
    """recent_crashes = count dans les dernières 60 minutes."""
    import time

    from ingestor.watchdog import WatchdogState

    state = WatchdogState()
    now = time.time()
    # Ajoute des timestamps récents + anciens
    state.restarts_last_hour.extend([now - 60, now - 120, now - 300])  # > 1h → exclus
    state.restarts_last_hour.extend([now - 1800, now - 1900])           # > 1h → exclus
    state.restarts_last_hour.extend([now - 3599])                        # < 1h → inclus

    assert state.recent_crashes == 1


def test_state_roundtrip(tmp_path: Path):
    """Sauvegarde + rechargement d'état."""
    from ingestor.watchdog import WatchdogState

    state = WatchdogState()
    state.pid = 99999
    state.status = "crashed"
    state.crash_count = 3

    json_file = tmp_path / "state.json"
    json_file.write_text(json.dumps(state.to_dict()), encoding="utf-8")

    loaded = WatchdogState()
    loaded_data = json.loads(json_file.read_text())
    loaded.pid = loaded_data["pid"]
    loaded.status = loaded_data["status"]
    loaded.crash_count = loaded_data["crash_count"]

    assert loaded.pid == 99999
    assert loaded.status == "crashed"
    assert loaded.crash_count == 3


# ===========================================================================
# ServerWatchdog — fichiers PID
# ===========================================================================


def test_writeread_pid_file(temp_state_dir: Path, temp_pid_file: Path):
    """Écriture et lecture du fichier PID."""
    from ingestor.watchdog import WatchdogConfig, ServerWatchdog

    config = WatchdogConfig.from_env()
    config.PID_FILE = temp_pid_file

    wd = ServerWatchdog(
        server_cmd=["python", "-c", "pass"],
        config=config,
        state_dir=temp_state_dir,
    )

    # Écriture
    wd._write_pid_file(12345)
    assert temp_pid_file.exists()

    # Lecture
    loaded_pid = wd._get_current_pid()
    assert loaded_pid == 12345


def test_pid_file_removal(temp_state_dir: Path, temp_pid_file: Path):
    """Suppression du fichier PID."""
    from ingestor.watchdog import WatchdogConfig, ServerWatchdog

    config = WatchdogConfig.from_env()
    config.PID_FILE = temp_pid_file

    wd = ServerWatchdog(
        server_cmd=["python", "-c", "pass"],
        config=config,
        state_dir=temp_state_dir,
    )

    wd._write_pid_file(12345)
    wd._remove_pid_file()
    assert not temp_pid_file.exists()


def test_get_current_pid_when_file_missing(temp_state_dir: Path):
    """Aucun PID file → None."""
    from ingestor.watchdog import WatchdogConfig, ServerWatchdog

    config = WatchdogConfig.from_env()
    config.PID_FILE = temp_state_dir / "nonexistent.pid"

    wd = ServerWatchdog(
        server_cmd=["python", "-c", "pass"],
        config=config,
        state_dir=temp_state_dir,
    )

    assert wd._get_current_pid() is None


# ===========================================================================
# State persistence
# ===========================================================================


def test_load_save_state(temp_state_dir: Path):
    """Chargement et sauvegarde de l'état."""
    from ingestor.watchdog import WatchdogConfig, ServerWatchdog

    config = WatchdogConfig.from_env()
    config.PID_FILE = temp_state_dir / "server.pid"

    state_file = temp_state_dir / "state.json"

    wd = ServerWatchdog(
        server_cmd=["python", "-c", "pass"],
        config=config,
        state_dir=temp_state_dir,
    )

    # Sauvegarde custom state
    test_state = MagicMock()
    test_state.to_dict.return_value = {"pid": 54321, "status": "running"}
    wd._state = test_state

    # Le _save_state sérialise via to_dict
    wd._save_state()

    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert isinstance(data, dict)


def test_load_empty_state():
    """Nouveau WatchdogState() est vide."""
    from ingestor.watchdog import WatchdogState

    state = WatchdogState()
    assert state.pid is None
    assert state.status == "idle"
    assert state.crash_count == 0
    assert state.start_time is None


# ===========================================================================
# _is_process_alive
# ===========================================================================


def test_is_process_alive_with_current_pid():
    """Le PID courant existe → True."""
    from ingestor.watchdog import ServerWatchdog

    # PID du processus courant
    current_pid = os.getpid() if hasattr(os, "getpid") else subprocess.Popen(["echo", "test"]).pid
    assert ServerWatchdog._is_process_alive(current_pid) is True


def test_is_process_alive_invalid_pid():
    """PID invalide → False."""
    from ingestor.watchdog import ServerWatchdog

    # PID 1 existe sur Linux mais pas sur Windows — utiliser un PID très élevé garanti inexistant
    assert ServerWatchdog._is_process_alive(999999999) is False


# ===========================================================================
# CLI entry point
# ===========================================================================


def test_cli_status_no_server(temp_state_dir: Path):
    """Status sans serveur actif → PID 'aucun'."""
    from ingestor.watchdog import main

    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        code = main(["--state-dir", str(temp_state_dir), "status"])

    output = f.getvalue()
    assert code == 0
    assert "aucun" in output or "PID" in output


def test_cli_stop_no_server(temp_state_dir: Path):
    """Stop sans serveur → retourne False."""
    from ingestor.watchdog import main

    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        code = main(["--state-dir", str(temp_state_dir), "stop"])

    output = f.getvalue()
    assert code == 0  # Pas d'erreur, juste pas de processus à arrêter


# ===========================================================================
# Edge cases
# ===========================================================================


def test_config_from_env_ignores_comments(tmp_path: Path):
    """Lignes commençant par # ignorées."""
    from ingestor.watchdog import WatchdogConfig

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# This is a comment\n"
        "\n"
        "WATCHDOG_MAX_RESTARTS=7\n"  # variable valide
        "# Another comment\n",
        encoding="utf-8",
    )

    with patch.object(WatchdogConfig, "CONFIG_PATH", env_file):
        config = WatchdogConfig.from_env()

    assert config.MAX_RESTARTS_PER_HOUR == 7


def test_config_from_env_ignores_invalid_lines(tmp_path: Path):
    """Lignes sans '=' ignorées."""
    from ingestor.watchdog import WatchdogConfig

    env_file = tmp_path / ".env"
    env_file.write_text(
        "no_equals_here\n"  # pas de '=' → ignorée
        "WATCHDOG_MAX_RESTARTS=3\n",
        encoding="utf-8",
    )

    with patch.object(WatchdogConfig, "CONFIG_PATH", env_file):
        config = WatchdogConfig.from_env()

    assert config.MAX_RESTARTS_PER_HOUR == 3


# ===========================================================================
# Runner (pytest auto-discovery)
# ===========================================================================

TESTS = [
    test_config_from_env_uses_defaults_when_no_env,
    test_config_from_env_reads_custom_values,
    test_state_serialization,
    test_state_recent_crashes_threshold,
    test_state_roundtrip,
    test_writeread_pid_file,
    test_pid_file_removal,
    test_get_current_pid_when_file_missing,
    test_load_save_state,
    test_load_empty_state,
    test_is_process_alive_with_current_pid,
    test_is_process_alive_invalid_pid,
    test_cli_status_no_server,
    test_cli_stop_no_server,
    test_config_from_env_ignores_comments,
    test_config_from_env_ignores_invalid_lines,
]


def main():
    total_ok = 0
    total_fail = 0

    for fn in TESTS:
        try:
            fn()
            print(f"  [+] {fn.__name__}")
            total_ok += 1
        except Exception as e:
            print(f"  [-] {fn.__name__}: {e}")
            total_fail += 1

    print(f"\n{'='*60}")
    print(f"Watchdog Tests — {total_ok}/{total_ok + total_fail} passed")
    print("=" * 60)
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
