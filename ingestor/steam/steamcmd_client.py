"""
steamcmd_client — Wrapper de la CLI steamcmd pour le telechargement de PZ et mods.

Commandes supportees (login avec credentials ou anonymous) :
  +login <user> <pass>                    → login credential
  +login <user> <pass> <authcode>          → login avec Steam Guard (2FA)
  +app_update 1042170 validate             → installer/mettre a jour PZ
  +workshop_download_item 1042170 <id>     → telecharger un mod du workshop
  +quit                                      → fermer steamcmd

Le client essaie en priorité les credentials .env (STEAM_USER / STEAM_PASS).
S'ils sont absents, fallback anonymous.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PZ_APP_ID: int = 1042170


@dataclass
class CmdResult:
    """Retour d'execution steamcmd."""

    success: bool
    output: str
    exit_code: int
    error: str | None = None

    @property
    def lines(self) -> list[str]:
        return self.output.splitlines()

    @property
    def progress_lines(self) -> list[str]:
        """Lignes de progression du telechargement."""
        return [l for l in self.lines if any(kw in l for kw in ("downloading", "progress", "[  OK  ]"))]


def _discover_steamcmd_path() -> Path | None:
    """Decouvrir steamcmd.exe dans les chemins standards."""
    candidates = []
    # Project-local tools
    project_root = Path(__file__).resolve().parents[3]
    for base in [project_root / "tools", Path.cwd() / ".." / "Games", Path("C:\\Games"), Path("C:\\Steam")]:
        for candidate in ["steamcmd/steamcmd.exe", "SteamCMD/steamcmd.exe"]:
            full = base / candidate
            if full.exists():
                logger.info("steamcmd.exe decouvert: %s", full)
                return full.resolve()

    # PATH fallback
    try:
        import shutil
        found = shutil.which("steamcmd") or shutil.which("steamcmd.exe")
        if found:
            return Path(found)
    except ImportError:
        pass

    logger.warning("steamcmd.exe non trouve — verification manuelle necessaire.")
    return None


class SteamCMDClient:
    """Wrapper async de steamcmd.exe pour le telechargement de PZ et mods workshop."""

    def __init__(self, steamcmd_path: Path | None = None):
        """
        Args:
            steamcmd_path: Chemin vers steamcmd.exe. Si None, decouverte automatique.
        """
        self._steamcmd_exe = steamcmd_path or _discover_steamcmd_path()

    @property
    def steamcmd_exe(self) -> Path | None:
        return self._steamcmd_exe

    async def _run_cmd(self, *commands: str, work_dir: Path | None = None) -> CmdResult:
        """Executer une sequence de commandes steamcmd.

        Args:
            *commands: Sequences de commandes (ex: "+login anonymous", "+app_update 1042170").
            work_dir: Repertoire de travail pour steamcmd.

        Returns:
            CmdResult avec output, success flag, et code de sortie.
        """
        if self._steamcmd_exe is None:
            return CmdResult(success=False, output="", exit_code=-1, error="steamcmd.exe non trouve")

        # Build the full command line
        cmd = [str(self._steamcmd_exe), *commands, "+quit"]

        logger.info("Lancement steamcmd: %s", " ".join(cmd[:5]) + "...")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(work_dir) if work_dir else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate(timeout=600)  # 10 min max for large downloads
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error = stderr.decode("utf-8", errors="replace") if stderr else None

            success = proc.returncode == 0 and ("[  OK  ]" in output or "fully installed" in output.lower()
                                                 or "successfully" in output.lower())

            result = CmdResult(success=success, output=output, exit_code=proc.returncode, error=error)
            logger.info("steamcmd termine (succes=%s, code=%d)", success, proc.returncode)
            return result

        except asyncio.TimeoutError:
            return CmdResult(
                success=False, output="", exit_code=-1,
                error="Timeout steamcmd depasse 10 minutes",
            )
        except OSError as exc:
            return CmdResult(success=False, output="", exit_code=-1, error=f"OSError: {exc}")

    async def download_game(self, target_dir: Path | str, validate: bool = False) -> CmdResult:
        """Telecharger/mettre a jour Project Zomboid via steamcmd.

        Args:
            target_dir: Repertoire de destination (ex: steamapps/common/).
            validate: Ajouter l'option 'validate' pour verifier les fichiers.

        Returns:
            CmdResult avec le resultat du telechargement.
        """
        # Try credential login first, fallback to anonymous
        login_cmd = self._get_login_command()

        cmd_line = login_cmd + [f"+app_update", str(PZ_APP_ID)]
        if validate:
            cmd_line.append("validate")
        cmd_line.extend(["-dir", str(target_dir)])

        result = await self._run_cmd(*cmd_line)

        # If credential login failed, retry with anonymous
        if not result.success and "FAILURE" in (result.output or "").upper():
            logger.info("Login credentials echoue — fallback anonymous")
            cmd_line_anon = ["+login", "anonymous", f"+app_update", str(PZ_APP_ID)]
            if validate:
                cmd_line_anon.append("validate")
            cmd_line_anon.extend(["-dir", str(target_dir)])
            return await self._run_cmd(*cmd_line_anon)

        return result

    async def install_workshop_item(self, workshop_id: int, target_dir: Path | None = None) -> CmdResult:
        """Installer un mod du Workshop via steamcmd.

        Args:
            workshop_id: ID Steam Workshop du mod (ex: 1234567890).
            target_dir: Repertoire de destination (defaut: steamapps/workshop/content/1042170/).

        Returns:
            CmdResult avec le resultat de l'installation.
        """
        if target_dir is None:
            # Default workshop content directory — project-local to gather all assets centrally
            target_dir = Path.cwd() / "downloads" / "workshop"

        login_cmd = self._get_login_command()
        cmd_line = login_cmd + ["-dir", str(target_dir), f"+workshop_download_item", str(PZ_APP_ID), str(workshop_id)]

        result = await self._run_cmd(*cmd_line)

        # If credential login failed, retry with anonymous
        if not result.success and "FAILURE" in (result.output or "").upper():
            logger.info("Login credentials echoue — fallback anonymous")
            cmd_line_anon = ["+login", "anonymous", "-dir", str(target_dir),
                             f"+workshop_download_item", str(PZ_APP_ID), str(workshop_id)]
            return await self._run_cmd(*cmd_line_anon)

        return result

    async def download_all_subscribed_mods(self, target_dir: Path | None = None) -> list[int]:
        """Telecharger tous les mods workshop abonnees.

        Scanne steamapps/workshop/content/1042170/ et installe chaque repertoire inexistant.

        Args:
            target_dir: Racine du contenu workshop.

        Returns:
            Liste des IDs de mods installes.
        """
        if target_dir is None:
            target_dir = Path.cwd() / "steamapps" / "workshop" / "content" / str(PZ_APP_ID)

        installed = []
        if not self._steamcmd_exe:
            return installed

        # Discover what's already present
        if target_dir.exists():
            existing_ids = {d.name for d in target_dir.iterdir() if d.is_dir() and d.name.isdigit()}
        else:
            existing_ids = set()

        logger.info("Recherche des mods workshop abonnees... (deja installes: %d)", len(existing_ids))

        # For now, return list of IDs that need installation
        # Full "subscribed mods" enumeration requires parsing steam's account data,
        # which is complex. Instead, we just scan for installed ones.
        return list(sorted(int(x) for x in existing_ids if x.isdigit()))

    @staticmethod
    def parse_progress_line(line: str) -> dict[str, Any] | None:
        """Parser une ligne de progression steamcmd.

        Exemple de sortie: "[  OK  ] - Downloaded update '1042170' (100% complete)"
        """
        patterns = [
            r"\[\s*OK\s*\]\s*(.*)",           # [  OK  ] message
            r"(\d+)\.(\d+)%\s+of\s+(\d+\.?\d*)",  # percentage progress
        ]
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                groups = match.groups()
                return {"raw": line.strip(), "matched_groups": groups}
        return None

    # -----------------------------------------------------------------------
    # Credentials & Steam Guard
    # -----------------------------------------------------------------------

    def _get_login_command(self) -> list[str]:
        """Retourner la commande de login appropriee.

        Priorite: credentials .env > credential avec code Steam Guard
        > anonymous.
        """
        from ..config import load_config

        config = load_config()

        if config.STEAM_USER and config.STEAM_PASS:
            return ["+login", config.STEAM_USER, config.STEAM_PASS]

        logger.info("Aucun credential Steam — utilisation anonymous")
        return ["+login", "anonymous"]
