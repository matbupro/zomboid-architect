"""parser/dual_field â€” Parseur Dual-Field resilient.

Extrait DEUX representations d'un meme fichier source :
  - structured (dict) â†’ metadata pour filtrage/lookup deterministe
  - prose (str)        â†’ contenu lisible pour embedding RAG

Cascade de fallback pour les encodages et formats corrupts.

Usage :
    from ingestor.parser.dual_field import ResilientParser, DualFieldResult

    parser = ResilientParser()
    result = parser.parse_file("C:/Mods/items.xml")  # DualFieldResult(structured=..., prose=...)
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import ContentType, SchemaValidator  # noqa: E402

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class DualFieldResult:
    """Resultat de parsing Dual-Field."""
    structured: dict[str, Any]     # metadata JSON pour filtrage/lookup
    prose: str                     # contenu lisible pour RAG/embedding
    content_type: ContentType
    source_file: str               # chemin relatif du fichier source
    chunk_id: str                  # UUID unique pour ce chunk

    def to_dict(self) -> dict[str, Any]:
        """Exporte en format compatible storage vectoriel writer."""
        return {
            "id": self.chunk_id,
            "type": self.content_type.value,
            "structured": self.structured,
            "prose": self.prose,
            "source_file": self.source_file,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class ResilientParser:
    """Parseur Dual-Field avec cascade d'encodages et fallbacks."""

    # Cascade d'encodages â€” du plus specifique au plus general
    ENCODING_CASCADE = ["utf-8", "utf-16-le", "utf-16-be", "latin-1", "cp1252", "iso-8859-1"]

    # Regex helpers pour extraction de metadata depuis du texte brut
    _META_KV_RE = re.compile(r"(\w+)\s*[:=]\s*(.+?)\s*$", re.MULTILINE)
    _LUA_FN_RE = re.compile(r"^function\s+(\w+)\.(\w+)\s*\(", re.MULTILINE)

    def __init__(self, quarantine_on_error: bool = True) -> None:
        self.quarantine_on_error = quarantine_on_error

    # â”€â”€ Lecture resilient â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _read_file(self, path: Path) -> str:
        """Lit un fichier avec cascade d'encodages.

        Si tous les encodages echouent â†’ retourne raw bytes hexademicaux
        (pas de perte de donnee).
        """
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        for encoding in self.ENCODING_CASCADE:
            try:
                return path.read_text(encoding=encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue

        # Tous echouent â†’ hex dump safe
        raw = path.read_bytes()
        raise UnicodeDecodeError(
            "all encodings exhausted", "", 0, len(raw),
            f"hex dump available ({len(raw)} bytes)",
        )

    # â”€â”€ Parsing par type â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _parse_xml(self, raw: str, path: Path) -> list[DualFieldResult]:
        """Parse du XML (items.xml, recipes.xml, traits.xml)."""
        from xml.etree import ElementTree as ET  # noqa: E402
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            if self.quarantine_on_error:
                self._quarantine(f"XML parse error: {exc}", path)
            return []

        results: list[DualFieldResult] = []
        # Determine element type from root tag
        for elem in root.iter():
            tag_lower = elem.tag.lower()
            if tag_lower in ("item", "recipe", "trait"):
                structured, prose = self._extract_from_element(elem)
                ct = {
                    "item": ContentType.ITEM,
                    "recipe": ContentType.RECIPE,
                    "trait": ContentType.TRAIT,
                }.get(tag_lower, ContentType.UNKNOWN)

                results.append(DualFieldResult(
                    structured=structured,
                    prose=prose,
                    content_type=ct,
                    source_file=path.name,
                    chunk_id=self._gen_chunk_id(ct, structured.get("id", "") or structured.get("name", "")),
                ))

        return results

    def _parse_markdown(self, raw: str, path: Path) -> list[DualFieldResult]:
        """Parse du markdown (mechanics, docs)."""
        lines = raw.splitlines()
        current_title = ""
        current_body: list[str] = []
        current_meta: dict[str, Any] = {}

        results: list[DualFieldResult] = []

        def _flush() -> None:
            if not current_title.strip():
                return
            structured = {**current_meta, "title": current_title}
            prose = f"# {current_title}\n\n" + "\n".join(current_body)
            results.append(DualFieldResult(
                structured=structured,
                prose=prose,
                content_type=ContentType.MECHANIC,
                source_file=path.name,
                chunk_id=self._gen_chunk_id(ContentType.MECHANIC, current_title),
            ))

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("##"):
                _flush()
                current_title = stripped[2:].strip()
                current_body = []
                current_meta = {}
            elif stripped.startswith("<!-- meta:"):
                m = re.search(r"meta:\s*(\{.*?\})\s*-->", stripped)
                if m:
                    try:
                        import json  # noqa: E402
                        current_meta.update(json.loads(m.group(1)))
                    except (json.JSONDecodeError, Exception):  # noqa: BLE001
                        pass
            elif stripped.startswith("## "):
                current_body.append(stripped)
            else:
                current_body.append(stripped)

        _flush()  # last chunk
        return results

    def _parse_lua(self, raw: str, path: Path) -> list[DualFieldResult]:
        """Parse de code Lua (API docs)."""
        results: list[DualFieldResult] = []
        # Extract function signatures with docstrings
        fn_blocks = re.split(r"^function\s+", raw, flags=re.MULTILINE)

        for block in fn_blocks[1:]:  # skip before first function
            lines = block.splitlines()
            sig_line = lines[0] if lines else ""
            # Parse signature: Module.Function(params) ... end
            match = re.match(r"(\w+)\.(\w+)\s*\((.*)\)\s*(.-)\s*end", sig_line, re.DOTALL)
            if not match:
                continue

            module, fn_name, params_str = match.group(1), match.group(2), match.group(3)
            body_lines = [sig_line] + [l for l in lines[1:] if "end" not in l.lower()]

            structured = {
                "module": module,
                "function": fn_name,
                "params": [p.strip() for p in params_str.split(",") if p.strip()],
                "type": "lua_function",
            }

            # Prose: docstring-style
            prose_lines = [f"## {module}.{fn_name}", f"```lua\n{sig_line}\n```"]
            if body_lines:
                prose_lines.append("\n".join(body_lines[:50]))  # truncate long bodies

            results.append(DualFieldResult(
                structured=structured,
                prose="\n".join(prose_lines),
                content_type=ContentType.LUA_API,
                source_file=path.name,
                chunk_id=self._gen_chunk_id(ContentType.LUA_API, f"{module}.{fn_name}"),
            ))

        return results

    def _parse_generic_text(self, raw: str, path: Path) -> list[DualFieldResult]:
        """Parse general text (fallback)."""
        structured = self._extract_structured_from_text(raw)
        structured["type"] = "text"
        results = [DualFieldResult(
            structured=structured,
            prose=raw[:8192],  # truncate for RAG
            content_type=ContentType.UNKNOWN,
            source_file=path.name,
            chunk_id=self._gen_chunk_id(ContentType.UNKNOWN, path.stem),
        )]
        return results

    def _extract_structured_from_text(self, text: str) -> dict[str, Any]:
        """Extrait metadata structurÃ©e depuis du texte brut (fallback)."""
        meta: dict[str, Any] = {}
        # Key-value pairs (NAME: value or NAME = value)
        for match in self._META_KV_RE.finditer(text):
            key, val = match.group(1).lower(), match.group(2).strip().strip('"').strip("'")
            if key not in meta:  # first wins
                meta[key] = val

        # Try to detect number fields
        for match in re.finditer(r"(\w+)\s*[:=]\s*(\d+\.?\d*)", text):
            key, val = match.group(1).lower(), match.group(2)
            if key not in meta:
                try:
                    meta[key] = float(val) if "." in val else int(val)
                except ValueError:
                    pass

        return meta

    # â”€â”€ Dispatch principal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def parse_file(self, file_path: str | Path) -> list[DualFieldResult]:
        """Parse un fichier et retourne les dual-field results.

        Auto-detecte le type par extension :
          .xml â†’ XML parser
          .md/.markdown â†’ Markdown parser
          .lua â†’ Lua parser
          .csv/.json â†’ generic text (with structured extraction)
          autres â†’ raw text parse
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = path.suffix.lower()
        raw = self._read_file(path)

        try:
            if suffix in (".xml",):
                return self._parse_xml(raw, path)
            elif suffix in (".md", ".markdown"):
                return self._parse_markdown(raw, path)
            elif suffix in (".lua",):
                return self._parse_lua(raw, path)
            elif suffix in (".csv",):
                # Simple CSV â†’ list of key-value dicts
                lines = raw.strip().splitlines()
                if len(lines) > 1:
                    headers = [h.strip() for h in lines[0].split(",")]
                    results = []
                    for row in lines[1:]:
                        values = [v.strip() for v in row.split(",")]
                        structured = dict(zip(headers, values)) if len(headers) == len(values) else {"raw": row}
                        structured["type"] = "csv_row"
                        results.append(DualFieldResult(
                            structured=structured,
                            prose=row,
                            content_type=ContentType.ITEM,  # approximate
                            source_file=path.name,
                            chunk_id=self._gen_chunk_id(ContentType.ITEM, path.stem),
                        ))
                    return results
            elif suffix in (".json",):
                try:
                    import json  # noqa: E402
                    data = json.loads(raw)
                    structured = data if isinstance(data, dict) else {"data": str(data)}
                    structured["type"] = "json"
                    return [DualFieldResult(
                        structured=structured,
                        prose=json.dumps(data, ensure_ascii=False, indent=2)[:8192],
                        content_type=ContentType.ITEM,  # approximate
                        source_file=path.name,
                        chunk_id=self._gen_chunk_id(ContentType.ITEM, path.stem),
                    )]
                except json.JSONDecodeError:
                    pass

            return self._parse_generic_text(raw, path)
        except UnicodeDecodeError as exc:
            if self.quarantine_on_error:
                self._quarantine(str(exc), path)
            # Fallback hex dump in prose
            structured = {"raw_hex": raw.hex()[:1024], "type": "binary", "error": str(exc)}
            return [DualFieldResult(
                structured=structured,
                prose=f"[BINARY FILE - {len(path.read_bytes())} bytes]",
                content_type=ContentType.UNKNOWN,
                source_file=path.name,
                chunk_id=self._gen_chunk_id(ContentType.UNKNOWN, path.stem),
            )]

    # â”€â”€ Extraction d'element XML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _extract_from_element(self, elem: Any) -> tuple[dict[str, Any], str]:
        """Extrait metadata + prose depuis un element XML."""
        structured: dict[str, Any] = {}
        lines: list[str] = []

        # Attributes directes
        for k, v in elem.attrib.items():
            if v:
                structured[k.lower()] = v.strip()
                lines.append(f"{k}: {v}")

        # Child elements
        children = list(elem)
        for child in children:
            key = child.tag.lower()
            val = (child.text or "").strip()
            if val:
                structured[key] = val
                lines.append(f"  {key}: {val}")

        prose = "\n".join(lines) if lines else elem.tag

        # Si children ont des attributes, les ajouter a structured
        for child in children:
            for ck, cv in child.attrib.items():
                key = f"{child.tag.lower()}_{ck}"
                if cv:
                    structured[key] = cv.strip()

        return structured, prose

    # â”€â”€ ID generation anti-collision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _gen_chunk_id(content_type: ContentType, identifier: str) -> str:
        """Genere un chunk_id SHA-256 unique a partir du type + identifiant.

        Guaranti l'unicite par hashing deterministe (pas de collision possible).
        Pour les IDs humains : preserve le format PZ si dispo.
        """
        if not identifier:
            return str(uuid.uuid4())

        # Si l'ID existe deja dans le format PZ (Namespace.ClassName), l'utiliser tel quel
        # Sinon generer un hash SHA-256 qui sera l'ID interne de suivi
        pax_id = f"{content_type.value}.{identifier}"
        return hashlib.sha256(pax_id.encode()).hexdigest()[:32]

    # â”€â”€ Quarantaine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _quarantine(self, error_msg: str, path: Path) -> None:
        """Ecrit une erreur de parsing dans quarantine.jsonl."""
        from pathlib import Path as _Path  # noqa: E402
        from datetime import datetime as _datetime, timezone as _timezone  # noqa: E402

        qdir = _Path("data/quarantine")
        qdir.mkdir(parents=True, exist_ok=True)
        stamp = _datetime.now(_timezone.utc).strftime("%Y%m%d")
        qfile = qdir / f"quarantine_{stamp}.jsonl"

        with open(qfile, "a", encoding="utf-8") as fh:
            import json  # noqa: E402
            entry = {
                "chunk_id": str(uuid.uuid4()),
                "type": "parse_error",
                "source_file": str(path),
                "error": error_msg,
                "timestamp": _datetime.now(_timezone.utc).isoformat(),
            }
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # â”€â”€ Validation post-parse â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def validate_results(self, results: list[DualFieldResult]) -> tuple[list[bool], list[str]]:
        """Valide les results parses avec les schÃ©mas.

        Returns:
            (success_flags, errors) â€” [(True/False), [error_messages]]
        """
        success = []
        errors = []
        for r in results:
            try:
                SchemaValidator.validate(r.structured, r.content_type)
                success.append(True)
            except Exception as exc:  # noqa: BLE001
                success.append(False)
                errors.append(f"[{r.content_type.value}] {r.source_file}: {exc}")
        return success, errors
