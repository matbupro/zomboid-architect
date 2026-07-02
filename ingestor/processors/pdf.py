"""
pdf — Processeur PDF avec extraction texte + OCR fallback.

Flux :
1. pdfplumber extrait le texte directement (si le PDF n'est pas scanné)
2. Si peu de texte ou échec → easyocr sur les pages du PDF (PDF scanné/image)

Gère aussi les PDFs protégés par mot de passe (erreur PermissionError).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import Chunk, ExtractionResult

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Extracteur PDF avec fallback OCR pour les PDFs scannés."""

    SUPPORTED_MIMES = {"application/pdf"}

    def __init__(self, config):
        self.config = config

    async def extract(self, source: str) -> ExtractionResult:
        """Extrait le texte d'un fichier PDF.

        Args:
            source: Chemin vers le fichier PDF.

        Returns:
            ExtractionResult avec chunks du contenu.
        """
        from pathlib import Path
        p = Path(source)
        start_time = time.monotonic()

        if not p.exists():
            raise FileNotFoundError(f"PDF non trouvé : {p}")

        # Phase 1 : extraction texte directe (pdfplumber)
        text, extracted_text_length = self._extract_direct(p)

        if extracted_text_length < 20:
            # Phase 2 : OCR pour PDF scanné
            logger.info("Peu de texte direct (%d chars), fallback OCR sur le PDF %s", extracted_text_length, p.name)
            text, extracted_text_length = self._extract_ocr(p)

        if not text or not text.strip():
            return ExtractionResult(
                chunks=[], source=str(source), content_type="application/pdf",
                file_hash="", word_count=0, extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Aucun texte extrait du PDF (ni direct ni OCR)"},
            )

        chunks = self._chunk(text)
        word_count = len(text.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            source=str(source),
            content_type="application/pdf",
            file_hash=self._compute_file_hash(p),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={
                "extraction_method": "direct" if extracted_text_length > 20 else "ocr",
                "file_size_bytes": p.stat().st_size,
            },
        )

    def _extract_direct(self, path: Path) -> tuple[str, int]:
        """Extraction texte directe via pdfplumber."""
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                pages_text = []
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pages_text.append(f"--- Page {i+1} ---\n{text}")

                full_text = "\n".join(pages_text)
                return full_text, len(full_text)

        except pdfplumber.errors.PasswordError:  # type: ignore[attr-defined]
            raise PermissionError("PDF protégé par mot de passe.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Extraction directe PDF échouée : %s", exc)
            return "", 0

    def _extract_ocr(self, path: Path) -> tuple[str, int]:
        """OCR du PDF via easyocr sur chaque page."""
        try:
            import pdfplumber
            import easyocr  # type: ignore[import-not-found]

            reader = easyocr.Reader(['fr', 'en'], gpu=False)  # language config depuis config
            ocr_text_parts = []
            total_pages = 0

            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages):
                    img = page.to_image(resolution=300)
                    # easyocr prend une numpy array ou PIL Image
                    try:
                        result = reader.readtext(img.original)  # type: ignore[attr-defined]
                        page_text = "\n".join([line[1] for line in result if line[2] > 0.3])  # filtre confiance < 30%
                        if page_text.strip():
                            ocr_text_parts.append(f"--- Page {i+1} (OCR) ---\n{page_text}")
                            total_pages += 1
                    except Exception:  # noqa: BLE001
                        pass

            full_text = "\n".join(ocr_text_parts)
            return full_text, len(full_text)

        except ImportError:
            logger.error("easyocr non installé : pip install easyocr")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR PDF échoué : %s", exc)
            return "", 0

    def _chunk(self, text: str) -> list[Chunk]:
        """Chunking du texte PDF (séparé par pages)."""
        chunks = []
        idx = 0
        for page_section in text.split("--- Page"):
            if not page_section.strip():
                continue
            chunk_text = page_section.strip()
            if len(chunk_text) > self.config.CHUNK_SIZE:
                # Split en sous-chunks si une page est trop longue
                sub_chunks = self._split_large_chunk(chunk_text)
                for sc in sub_chunks:
                    chunks.append(Chunk(text=sc, index=idx, start_offset=text.find(sc)))
                    idx += 1
            else:
                chunks.append(Chunk(text=chunk_text, index=idx, start_offset=text.find(page_section)))
                idx += 1
        return chunks

    def _split_large_chunk(self, text: str) -> list[str]:
        """Split un chunk trop grand en sous-chunks."""
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            return [text]

        result = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip()
            if len(candidate) > self.config.CHUNK_SIZE:
                if current.strip():
                    result.append(current.strip())
                current = sentence
            else:
                current = candidate

        if current.strip():
            result.append(current.strip())
        return result

    def _split_sentences(self, text: str) -> list[str]:
        """Découpe en phrases (terminaison par .!? suivie d'espace)."""
        import re
        parts = re.split(r'(?<=[.!?])\s+', text)
        # Regrouper les parties courtes
        result = []
        current = ""
        for part in parts:
            if len(current) + len(part) > self.config.CHUNK_SIZE and current.strip():
                result.append(current.strip())
                current = part
            else:
                current = f"{current} {part}".strip() if current.strip() else part
        if current.strip():
            result.append(current.strip())
        return result if result else [text]

    def _compute_file_hash(self, path: Path) -> str:
        """SHA-256 du contenu brut."""
        import hashlib
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        except (OSError, IOError):
            pass
        return h.hexdigest()
