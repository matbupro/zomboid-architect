"""
pbo — Processeur d'archives .pbo (format ArmA/Project Zomboid).

Extrait les fichiers des archives .pbo (.pbosync) en utilisant py7zr (LZMA compression).
Les fichiers extraits (.lua, .txt, .bin configs) sont ensuite traites comme du texte brut
et retournes en chunks avec metadata de traçabilité.

Note: Le format .pbo utilise CA compression (LZMA), compatible avec py7zr.
Les archives BOSS (chiffrees) ne sont pas supportees — celles-ci sont rares dans le Workshop PZ.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Chunk extrait d'une archive .pbo."""
    text: str
    index: int
    start_offset: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class PBOProcessor:
    """Processeur de fichiers d'archives .pbo pour le pipeline d'ingestion.

    Extraction → detection contenu → chunking → retour ExtractionResult.
    Suit l'interface Processor.extract() definie dans processors/base.py.
    """

    SUPPORTED_EXTENSIONS = {".pbo", ".pbosync"}
    TEXT_EXTENSIONS = {".lua", ".txt", ".bin", ".cfg", ".csv", ".json", ".xml", ".toml", ".ini", ".hpp", ".cpp"}

    def __init__(self, config=None, extract_to: Path | None = None):
        """
        Args:
            config: IngestorConfig (optionnel, non utilise directement).
            extract_to: Repertoire pour l'extraction temporaire. Par defaut: dossier adjacent au .pbo.
        """
        self.config = config
        self._extract_to = extract_to

    async def extract(self, source: str) -> Any:  # ExtractionResult — avoid import cycle
        """Extraire et chunk un fichier .pbo/.pbosync.

        Args:
            source: Chemin vers le fichier .pbo a traiter.

        Returns:
            ExtractionResult avec chunks extraits du contenu du fichier archive.
        """
        from ..config import IngestorConfig, load_config  # lazy import to avoid base.py cycle
        from .base import Chunk as BaseChunk, ExtractionResult

        p = Path(source)
        start_ms = time.time() * 1000

        if not p.exists():
            logger.error("Fichier .pbo non trouve: %s", source)
            return ExtractionResult(
                chunks=[], collection="pz_mod_configs", source=source,
                content_type="application/x-pbo", file_hash="", extraction_time_ms=0,
                metadata={"error": "file_not_found"}, word_count=0,
            )

        if p.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            logger.warning("Extension non supportee .pbo: %s (attendu %s)", p.suffix, self.SUPPORTED_EXTENSIONS)
            return ExtractionResult(
                chunks=[], collection="pz_mod_configs", source=source,
                content_type=f"application/x-pbo-{p.suffix}", file_hash="", extraction_time_ms=0,
                metadata={"error": "unsupported_extension"}, word_count=0,
            )

        # Extract archive using py7zr
        extract_dir = self._extract_to or p.parent / f".pbo_extracted_{p.stem}"
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            import py7zr
            archive = py7zr.SevenZipFile(str(p), mode="r")
            archive.extractall(path=str(extract_dir))
            archive.close()
            logger.info(".pbo extrait vers %s (%d fichiers)", extract_dir, sum(1 for _ in extract_dir.rglob("*")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Echec extraction .pbo %s: %s (essai fallback sans extraction)", p.name, exc)
            # Fallback: if the .pbo is actually a plain directory (some PZ mods store files directly)
            return await self._extract_from_directory(p, source)

        # Process extracted files
        chunks = []
        index = 0
        total_words = 0
        processed_files = []

        for extracted_file in sorted(extract_dir.rglob("*")):
            if not extracted_file.is_file():
                continue

            ext = extracted_file.suffix.lower()
            rel_path = extracted_file.relative_to(extract_dir)

            # Try to read as text (skip binary files)
            if ext in self.TEXT_EXTENSIONS or ext == "":  # try reading extensionless files too
                try:
                    text = extracted_file.read_text(encoding="utf-8", errors="replace")
                    if not text.strip():
                        continue

                    # Truncate very large files
                    max_chars = 10000
                    if len(text) > max_chars:
                        logger.debug("Fichier tronque %s (%d → %d chars)", extracted_file.name, len(text), max_chars)
                        text = text[:max_chars]

                    chunk_meta = {
                        "pbo_file": p.name,
                        "internal_path": str(rel_path),
                        "extracted_from": "pbo_archive",
                        "content_type": f"text/x-pz-{ext.lstrip('.')}" if ext else "text/plain",
                    }

                    chunks.append(BaseChunk(
                        text=text,
                        index=index,
                        start_offset=0,
                        metadata=chunk_meta,
                    ))
                    processed_files.append(str(rel_path))
                    total_words += len(text.split())
                    index += 1
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Lecture texte echoue %s: %s", extracted_file.name, exc)

        elapsed_ms = time.time() * 1000 - start_ms

        collection = "pz_mod_configs"
        # Route Lua files to their own collection for better organization
        lua_chunks = [c for c in chunks if ".lua" in c.metadata.get("internal_path", "")]
        if lua_chunks and len(lua_chunks) > index // 2:  # majority are Lua → use separate collection
            collection = "pz_mod_lua_scripts"

        result = ExtractionResult(
            chunks=chunks,
            collection=collection,
            source=source,
            content_type="application/x-pbo",
            file_hash="",
            extraction_time_ms=elapsed_ms,
            metadata={
                "extracted_files": processed_files,
                "file_count": len(processed_files),
                "archive_path": str(p),
                "extraction_dir": str(extract_dir),
            },
            word_count=total_words,
        )

        logger.info(".pbo %s: %d chunks extraits (%d mots) dans '%s'", p.name, len(chunks), total_words, collection)
        return result

    async def _extract_from_directory(self, source_dir: Path, source: str) -> Any:
        """Fonction de repli: traiter les fichiers d'un repertoire comme s'ils etaient dans une archive."""
        from .base import Chunk as BaseChunk, ExtractionResult

        chunks = []
        index = 0
        total_words = 0
        processed_files = []

        for file_path in sorted(source_dir.rglob("*")):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            rel_path = file_path.relative_to(source_dir)

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                if not text.strip():
                    continue

                max_chars = 10000
                if len(text) > max_chars:
                    text = text[:max_chars]

                chunk_meta = {
                    "source": source,
                    "internal_path": str(rel_path),
                    "extracted_from": "directory_fallback",
                    "content_type": f"text/x-pz-{ext.lstrip('.')}" if ext else "text/plain",
                }

                chunks.append(BaseChunk(text=text, index=index, start_offset=0, metadata=chunk_meta))
                processed_files.append(str(rel_path))
                total_words += len(text.split())
                index += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("Lecture %s echoue: %s", file_path.name, exc)

        collection = "pz_mod_configs"
        lua_chunks = [c for c in chunks if ".lua" in c.metadata.get("internal_path", "")]
        if lua_chunks and len(lua_chunks) > index // 2:
            collection = "pz_mod_lua_scripts"

        return ExtractionResult(
            chunks=chunks, collection=collection, source=source,
            content_type="text/directory", file_hash="", extraction_time_ms=0,
            metadata={"extracted_files": processed_files, "file_count": len(processed_files)},
            word_count=total_words,
        )
