"""
image — Processeur images avec OCR (easyocr) et description vision API.

Flux :
1. easyocr extrait le texte de l'image (OCR multi-langue FR/EN)
2. Si Claude vision API dispo → génère une description textuelle en complément
3. Le texte + la description sont stockés dans pz_images
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import Chunk, ExtractionResult

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Extracteur OCR de images avec fallback description vision API."""

    SUPPORTED_MIMES = {
        "image/png", "image/jpeg", "image/jpg", "image/gif",
        "image/bmp", "image/webp", "image/tiff", "image/svg+xml",
    }

    def __init__(self, config):
        self.config = config

    async def extract(self, source: str) -> ExtractionResult:
        """Extrait le texte + description d'une image.

        Args:
            source: Chemin vers le fichier image.

        Returns:
            ExtractionResult avec chunks (texte OCR + description vision).
        """
        from pathlib import Path
        p = Path(source)
        start_time = time.monotonic()

        if not p.exists():
            raise FileNotFoundError(f"Image non trouvée : {p}")

        # Phase 1 : OCR
        ocr_text = self._ocr(p)

        # Phase 2 : Description vision API (optionnel, si Claude key dispo)
        description = ""
        if self.config.CLAUDE_API_KEY:
            description = await self._vision_description(p)

        full_text = f"[DESCRIPTION VISION]\n{description}\n\n[TEXTE OCR]\n{ocr_text}" if ocr_text and description else (ocr_text or description)

        if not full_text.strip():
            return ExtractionResult(
                chunks=[], source=str(source), content_type="image",
                file_hash="", word_count=0, extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Pas de texte ni description trouvé dans l'image"},
            )

        chunks = self._chunk(full_text)
        word_count = len(full_text.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            source=str(source),
            content_type="image",
            file_hash=self._compute_file_hash(p),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={
                "file_size_bytes": p.stat().st_size,
                "has_ocr": bool(ocr_text),
                "has_vision_description": bool(description),
                "image_type": p.suffix.lower(),
            },
        )

    def _ocr(self, path: Path) -> str:
        """OCR d'une image via easyocr."""
        try:
            import easyocr  # type: ignore[import-not-found]
            reader = easyocr.Reader(
                self.config.OCR_LANG.split("+"),
                gpu=False,
            )
            results = reader.readtext(str(path))

            # Fusionner les résultats (texte + confiance)
            text_parts = []
            for bbox, text, confidence in results:
                if confidence > 0.3:  # filtre faible confiance
                    text_parts.append(text)

            return "\n".join(text_parts)

        except ImportError:
            logger.error("easyocr non installé : pip install easyocr")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR image échoué (%s) : %s", path.name, exc)
            return ""

    async def _vision_description(self, path: Path) -> str:
        """Description de l'image via Claude vision API."""
        try:
            import httpx
            from pathlib import Path

            # Lire l'image en base64
            with open(path, "rb") as f:
                image_data = f.read()

            payload = {
                "model": self.config.OLLAMA_MODEL if self.config.OLLAMA_MODEL == "claude-sonnet-4-20250514" else "claude-sonnet-4-20250514",
                "max_tokens": 1024,
                "system": "Tu es un assistant d'analyse d'image. Décris le contenu textuel visible dans l'image de manière détaillée mais concise.",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Décris le texte visible dans cette image. Lis et transcris tout texte lisible. Si c'est un graphique ou un diagramme, décris les données visuellement.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{path.suffix.lstrip('.')};base64,{__import__('base64').b64encode(image_data).decode('utf-8')[:1_000_000]}",  # truncate for large files
                                },
                            },
                        ],
                    },
                ],
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.config.CLAUDE_API_KEY,  # type: ignore[arg-type]
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"]

            return ""

        except ImportError:
            logger.debug("httpx non disponible pour vision API.")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision description échoué (%s) : %s", path.name, exc)
            return ""

    def _chunk(self, text: str) -> list[Chunk]:
        """Chunking simple par parties (DESCRIPTION / TEXTE OCR)."""
        sections = []
        current_section = ""
        for line in text.split("\n"):
            if not current_section:
                current_section = line
            else:
                candidate = f"{current_section}\n{line}"
                if len(candidate) > self.config.CHUNK_SIZE:
                    sections.append(current_section.strip())
                    current_section = line
                else:
                    current_section = candidate

        if current_section.strip():
            sections.append(current_section.strip())

        return [Chunk(text=s, index=i, start_offset=text.find(s)) for i, s in enumerate(sections)]

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
