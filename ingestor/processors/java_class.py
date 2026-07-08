"""
java_class — Processeur d'ingestion de classes Java decompilées (Class Z).

Parse des fichiers .java issus de la decompilation du code source PZ
(TheIndoor/projectzomboid) et genere des chunks structuration pour injection
dans la collection `pz_java_api` StorageBackend.

Couverture Ciblee (classes prioritaires identifiees dans tasks.md):
  - ZombierStats     — HP, speed, damage par type de zombie
  - Item.Type / IngredientItem — types d'items et ingredients
  - FoodSpoilerItem   — nutrition stats, spoil mechanics
  - WeatherManager    — temperature/humidity/rainfall logic
  - WorldOccupancyTable — POI occupancy data
  - ServerOptions     — servert.ini params + defaults

Mappage :
  Chaque fichier .java → 1-3 chunks selon la taille de la classe
  Metadata : class_name, package, extends, implements, fields[], methods[], imports[]

Usage :
    from ingestor.processors.java_class import JavaClassProcessor
    proc = JavaClassProcessor("/path/to/decompiled/classes")
    result = await proc.extract()
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.governance.logger import get_logger

from .base import Processor, Chunk, ExtractionResult

logger = get_logger(__name__)


# =============================================================================
# Modeles de donnees pour la parse
# =============================================================================


@dataclass
class JavaField:
    """Un champ d'une classe Java."""
    name: str
    type_name: str
    access_modifier: str = "public"  # public/protected/private/static
    is_static: bool = False
    default_value: str | None = None


@dataclass
class JavaMethod:
    """Une methode d'une classe Java."""
    name: str
    return_type: str
    access_modifier: str = "public"
    parameters: list[tuple[str, str]] = field(default_factory=list)  # [(type, name), ...]
    is_static: bool = False
    is_abstract: bool = False
    javadoc: str = ""
    annotations: list[str] = field(default_factory=list)


@dataclass
class JavaClass:
    """Representation d'une classe Java decompilee."""
    name: str
    package: str = ""
    extends: str | None = None
    implements: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    fields: list[JavaField] = field(default_factory=list)
    methods: list[JavaMethod] = field(default_factory=list)
    javadoc: str = ""
    source_file: str = ""


# =============================================================================
# Parseur Java (regex-based, pas de dependance externe)
# =============================================================================

_CLASS_HEADER_RE = re.compile(
    r'(?:public|private|protected)\s+(?:static\s+)?(?:abstract\s+)?class\s+(\w+)'
    r'(?:\s+extends\s+([\w.<>\|]+\w))?'
    r'(?:\s+implements\s+([\w,\s.\|]+))?'
    r'\s*\{?',  # doit etre suivi d'au moins un { ou espace → {
)

_METHOD_RE = re.compile(
    r'(public|private|protected)\s*'
    r'(static\s+)?'
    r'(final\s+)?'
    r'(\w[\w<>\[\],\s\.]*?)\s+'       # return type (could be generic)
    r'(\w+)\s*'                         # method name
    r'\(([^)]*)\)'                     # parameters
    r'(?:\s+throws\s+\w+(?:,\s*\w+)*)?'  # throws clause
    r'\s*\{?',                         # opening brace (optional)
    re.DOTALL,
)

_FIELD_RE = re.compile(
    r'(public|private|protected)\s*'
    r'(static\s+)?'
    r'(final\s+)?'
    r'(\w[\w<>\[\],\s\.]*?)\s+'       # type
    r'(\w+)\s*=?\s*(.*?)(?:;|$)'       # name + optional default value
)

_IMPORT_RE = re.compile(r'^import\s+([\w.]+(?:\.\*)?);$', re.MULTILINE)

_JAVADOC_RE = re.compile(r'/\*\*(.*?)\*/', re.DOTALL)

_ANNOTATION_RE = re.compile(r'@(\w+)\s*([^@\n]*)')


def _parse_javadoc(text: str) -> dict[str, str]:
    """Parse un bloc Javadoc en dictionnaire (tags → value).

    Le texte doit etre le contenu brut entre /** et */.
    """
    result: dict[str, str] = {}

    # Init des accumulateurs
    for tag in ('param', 'return', 'throws', 'deprecated'):
        result[tag] = ""

    # Extraire les tags un par un avec non-greedy + fin de ligne
    for m in re.finditer(r'@(param|return|throws|deprecated)\s+(.*?)$', text, re.MULTILINE):
        tag = m.group(1)
        val = m.group(2).strip()
        if tag == 'param':
            # Le nom du parametre est le mot juste apres @param
            match_param = re.match(r'(\w+)\s+(.*)', val)
            if match_param:
                key = f"param_{match_param.group(1)}"
                result[key] = match_param.group(2).strip()
            # Sinon, on ajoute a l'accumulateur param (valeur orpheline)
        else:
            result[tag] += val + "\n"

    # Corps du Javadoc (sans les lignes de tags @)
    lines = text.split('\n')
    body_lines = [l for l in lines if not re.match(r'\s*@(param|return|throws|deprecated)\b', l)]
    body = '\n'.join(body_lines).strip()
    body = re.sub(r'^\s*\*\s*', '', body, flags=re.MULTILINE)
    result['_body'] = body.strip()
    return result


def _parse_parameters(param_str: str) -> list[tuple[str, str]]:
    """Parse la liste de parametres d'une methode en [(type, name), ...]."""
    if not param_str.strip():
        return []

    params = []
    # Split by comma, but handle generics like <String>
    depth = 0
    current = ""
    for ch in param_str:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == ',' and depth == 0:
            params.append(_parse_single_param(current.strip()))
            current = ""
            continue
        current += ch
    if current.strip():
        params.append(_parse_single_param(current.strip()))
    return params


def _parse_single_param(param_str: str) -> tuple[str, str]:
    """Parse un seul parametre : 'String key' → ('String', 'key')."""
    parts = param_str.strip().split()
    if len(parts) >= 2:
        # Handles generics like Map<String, String> — just take first part as type
        return parts[0] + (" ".join(parts[1:-1]) if len(parts) > 2 else ""), parts[-1]
    elif len(parts) == 1:
        return "unknown", parts[0]
    return "unknown", ""


def _parse_java_file(filepath: Path) -> JavaClass | None:
    """Parse un fichier .java en objet JavaClass.

    Utilise des regex pour extraire package, imports, class header, fields,
    methods, Javadoc et annotations. Gere les cas de decompilation (souvent
    sans package declare).

    Returns:
        JavaClass parse, ou None si le fichier ne contient pas de classe.
    """
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Impossible de lire %s : %s", filepath.name, exc)
        return None

    # Extraire le Javadoc global (celui qui precede la declaration de classe)
    javadoc_match = _JAVADOC_RE.search(content)
    javadoc_text = javadoc_match.group(1) if javadoc_match else ""
    javadoc_parsed = _parse_javadoc(javadoc_text)

    # Package
    pkg_match = re.search(r'^package\s+([\w.]+);', content, re.MULTILINE)
    package = pkg_match.group(1) if pkg_match else ""

    # Imports
    imports = _IMPORT_RE.findall(content)

    # Classe (header complet : extends/implements)
    class_match = _CLASS_HEADER_RE.search(content)
    if not class_match:
        return None  # Pas de classe detectee (fichier vide ou comments seulement)

    class_name = class_match.group(1)
    extends = class_match.group(2) or None
    impl_str = class_match.group(3) or ""
    implements = [i.strip() for i in impl_str.split(",") if i.strip()] if impl_str else []

    # Corps de la classe : extraire le bloc entre les { de declaration et le } fermant
    # Position du debut du corps (apres le "(" du header ou le "extends/implements")
    class_body_start = content.find("{", class_match.start())
    if class_body_start == -1:
        class_body_start = class_match.end()

    # Trouver la correspondance fermante — compter les braces
    brace_depth = 0
    class_body_end = len(content)
    in_string = False
    in_char = False
    escape_next = False
    for i in range(class_body_start, len(content)):
        ch = content[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"' and not in_char:
            in_string = not in_string
        elif ch == "'" and not in_string:
            in_char = not in_char
        elif not in_string and not in_char:
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    class_body_end = i
                    break

    body_content = content[class_body_start:class_body_end]

    # Champs (dans le corps, en-dehors des methodes)
    fields: list[JavaField] = []
    methods: list[JavaMethod] = []

    # Extraire le Javadoc pour chaque methode/champ
    # On fait un premier scan des javadocs par position
    all_javadocs: list[tuple[int, str]] = []  # (position_debut, texte)
    for m in _JAVADOC_RE.finditer(body_content):
        all_javadocs.append((m.start(), m.group(1)))

    def _get_javadoc(pos: int) -> str:
        """Trouve le Javadoc le plus proche avant la position donnee."""
        closest = ""
        for start, text in all_javadocs:
            if start <= pos and (pos - start) < 500:  # doit etre proche
                if not closest or start > int(closest.split("\t")[0]) if "\t" in closest else True:
                    closest = f"{start}\t{text}"
        return closest.split("\t", 1)[1] if closest and "\t" in closest else ""

    def _get_annotations(text_block: str) -> list[str]:
        """Extrait les annotations d'un bloc de texte."""
        return [m.group(1) for m in _ANNOTATION_RE.finditer(text_block)]

    # Parse des methodes : on cherche les signatures connues dans le corps
    for m in re.finditer(_METHOD_RE, body_content):
        full_match = m.group(0)
        start_pos = class_body_start + m.start()

        access = m.group(1)
        is_static = "static" in (m.group(2) or "")
        return_type = m.group(4).strip()
        method_name = m.group(5)
        param_str = m.group(6)

        # Skip constructors: le nom de la methode == le nom de la classe
        if method_name == class_name:
            continue  # constructeurs geres comme des methods specialisees si besoin

        javadoc_raw = _get_javadoc(start_pos)
        annotations = _get_annotations(full_match[:full_match.index("static") if "static" in full_match else 0])

        methods.append(JavaMethod(
            name=method_name,
            return_type=return_type,
            access_modifier=access,
            parameters=_parse_parameters(param_str),
            is_static=is_static,
            javadoc=javadoc_raw.strip(),
            annotations=annotations if annotations else [],
        ))

    # Parse des champs (en-dehors des methodes)
    # Approche : lignes contenant un type connu suivi d'un nom et ';'
    # On utilise _FIELD_RE mais on filtre les declarations de methodes deja vues
    method_spans = set()
    for m in re.finditer(_METHOD_RE, body_content):
        for i in range(m.start(), m.end()):
            method_spans.add(i)

    for m in re.finditer(_FIELD_RE, body_content):
        start_pos = class_body_start + m.start()
        if start_pos in method_spans:
            continue  # skip — fait partie d'une methode (ex: return type dans signature)

        access = m.group(1)
        is_static = "static" in (m.group(2) or "")
        field_type = m.group(4).strip()
        field_name = m.group(5)
        default_val = m.group(6).strip().rstrip(";") if m.group(6) else None

        javadoc_raw = _get_javadoc(start_pos)

        fields.append(JavaField(
            name=field_name,
            type_name=field_type,
            access_modifier=access,
            is_static=is_static,
            default_value=default_val,
        ))

    return JavaClass(
        name=class_name,
        package=package,
        extends=extends,
        implements=implements,
        imports=[imp.replace("static ", "") for imp in imports],
        fields=fields,
        methods=methods,
        javadoc=javadoc_parsed.get("_body", ""),
        source_file=filepath.name,
    )


# =============================================================================
# Processeur Java Class Z
# =============================================================================

_TARGET_CLASSES = frozenset([
    "ZombierStats", "Item", "IngredientItem", "FoodSpoilerItem",
    "WeatherManager", "WorldOccupancyTable", "ServerOptions",
])


class JavaClassProcessor(Processor):
    """Processeur d'ingestion de classes Java decompilées.

    Lit tous les fichiers .java depuis un dossier, parse chaque classe
    et genere des chunks structuration pour la collection pz_java_api.
    """

    def __init__(self, source: str | Path):
        self.source = Path(source)
        # On n'appelle pas super().__init__() car ce processeur n'utilise pas config.CHUNK_SIZE
        self.config = None  # type: ignore[assignment]
        self._cache: dict[str, Chunk] = {}

    async def extract(self, source: str | Path | None = None) -> ExtractionResult:  # type: ignore[override]
        """Extrait toutes les classes Java du dossier (ou d'un fichier unique).

        Args:
            source: si fourni et pointe vers un fichier .java, parse uniquement ce fichier.
                    Si absent ou pointe vers un dossier, parse tout le dossier source.

        Returns:
            ExtractionResult avec un chunk par classe.
        """
        # Mode fichier unique (appel externe via cli.py)
        if source is not None and Path(source).is_file():
            self.source = Path(source).parent
            return self._extract_single_file(Path(source))

        start_time = time.monotonic()

        if not self.source.is_dir():
            raise ValueError(f"Source n'est pas un repertoire : {self.source}")

        java_files = sorted(self.source.glob("**/*.java"))
        if not java_files:
            logger.warning("Aucun fichier .java trouve dans %s", self.source)

        classes: list[JavaClass] = []
        parse_errors: list[str] = []

        for jf in java_files:
            try:
                cls = _parse_java_file(jf)
                if cls is not None:
                    classes.append(cls)
            except Exception as exc:
                parse_errors.append(f"{jf.name}: {exc}")

        # Generer les chunks
        chunks: list[Chunk] = []
        class_refs: list[tuple[str, str]] = []  # (class_a, class_b) cross-refs

        for cls in classes:
            chunk_text = _format_class_chunk(cls)
            is_target = cls.name in _TARGET_CLASSES or any(
                tc in cls.imports for tc in _TARGET_CLASSES
            )

            # Cross-references : les types utilises par cette classe
            referenced_types = set()
            for f in cls.fields:
                referenced_types.add(f.type_name)
            for m in cls.methods:
                referenced_types.add(m.return_type)
                for pt, _ in m.parameters:
                    referenced_types.add(pt)

            # Collecter les refs vers d'autres classes connues (pour data_links)
            for ref in referenced_types:
                base = ref.split(".")[0] if "." in ref else ref
                if any(c.name == base for c in classes):
                    class_refs.append((cls.name, base))

            # Metadata enrichie
            metadata: dict[str, Any] = {
                "type": "java_class",
                "class_name": cls.name,
                "package": cls.package,
                "extends": cls.extends,
                "implements": cls.implements,
                "field_count": len(cls.fields),
                "method_count": len(cls.methods),
                "imports": cls.imports[:20],  # max 20 imports dans metadata
                "is_target_class": is_target,
                "target_priority": cls.name in _TARGET_CLASSES,
                "class_refs": list(base for _, base in class_refs if _ == cls.name),
            }

            chunks.append(Chunk(
                text=chunk_text,
                index=len(chunks),
                start_offset=0,
                metadata=metadata,
            ))

        elapsed_ms = (time.monotonic() - start_time) * 1000

        # SHA-256 du dossier source (pour dedup entre runs)
        file_hash = ""
        if java_files:
            combined = "".join(f.name for f in sorted(java_files))
            file_hash = _compute_dir_hash(combined)

        return ExtractionResult(
            chunks=chunks,
            collection="pz_java_api",
            source=str(self.source),
            content_type="java_decompiled",
            file_hash=file_hash,
            word_count=sum(len(c.text.split()) for c in chunks),
            extraction_time_ms=elapsed_ms,
            metadata={
                "classes_parsed": len(classes),
                "total_fields": sum(len(c.fields) for c in classes),
                "total_methods": sum(len(c.methods) for c in classes),
                "target_classes_found": [c.name for c in classes if c.name in _TARGET_CLASSES],
                "parse_errors": parse_errors,
            },
        )

    def _extract_single_file(self, filepath: Path) -> ExtractionResult:
        """Parse un seul fichier .java."""
        cls = _parse_java_file(filepath)
        if cls is None:
            return ExtractionResult(collection="pz_java_api", source=str(filepath))

        chunks = [Chunk(
            text=_format_class_chunk(cls),
            index=0,
            start_offset=0,
            metadata={
                "type": "java_class",
                "class_name": cls.name,
                "package": cls.package,
                "extends": cls.extends,
                "implements": cls.implements,
                "field_count": len(cls.fields),
                "method_count": len(cls.methods),
                "is_target_class": cls.name in _TARGET_CLASSES,
            },
        )]

        return ExtractionResult(
            chunks=chunks,
            collection="pz_java_api",
            source=str(filepath),
            content_type="java_decompiled",
            file_hash=_compute_dir_hash(filepath.name),
            word_count=len(chunks[0].text.split()),
            extraction_time_ms=0,
            metadata={"classes_parsed": 1},
        )


def _format_class_chunk(cls: JavaClass) -> str:
    """Genere un texte structuration pour une classe Java (chunk content).

    Format optimise pour la recherche vectorielle : chaque chunk contient
    le contexte complet d'une classe avec methodes, champs et Javadoc.
    """
    parts = [f"// Class: {cls.name}"]
    if cls.package:
        parts.append(f"package {cls.package};")

    if cls.extends:
        parts.append(f"extends {cls.extends}")
    if cls.implements:
        parts.append(f"implements {', '.join(cls.implements)}")
    parts.append("{")

    # Javadoc
    if cls.javadoc:
        javadoc_clean = "\n".join(
            line.lstrip(" * ") for line in cls.javadoc.split("\n") if " * " in line or not line.strip()
        ).strip()
        if javadoc_clean:
            parts.append(f"/**\n * {javadoc_clean}\n */")

    # Imports utiles (uniquement ceux references dans la classe)
    if cls.imports:
        unique_imports = list(dict.fromkeys(cls.imports))  # dedupe conserve ordre
        parts.append(f"\n// {len(unique_imports)} imports:")
        for imp in unique_imports[:15]:
            parts.append(f"import {imp};")

    # Fields
    if cls.fields:
        parts.append("\n// Fields:")
        for f in cls.fields:
            static_str = "static " if f.is_static else ""
            default = f" = {f.default_value}" if f.default_value else ""
            parts.append(f"{f.access_modifier} {static_str}{f.type_name} {f.name}{default};")

    # Methods
    if cls.methods:
        parts.append("\n// Methods:")
        for m in cls.methods:
            sig_parts = [m.access_modifier]
            if m.is_static:
                sig_parts.append("static")
            sig_parts.append(m.return_type)
            sig_parts.append(m.name)

            # Parameters formates
            params_str = ", ".join(f"{pt} {pn}" for pt, pn in m.parameters)
            sig_parts.append(f"({params_str})")

            if m.annotations:
                parts[-1] += "  //" + " @".join([m.name] + [f"@{a}" for a in m.annotations])

            parts.append(" ".join(sig_parts) + " { ... }")

            # Param doc from Javadoc
            if m.javadoc:
                params = _parse_javadoc(m.javadoc)
                for pk, pv in sorted(params.items()):
                    if pk.startswith("param_"):
                        parts.append(f"    // param {pk[len('param_'):]}: {pv}")

    parts.append("}")
    return "\n".join(parts)


def _compute_dir_hash(source: str) -> str:
    """Hash de la source (fichier ou dossier)."""
    import hashlib
    if isinstance(source, str):
        encoded = source.encode("utf-8")
    else:
        encoded = b""
    return hashlib.sha256(encoded).hexdigest()
