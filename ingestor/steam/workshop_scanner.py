"""
workshop_scanner — Scan des mods installes depuis le Steam Workshop.

Scanne steamapps/workshop/content/1042170/<mod_id>/ pour decouvrir les mods installés.
Lit addoninfo.txt (format texte clair Valve) pour extraire metadata.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)

PZ_APP_ID: int = 1042170
"""Steam AppID pour Project Zomboid (utilisé comme clef dans workshop/content/<appid>/)."""


@dataclass
class WorkshopModInfo:
    """Information sur un mod du Steam Workshop."""

    mod_id: int
    folder_path: Path
    name: str | None = None
    description: str | None = None
    author: str | None = None
    date_created: str | None = None
    date_updated: str | None = None
    file_count: int = 0
    tags: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        """Convertir en metadata pour ChromaDB."""
        return {
            "mod_id": self.mod_id,
            "name": self.name,
            "author": self.author,
            "description": self.description[:500] if self.description else None,
            "date_created": self.date_created,
            "date_updated": self.date_updated,
            "file_count": self.file_count,
            "tags": ",".join(self.tags),
            "source": "steam_workshop",
        }


class WorkshopScanner:
    """Scanne le repertoire steamapps/workshop/content/1042170/ pour decouvrir les mods installés."""

    def __init__(self, content_root: Path):
        """
        Args:
            content_root: Repertoire workshop/content/1042170 (doit exister).
        """
        self._content_root = content_root.resolve()

    @property
    def content_root(self) -> Path:
        return self._content_root

    async def scan(self) -> list[WorkshopModInfo]:
        """Decouvrir tous les mods dans le repertoire workshop.

        Returns:
            Liste de WorkshopModInfo pour chaque mod installe.
        """
        if not self._content_root.exists():
            logger.warning("Root Workshop inexistant: %s", self._content_root)
            return []

        mods: list[WorkshopModInfo] = []
        now = time.time()

        for item_id_dir in sorted(self._content_root.iterdir()):
            if not item_id_dir.is_dir():
                continue

            try:
                mod_id = int(item_id_dir.name)
            except ValueError:
                logger.debug("Repertoire non-numeric ignore: %s", item_id_dir.name)
                continue

            mod_info = await self._parse_mod_folder(item_id_dir, mod_id)
            if mod_info is not None:
                # Count files (recursively)
                try:
                    mod_info.file_count = sum(1 for _ in item_id_dir.rglob("*") if _.is_file())
                except OSError as exc:
                    logger.debug("Erreur comptage fichiers %s: %s", item_id_dir.name, exc)

                # Default name to folder name if addoninfo.txt failed
                if mod_info.name is None:
                    mod_info.name = item_id_dir.name

                mods.append(mod_info)

        logger.info("%d mods Workshop decouverts.", len(mods))
        return mods

    async def find_by_mod_id(self, mod_id: int) -> WorkshopModInfo | None:
        """Rechercher un mod par son ID du workshop.

        Args:
            mod_id: ID du mod Steam Workshop.

        Returns:
            WorkshopModInfo ou None si inexistant.
        """
        target = self._content_root / str(mod_id)
        if not target.is_dir():
            return None
        return await self._parse_mod_folder(target, mod_id)

    async def _parse_mod_folder(self, folder: Path, mod_id: int) -> WorkshopModInfo | None:
        """Parser les metadata d'un repertoire de mod individual."""
        info = WorkshopModInfo(mod_id=mod_id, folder_path=folder)

        # Method 1: addoninfo.txt (Valve's standard for workshop addons)
        addon_info = folder / "addoninfo.txt"
        if addon_info.exists():
            metadata = self._parse_addoninfo(addon_info)
            info.name = metadata.get("name")
            info.description = metadata.get("description")
            info.author = metadata.get("author")
            info.date_created = metadata.get("dateCreated")
            info.date_updated = metadata.get("dateUpdated")
            # Parse tags if present
            if "tags" in metadata:
                info.tags = [t.strip() for t in metadata["tags"].split(",") if t.strip()]
            return info

        # Method 2: Try reading any README file
        for readme_name in ["README.txt", "readme.txt", "README.md", "readme.md"]:
            readme = folder / readme_name
            if readme.exists():
                try:
                    text = readme.read_text(encoding="utf-8", errors="replace")[:500]
                    # Extract name from first line that starts with "name" or "# " or "Name:"
                    for line in text.splitlines()[:10]:
                        if line.startswith("# ") and not info.name:
                            info.name = line[2:].strip()
                            break
                        elif line.lower().startswith("name:"):
                            info.name = line.split(":", 1)[1].strip()
                            break
                        elif line.lower().startswith("name "):
                            info.name = line.split(None, 1)[1].strip() if len(line) > 4 else None
                            break
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Lecture README %s echoue: %s", readme_name, exc)

        return info

    @staticmethod
    def _parse_addoninfo(path: Path) -> dict[str, str]:
        """Parser addoninfo.txt — format cle=valeur texte clair de Valve.

        Format attendu:
            name "My Mod"
            author "Mod Author"
            description "A great mod for PZ."
            tags "weapons,combat,pve"
            dateCreated "1234567890"
            dateUpdated "1234567890"
        """
        result: dict[str, str] = {}
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Valve addoninfo.txt format: key "value" or key="value"
                if "=" in line:
                    key, _, value = line.partition("=")
                else:
                    # Space-separated: key "value"
                    parts = line.split(None, 1)
                    if len(parts) < 2:
                        continue
                    key, value = parts[0].strip().strip('"'), parts[1]

                key = key.strip().strip('"')
                # Strip surrounding quotes from value
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                result[key] = value
        except Exception as exc:  # noqa: BLE001
            logger.debug("Echec parsing addoninfo %s: %s", path.name, exc)
        return result
