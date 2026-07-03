"""
text — Processeur pour fichiers texte bruts (.txt, .md, .csv, .json, .yml, etc.).

Extraction directe du contenu + chunking intelligent par paragraphes.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .base import Chunk, ExtractionResult

logger = logging.getLogger(__name__)


class TextProcessor:
    """Extracteur de texte brut pour fichiers texte."""

    SUPPORTED_EXTENSIONS = {
        ".txt", ".md", ".markdown", ".csv", ".json", ".jsonl",
        ".yml", ".yaml", ".toml", ".xml", ".html", ".htm",
        ".rst", ".org", ".adoc", ".tex",
        # Scripts et configs de jeux (Zomboid / ArmA / etc.)
        ".lua",
    }

    def __init__(self, config):
        self.config = config

    async def extract(self, source: str) -> ExtractionResult:
        """Extrait le texte brut d'un fichier.

        Args:
            source: Chemin vers le fichier.

        Returns:
            ExtractionResult avec chunks du contenu.
        """
        from pathlib import Path

        p = Path(source)
        start_time = time.monotonic()

        if not p.exists():
            raise FileNotFoundError(f"Fichier non trouvé : {p}")

        # Détection de l'encodage en cascade (latin-1 → utf-8 → cp1252 → etc.)
        content, encoding_used = self._read_with_fallback(p)

        if not content or not content.strip():
            return ExtractionResult(
                chunks=[], source=str(source), content_type="text/plain",
                file_hash="", word_count=0, extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"encoding": encoding_used},
            )

        # Détection du type de contenu à partir de l'extension
        ext = p.suffix.lower()
        content_type = f"text/{ext.lstrip('.')}"
        if ext == ".md":
            content_type = "text/markdown"

        # Chunking par paragraphes
        chunks = self._chunk(content)

        word_count = len(content.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            source=str(source),
            content_type=content_type,
            file_hash=self._compute_file_hash(p),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={
                "encoding": encoding_used,
                "file_size_bytes": p.stat().st_size,
                "extension": ext,
                "chunk_count": len(chunks),
            },
        )

    def _read_with_fallback(self, path: Path) -> tuple[str, str]:
        """Lit un fichier avec cascade d'encodages.

        Tente : utf-8 → cp1252 (Windows) → latin-1 → utf-16 → raw fallback.
        Returns (content_string, encoding_used).
        """
        encodings = ["utf-8", "cp1252", "latin-1", "utf-16"]

        for encoding in encodings:
            try:
                with open(path, encoding=encoding, errors="replace") as f:
                    content = f.read()
                if content:
                    return content, encoding
            except (UnicodeDecodeError, UnicodeError):
                continue

        # Fallback ultime : lire en binaire et décoder avec remplacement
        try:
            with open(path, "rb") as f:
                raw = f.read()
            return raw.decode("utf-8", errors="replace"), "raw-utf8"
        except Exception:  # noqa: BLE001
            logger.error("Impossible de lire %s avec aucun encodage.", path)
            return "", "error"

    def _chunk(self, text: str) -> list[Chunk]:
        """Découpe le texte en chunks contextuels."""
        if not text or not text.strip():
            return []

        paragraphs = self._split_paragraphs(text)
        chunks: list[Chunk] = []

        # Regrouper les paragraphes courts pour éviter des chunks minuscules
        buffer: list[str] = []
        chunk_start = 0
        idx = 0
        last_para_end = 0

        for para in paragraphs:
            if not para.strip():
                continue

            # Ajouter le paragraphe au buffer ou en créer un nouveau
            if len(buffer) == 0:
                buffer = [para]
                chunk_start = text.find(para)
            else:
                candidate_text = "\n\n".join(buffer + [para])
                if len(candidate_text) > self.config.CHUNK_SIZE:
                    # Le buffer est plein, on le valide
                    chunks.append(Chunk(
                        text="\n\n".join(buffer).strip(),
                        index=idx,
                        start_offset=chunk_start,
                        metadata={"paragraphs": len(buffer)},
                    ))
                    idx += 1

                    # L'overlap = les derniers mots du chunk précédent
                    overlap_words = self.config.CHUNK_OVERLAP // 5  # ~5 chars per word
                    if overlap_words > 3:
                        overlap_words = 3
                    last_words = buffer[-1].split()[-overlap_words:] if overlap_words > 0 else []

                    buffer = [" ".join(last_words)] if last_words else [para]
                    chunk_start = text.find(para, chunk_start)
                else:
                    buffer.append(para)
                    last_para_end = chunk_start + len("\n\n".join(buffer))

        # Chunk final (buffer restant)
        if buffer:
            chunks.append(Chunk(
                text="\n\n".join(buffer).strip(),
                index=idx,
                start_offset=chunk_start,
                metadata={"paragraphs": len(buffer)},
            ))

        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """Découpe en paragraphes (séparés par lignes vides)."""
        paragraphs = []
        current = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if current:
                    paragraphs.append("\n".join(current).strip())
                    current = []
            else:
                current.append(line)

        if current:
            paragraphs.append("\n".join(current).strip())

        return paragraphs if paragraphs else [text] if text.strip() else []

    def _compute_file_hash(self, path: Path) -> str:
        """SHA-256 du contenu brut (pour deduplication)."""
        import hashlib
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        except (OSError, IOError):
            pass
        return h.hexdigest()
