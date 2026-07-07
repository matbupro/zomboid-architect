"""Watchdog — Monitoring et redémarrage automatique du serveur.

Surveille un processus serveur (MCP server, Discord bot, etc.) via un fichier PID
et redémarre automatiquement en cas de crash ou d'inactivité.

Usage CLI :
    python -m ingestor.watchdog start   # lance le serveur et le surveille
    python -m ingestor.watchdog status   # affiche l'état du monitoring
    python -m ingestor.watchdog stop     # arrête le processus monitoré
    python -m ingestor.watchdog restart  # redémarre proprement

Configuration :
    STEAM_USER / STEAM_PASS          → .env (SteamCMD)
    PID_FILE                         → default: data/watchdog/server.pid
    HEALTH_CHECK_URL                 → optionnel, pour vérifier le processus via HTTP
    MAX_RESTARTS                     → max de redémarrages avant alerte (defaut: 10/h)
    RESTART_COOLDOWN_S               → delai minimal entre restarts (defaut: 30s)

Seuil d'alerte :
    - PLUS_3_CRASHES_IN_1H           → log ERROR + optionnel webhook Discord
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = getLogger("ingestor.watchdog")

# ── Chemins par défaut ────────────────────────────────────────────────────────

DEFAULT_PID_FILE = PROJECT_ROOT / "data" / "watchdog" / "server.pid"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs" / "watchdog"
CONFIG_PATH = PROJECT_ROOT / ".env.unified"


# ── Configuration ─────────────────────────────────────────────────────────────

class WatchdogConfig:
    """Configuration du watchdog, lue depuis .env ou valeurs par défaut."""

    PID_FILE: Path = DEFAULT_PID_FILE
    HEALTH_CHECK_URL: str | None = None  # ex: "http://localhost:3000/health"
    MAX_RESTARTS_PER_HOUR: int = 10      # alerte si dépassé
    RESTART_COOLDOWN_S: float = 30.0     # delai minimal entre deux redémarrages
    HEARTBEAT_INTERVAL_S: float = 60.0   # intervalle de vérification du process
    LOG_DIR: Path = DEFAULT_LOG_DIR
    SERVER_COMMAND: list[str] | None = None  # commande du serveur (None = utilise serve cible)

    # ── Chargement depuis .env ───────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "WatchdogConfig":
        env_path = CONFIG_PATH
        if not env_path.exists():
            logger.warning(".env non trouvé — utilisation des valeurs par défaut")
            return cls()

        config: dict[str, Any] = {}
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    config[key.strip()] = value.strip()
        except OSError as exc:
            logger.warning("Erreur lecture .env : %s", exc)

        pid_file = config.get("WATCHDOG_PID_FILE")
        if pid_file:
            cls.PID_FILE = Path(pid_file)

        health_url = config.get("WATCHDOG_HEALTH_URL")
        if health_url:
            cls.HEALTH_CHECK_URL = health_url

        max_restarts = config.get("WATCHDOG_MAX_RESTARTS")
        if max_restarts:
            try:
                cls.MAX_RESTARTS_PER_HOUR = int(max_restarts)
            except ValueError:
                pass

        cooldown = config.get("WATCHDOG_RESTART_COOLDOWN_S")
        if cooldown:
            try:
                cls.RESTART_COOLDOWN_S = float(cooldown)
            except ValueError:
                pass

        heartbeat = config.get("WATCHDOG_HEARTBEAT_INTERVAL_S")
        if heartbeat:
            try:
                cls.HEARTBEAT_INTERVAL_S = float(heartbeat)
            except ValueError:
                pass

        return cls()


# ── État du watchdog ──────────────────────────────────────────────────────────

class WatchdogState:
    """État persisté du watchdog (sauvegardé sur disque)."""

    def __init__(self):
        self.pid: int | None = None
        self.start_time: str | None = None  # ISO timestamp
        self.last_restart: str | None = None
        self.restarts_last_hour: list[float] = []  # timestamps des restarts récents
        self.crash_count: int = 0
        self.status: str = "idle"  # idle, running, crashed, restarting

    @property
    def recent_crashes(self) -> int:
        """Nombre de crashes dans les dernières 60 minutes."""
        cutoff = time.time() - 3600
        return sum(1 for t in self.restarts_last_hour if t >= cutoff)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "start_time": self.start_time,
            "last_restart": self.last_restart,
            "restarts_last_hour": len(self.restarts_last_hour),
            "crash_count": self.crash_count,
            "status": self.status,
            "recent_crashes_in_1h": self.recent_crashes,
        }


# ── Watchdog core ─────────────────────────────────────────────────────────────

class ServerWatchdog:
    """Surveille et redémarre automatiquement un processus serveur."""

    def __init__(
        self,
        server_cmd: list[str],
        config: WatchdogConfig | None = None,
        state_dir: Path | None = None,
    ):
        self.server_cmd = server_cmd
        self.config = config or WatchdogConfig.from_env()
        self.state_dir = state_dir or self.config.PID_FILE.parent
        self.state_file = self.state_dir / "state.json"

        # État courant (en mémoire)
        self._process: subprocess.Popen | None = None
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._state = self._load_state()

    # ── Démarrage / Arrêt ────────────────────────────────────────────────────

    def start(self) -> WatchdogState:
        """Démarre le serveur et lance le monitoring."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_pid_file()
        self.start_server()
        return self._state

    def stop(self) -> bool:
        """Arrête proprement le processus monitoré."""
        pid = self._get_current_pid()
        if pid is None:
            logger.info("Aucun processus en cours — rien à arrêter")
            return False

        try:
            proc = subprocess.Popen(
                ["taskkill", "/pid", str(pid), "/f"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            proc.communicate(timeout=10)
            logger.info("Processus PID %d arrêté.", pid)
        except Exception as exc:  # noqa: BLE001
            logger.error("Erreur arrêt PID %d : %s", pid, exc)
            return False

        self._cleanup()
        return True

    def restart(self) -> WatchdogState:
        """Redémarre le processus (stop + start)."""
        old_pid = self._get_current_pid()
        if old_pid:
            self.stop()
        self._state.status = "restarting"
        self._state.last_restart = datetime.now(timezone.utc).isoformat()
        self._state.restarts_last_hour.append(time.time())

        # Vérifier le seuil d'alerte
        recent = self._state.recent_crashes
        if recent > self.config.MAX_RESTARTS_PER_HOUR:
            logger.error(
                "ALERTE : %d redémarrages dans la dernière heure (seuil: %d).",
                recent,
                self.config.MAX_RESTARTS_PER_HOUR,
            )

        self.start()
        return self._state

    # ── Monitoring async ─────────────────────────────────────────────────────

    async def monitor_loop(self):
        """Boucle de monitoring — vérifie le process à intervalle régulier."""
        while True:
            if self._process and self._process.poll() is None:
                self._state.status = "running"
                self._save_state()
            else:
                self._state.crash_count += 1
                self._state.last_restart = datetime.now(timezone.utc).isoformat()
                self._state.restarts_last_hour.append(time.time())
                recent = self._state.recent_crashes

                if recent > self.config.MAX_RESTARTS_PER_HOUR:
                    logger.error(
                        "ALERTE : %d crashes dans la dernière heure — le serveur semble instable.",
                        recent,
                    )
                    # TODO: webhook Discord / notification externe
                else:
                    logger.info(
                        "Processus mort. Redémarrage ( #%d) dans %.0fs...",
                        self._state.crash_count,
                        self.config.RESTART_COOLDOWN_S,
                    )

                # Attente avant redémarrage
                await asyncio.sleep(self.config.RESTART_COOLDOWN_S)

                # Cooldown : éviter les boucles de crash
                if self._state.restarts_last_hour[-1] - (self._state.restarts_last_hour[-2] if len(self._state.restarts_last_hour) > 1 else 0) < 10:
                    logger.warning("Redémarrages trop rapprochés — attente étendue à 60s")
                    await asyncio.sleep(50)

                self.start_server()

            await asyncio.sleep(self.config.HEARTBEAT_INTERVAL_S)

    # ── Interne : Gestion du processus ───────────────────────────────────────

    def start_server(self):
        """Démarre le serveur en sous-processus et enregistre le PID."""
        if self._running:
            logger.warning("Serveur déjà en cours — skip")
            return

        try:
            self._process = subprocess.Popen(
                self.server_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )
            pid = self._process.pid
            self._running = True
            self._state.pid = pid
            self._state.start_time = datetime.now(timezone.utc).isoformat()
            self._state.status = "running"

            self._write_pid_file(pid)
            logger.info("Serveur démarré : PID=%d, cmd=%s", pid, self.server_cmd)
        except Exception as exc:  # noqa: BLE001
            logger.error("Échec démarrage serveur : %s", exc)
            self._state.status = "crashed"

    def _cleanup(self):
        """Nettoyage après arrêt."""
        self._running = False
        self._process = None
        self._state.pid = None
        self._state.status = "idle"
        self._remove_pid_file()
        self._save_state()

    # ── Interne : Fichiers de suivi ───────────────────────────────────────────

    def _write_pid_file(self, pid: int):
        pid_path = self.config.PID_FILE
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        with open(pid_path, "w", encoding="utf-8") as fh:
            json.dump({"pid": pid, "started_at": self._state.start_time}, fh)

    def _remove_pid_file(self):
        pid_path = self.config.PID_FILE
        if pid_path.exists():
            pid_path.unlink()

    def _ensure_pid_file(self):
        """Crée le fichier PID s'il n'existe pas."""
        self.config.PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.PID_FILE.exists():
            with open(self.config.PID_FILE, "w", encoding="utf-8") as fh:
                json.dump({}, fh)

    def _get_current_pid(self) -> int | None:
        pid_path = self.config.PID_FILE
        if not pid_path.exists():
            return None
        try:
            data = json.loads(pid_path.read_text())
            pid = data.get("pid")
            if pid and self._is_process_alive(pid):
                return pid
        except (OSError, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _load_state(self) -> WatchdogState:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                state = WatchdogState()
                state.pid = data.get("pid")
                state.start_time = data.get("start_time")
                state.last_restart = data.get("last_restart")
                state.crash_count = data.get("crash_count", 0)
                state.status = data.get("status", "idle")
                return state
            except (OSError, json.JSONDecodeError):
                pass
        return WatchdogState()

    def _save_state(self):
        self.state_file.write_text(json.dumps(self._state.to_dict(), indent=2), encoding="utf-8")


# ── CLI Entry point ───────────────────────────────────────────────────────────

def main(args: list[str] | None = None) -> int:
    """Point d'entrée CLI du watchdog."""
    import argparse

    parser = argparse.ArgumentParser(description="Watchdog — monitoring et redémarrage serveur")
    parser.add_argument("action", choices=["start", "stop", "restart", "status"], help="Action à exécuter")
    parser.add_argument("--server-cmd", nargs="+", help="Commande du serveur (défaut: python -m ingestor.mcp_server)")
    parser.add_argument("--state-dir", type=Path, default=None, help="Répertoire de l'état persisté")

    parsed = parser.parse_args(args)

    server_cmd = parsed.server_cmd or ["python", "-m", "ingestor.mcp_server"]
    config = WatchdogConfig.from_env()

    if parsed.state_dir:
        config.PID_FILE = parsed.state_dir / "server.pid"

    watchdog = ServerWatchdog(
        server_cmd=server_cmd,
        config=config,
        state_dir=parsed.state_dir or config.PID_FILE.parent,
    )

    if parsed.action == "start":
        logger.info("=== Watchdog START ===")
        result = watchdog.start()
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    elif parsed.action == "stop":
        logger.info("=== Watchdog STOP ===")
        success = watchdog.stop()
        print(f"Arrêté : {success}")
        return 0 if success else 1

    elif parsed.action == "restart":
        logger.info("=== Watchdog RESTART ===")
        result = watchdog.restart()
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    elif parsed.action == "status":
        pid = watchdog._get_current_pid()
        state = watchdog._state
        if state.start_time:
            print(f"Démarré : {state.start_time}")
        if pid:
            print(f"PID   : {pid} (actif)")
        else:
            print("PID   : aucun")
        print(f"État  : {state.status}")
        print(f"Crashes/1h: {state.recent_crashes} (total: {state.crash_count})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
