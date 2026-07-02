"""ingestor/parser.py — Pipeline d'extraction des scripts Project Zomboid.

Tous les parseurs héritent de BaseParser. Chaque erreur est mise en quarantaine
dans quarantine.jsonl plutôt que de tuer le pipeline.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from defusedxml import ElementTree as DefusedET
from xml.etree import ElementTree as ET

from ingestor.game_version import GameVersion, get_current_game_version
from ingestor.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Enums & Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


class ContentType(Enum):
    """Catégories de contenu extraites depuis les fichiers sources."""
    ITEM       = "item"
    RECIPE     = "recipe"
    TRAIT      = "trait"
    PROFESSION = "profession"
    SKILL      = "skill"
    MOODLE     = "moodle"
    MECHANIC   = "mechanic"
    LUA_API    = "lua_api"
    UNKNOWN    = "unknown"


@dataclass
class ParsedChunk:
    """Unité atomique de contenu ingérée dans ChromaDB."""
    id: str
    type: str           # ContentType.value
    version: str        # GameVersion.value  ("b41" | "b42")
    title: str
    content: str        # texte lisible, formaté pour le RAG
    metadata: dict[str, Any]
    source_file: str    # chemin relatif du fichier source
    parsed_at: str      # ISO-8601 UTC

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParseError:
    """Représentation JSON-sérialisable d'une erreur de parsing."""
    chunk_id: str
    type: str
    snippet: str          # 500 premiers caractères du bloc problematic
    exc: str              # nom de l'exception
    raw_snippet: str      # tel quel (non trONqué)
    source_file: str
    timestamp: str
    game_version: str
    exc_info: str         # traceback court

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de parsing XML partagé
# ─────────────────────────────────────────────────────────────────────────────


def _sanitise(text: Optional[str]) -> str:
    """Normalise un texte XML : retire indentation, vide → None."""
    if text is None:
        return ""
    return " ".join(text.split()).strip()


def _flush_to_chunk(
    title: str,
    body_lines: list[str],
    content_type: ContentType,
    metadata: dict[str, Any],
    source_file: Path,
) -> ParsedChunk:
    """Fabrique un ParsedChunk avec versioning automatique."""
    version = get_current_game_version()
    content = "\n".join(body_lines).strip()
    return ParsedChunk(
        id=str(uuid.uuid4()),
        type=content_type.value,
        version=version.value,
        title=title,
        content=content,
        metadata=metadata,
        source_file=str(source_file),
        parsed_at=datetime.now(timezone.utc).isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Quarantaine
# ─────────────────────────────────────────────────────────────────────────────


def _quarantine(err: ParseError) -> None:
    """Écrit une erreur de parsing dans quarantine.jsonl (append)."""
    QUARANTINE_DIR = Path(__file__).parent.parent / "data" / "quarantine"
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    qfile = QUARANTINE_DIR / f"quarantine_{stamp}.jsonl"
    with open(qfile, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(err.to_dict(), ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# BaseParser
# ─────────────────────────────────────────────────────────────────────────────


class BaseParser:
    """Utilitaires partagés pour tous les parseurs XML / Markdown / Lua."""

    content_type: ContentType = ContentType.UNKNOWN

    def _fail(
        self,
        snippet: str,
        exc: Exception,
        source_file: str,
    ) -> None:
        """Journalise + quarantine une erreur de parsing."""
        err = ParseError(
            chunk_id=str(uuid.uuid4()),
            type=self.content_type.value,
            snippet=snippet[:500],
            exc=repr(exc),
            raw_snippet=snippet,
            source_file=source_file,
            timestamp=datetime.now(timezone.utc).isoformat(),
            game_version=get_current_game_version().value,
            exc_info=f"{type(exc).__name__}: {exc}",
        )
        _quarantine(err)
        logger.warning(
            f"[{self.content_type.value}] Parsing error quarantined",
            extra={"correlation_id": err.chunk_id},
        )


# ─────────────────────────────────────────────────────────────────────────────
# ItemParser
# ─────────────────────────────────────────────────────────────────────────────


class ItemParser(BaseParser):
    content_type = ContentType.ITEM

    def parse_xml_item(self, xml_path: str | Path) -> list[ParsedChunk]:
        """Extrait tous les <item> d'un items.xml."""
        chunks: list[ParsedChunk] = []
        path = Path(xml_path)

        try:
            tree = DefusedET.parse(str(path))
            root = tree.getroot()
        except ET.ParseError as exc:
            self._fail(f"<parse error in {path}>", exc, str(path))
            return chunks

        for element in root.findall("item"):
            try:
                chunk = self._parse_element(element, path)
                chunks.append(chunk)
            except Exception as exc:
                snippet = ET.tostring(element, encoding="unicode")[:500]
                self._fail(snippet, exc, str(path))

        logger.info(f"[ItemParser] Parsed {len(chunks)} items from {path.name}")
        return chunks

    def _parse_element(
        self,
        element: ET.Element,
        source_file: Path,
    ) -> ParsedChunk:
        version  = get_current_game_version()
        item_id  = _sanitise(element.get("id", ""))
        item_type = _sanitise(element.get("type", ""))
        display_name = _sanitise(element.get("DisplayName", ""))
        category = _sanitise(element.get("category", ""))

        lines = [f"Item: {display_name or item_id}  [{item_type}]"]
        if category:
            lines.append(f"Category: {category}")

        meta: dict[str, Any] = {
            "item_id": item_id,
            "type": item_type,
        }

        for child in element:
            tag  = child.tag.lower()
            text = _sanitise(child.text)
            if not text:
                continue

            if tag in ("displayname", "category", "icon", "weight"):
                meta[tag] = text
                lines.append(f"{tag.capitalize()}: {text}")

            elif tag == "attribute":
                attr_name = child.get("name", "?")
                attr_val  = _sanitise(child.text) or "?"
                meta[f"attr_{attr_name}"] = attr_val
                lines.append(f"Attribute {attr_name}: {attr_val}")

            else:
                meta[tag] = text
                lines.append(f"{tag.capitalize()}: {text}")

        return ParsedChunk(
            id=str(uuid.uuid4()),
            type=self.content_type.value,
            version=version.value,
            title=display_name or item_id,
            content="\n".join(lines),
            metadata=meta,
            source_file=str(source_file),
            parsed_at=datetime.now(timezone.utc).isoformat(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# RecipeParser
# ─────────────────────────────────────────────────────────────────────────────


class RecipeParser(BaseParser):
    content_type = ContentType.RECIPE

    def parse_xml_recipe(self, xml_path: str | Path) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        path = Path(xml_path)

        try:
            tree = DefusedET.parse(str(path))
            root = tree.getroot()
        except ET.ParseError as exc:
            self._fail(f"<parse error in {path}>", exc, str(path))
            return chunks

        for element in root.findall("recipe"):
            try:
                chunk = self._parse_element(element, path)
                chunks.append(chunk)
            except Exception as exc:
                snippet = ET.tostring(element, encoding="unicode")[:500]
                self._fail(snippet, exc, str(path))

        logger.info(f"[RecipeParser] Parsed {len(chunks)} recipes from {path.name}")
        return chunks

    def _parse_element(self, element: ET.Element, source_file: Path) -> ParsedChunk:
        version = get_current_game_version()
        name    = _sanitise(element.get("name", ""))
        result  = _sanitise(element.get("result", ""))
        cat     = _sanitise(element.get("category", ""))

        lines = [f"Recipe: {name}", f"Produces: {result}"]
        if cat:
            lines.append(f"Category: {cat}")

        meta: dict[str, Any] = {"name": name, "result": result}

        for ing in element.findall("ingredient"):
            item  = _sanitise(ing.get("item", ""))
            count = _sanitise(ing.get("count", "1"))
            lines.append(f"  Ingredient: {item}  x{count}")
            meta.setdefault("ingredients", []).append({"item": item, "count": count})

        for skill_el in element.findall("skill required"):
            skill = _sanitise(skill_el.get("name", ""))
            level = _sanitise(skill_el.get("level", ""))
            if skill:
                lines.append(f"  Skill required: {skill}  Level {level}")
                meta.setdefault("skills", []).append({"skill": skill, "level": level})

        return ParsedChunk(
            id=str(uuid.uuid4()),
            type=self.content_type.value,
            version=version.value,
            title=f"Recipe: {name}",
            content="\n".join(lines),
            metadata=meta,
            source_file=str(source_file),
            parsed_at=datetime.now(timezone.utc).isoformat(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# TraitParser
# ─────────────────────────────────────────────────────────────────────────────


class TraitParser(BaseParser):
    content_type = ContentType.TRAIT

    def parse_xml_trait(self, xml_path: str | Path) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        path = Path(xml_path)

        try:
            tree = DefusedET.parse(str(path))
            root = tree.getroot()
        except ET.ParseError as exc:
            self._fail(f"<parse error in {path}>", exc, str(path))
            return chunks

        for element in root.findall("trait"):
            try:
                chunk = self._parse_element(element, path)
                if chunk:
                    chunks.append(chunk)
            except Exception as exc:
                snippet = ET.tostring(element, encoding="unicode", short_empty_elements=True)[:500]
                self._fail(snippet, exc, str(path))

        logger.info(f"[TraitParser] Parsed {len(chunks)} traits from {path.name}")
        return chunks

    def _parse_element(self, element: ET.Element, source_file: Path) -> Optional[ParsedChunk]:
        version = get_current_game_version()
        name    = _sanitise(element.get("name", ""))
        if not name:
            return None

        icon   = _sanitise(element.get("icon", ""))
        desc   = _sanitise(element.findtext("description", ""))
        perks  = [_sanitise(p.text or "") for p in element.findall("perk") if p.text]
        spells = [_sanitise(s.text or "") for s in element.findall("spell") if s.text]

        meta: dict[str, Any] = {"icon": icon, "perks": perks, "spells": spells}

        lines = [f"Trait: {name}"]
        if icon:
            lines.append(f"Icon: {icon}")
        if desc:
            lines.append(f"Description: {desc}")
        if perks:
            lines.append(f"Perks: {', '.join(perks)}")
        if spells:
            lines.append(f"Spells: {', '.join(spells)}")

        return ParsedChunk(
            id=str(uuid.uuid4()),
            type=self.content_type.value,
            version=version.value,
            title=f"Trait: {name}",
            content="\n".join(lines),
            metadata=meta,
            source_file=str(source_file),
            parsed_at=datetime.now(timezone.utc).isoformat(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# MechanicParser
# ─────────────────────────────────────────────────────────────────────────────


class MechanicParser(BaseParser):
    content_type = ContentType.MECHANIC

    def parse_markdown_mechanic(self, md_path: str | Path) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        path = Path(md_path)

        raw = path.read_text(encoding="utf-8")
        current_title: str = ""
        current_body: list[str] = []
        current_meta: dict[str, Any] = {}

        def _flush(title: str, body: list[str]) -> Optional[ParsedChunk]:
            if not title.strip():
                return None
            return _flush_to_chunk(title, body, self.content_type, dict(current_meta), path)

        for raw_line in raw.splitlines():
            stripped = raw_line.strip()

            if stripped.startswith("# ") and stripped[2:].strip():
                chunk = _flush(current_title, current_body)
                if chunk:
                    chunks.append(chunk)
                current_title = stripped[2:].strip()
                current_body = []
                current_meta = {}

            elif stripped.startswith("## "):
                current_body.append(stripped)

            elif stripped.startswith("<!-- meta:"):
                m = re.search(r"meta:\s*({.*?})\s*-->", stripped)
                if m:
                    try:
                        current_meta.update(json.loads(m.group(1)))
                    except json.JSONDecodeError:
                        pass

            else:
                current_body.append(stripped)

        chunk = _flush(current_title, current_body)
        if chunk:
            chunks.append(chunk)

        logger.info(f"[MechanicParser] Parsed {len(chunks)} mechanics from {path.name}")
        return chunks


# ─────────────────────────────────────────────────────────────────────────────
# LuaApiParser
# ─────────────────────────────────────────────────────────────────────────────


class LuaApiParser(BaseParser):
    content_type = ContentType.LUA_API

    def parse_lua_function(self, lua_doc_path: str | Path) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        path = Path(lua_doc_path)

        raw = path.read_text(encoding="utf-8")
        current_fn: str = ""
        current_doc: str = ""
        current_meta: dict[str, Any] = {}

        def _flush(fn: str, doc: str, meta: dict[str, Any]) -> Optional[ParsedChunk]:
            if not fn.strip():
                return None
            return _flush_to_chunk(fn, [doc], self.content_type, meta, path)

        for raw_line in raw.splitlines():
            stripped = raw_line.strip()

            if stripped.startswith("## "):
                chunk = _flush(current_fn, current_doc, current_meta)
                if chunk:
                    chunks.append(chunk)
                current_fn   = stripped[3:].strip()
                current_doc  = ""
                current_meta = {}

            elif stripped.startswith("### "):
                m = re.match(r"###\s+(\w+)\s*:\s*(\S+)\s*(?:—|-)\s*(.*)", stripped)
                if m:
                    param, ptype, pdesc = m.group(1), m.group(2), m.group(3)
                    current_meta.setdefault("params", []).append({
                        "name": param,
                        "type": ptype,
                        "description": pdesc,
                    })
                    current_doc += stripped + "\n"
                else:
                    current_doc += stripped + "\n"
            else:
                current_doc += stripped + "\n"

        chunk = _flush(current_fn, current_doc, current_meta)
        if chunk:
            chunks.append(chunk)

        logger.info(f"[LuaApiParser] Parsed {len(chunks)} functions from {path.name}")
        return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Parser — façade principale
# ─────────────────────────────────────────────────────────────────────────────


class Parser:
    """Parseur unifié. Auto-détecte le type de fichier par son extension."""

    def __init__(self) -> None:
        self.item_parser      = ItemParser()
        self.recipe_parser    = RecipeParser()
        self.trait_parser    = TraitParser()
        self.mechanic_parser = MechanicParser()
        self.lua_parser      = LuaApiParser()
        self._parsed_count        = 0
        self._quarantine_count    = 0

    def parse_file(self, file_path: str | Path) -> list[ParsedChunk]:
        """Parse un fichier source unique.

        Toutes les erreurs sont capturées et mises en quarantaine ;
        cette méthode ne raise jamais.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"[Parser] File not found: {path}")
            return []
        suffix = path.suffix.lower()
        try:
            if suffix in (".xml",):
                return self._parse_xml(path)
            elif suffix in (".md", ".markdown"):
                return self._parse_markdown(path)
            elif suffix in (".lua", ".luadoc"):
                return self._parse_lua(path)
            else:
                logger.warning(f"[Parser] Unknown suffix '{suffix}': {path}")
                return []
        finally:
            self._parsed_count += 1

    def parse_directory(
        self,
        root_dir: str | Path,
        patterns: tuple[str, ...] = ("*.xml", "*.md", "*.lua", "*.luadoc"),
    ) -> list[ParsedChunk]:
        """Parse récursivement tous les fichiers correspondants sous root_dir."""
        root = Path(root_dir)
        chunks: list[ParsedChunk] = []
        for pattern in patterns:
            for fp in root.rglob(pattern):
                parts = fp.parts
                if any(
                    p in ("backup", ".git", "quarantine", "__pycache__")
                    for p in parts
                ):
                    continue
                for chunk in self.parse_file(fp):
                    chunks.append(chunk)
        return chunks

    def stats(self) -> dict:
        return {
            "files_parsed": self._parsed_count,
            "quarantine_entries": self._quarantine_count,
        }

    # ── Dispatch interne ────────────────────────────────────────────────────

    def _parse_xml(self, path: Path) -> list[ParsedChunk]:
        name = path.stem.lower()
        if name == "items":
            return self.item_parser.parse_xml_item(path)
        elif name == "recipes":
            return self.recipe_parser.parse_xml_recipe(path)
        elif name == "traits":
            return self.trait_parser.parse_xml_trait(path)
        else:
            logger.debug(f"[Parser] XML file '{path.name}' — no dedicated parser")
            return []

    def _parse_markdown(self, path: Path) -> list[ParsedChunk]:
        return self.mechanic_parser.parse_markdown_mechanic(path)

    def _parse_lua(self, path: Path) -> list[ParsedChunk]:
        return self.lua_parser.parse_lua_function(path)
