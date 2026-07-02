"""
audio — Processeur audio avec transcription complète.

Extrait le texte d'un fichier audio via :
1. Ollama (whisper-small/medium) si disponible
2. Fallback : transcription locale openai-whisper si installé

Dépendances : ollama whisper model, ou pip install openai-whisper
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import Chunk, ExtractionResult

logger = logging.getLogger(__name__)


class AudioProcessor:
    """Extracteur de transcription audio."""

    SUPPORTED_MIMES = {
        "audio/mpeg", "audio/wav", "audio/ogg", "audio/flac",
        "audio/aac", "audio/mp4",
    }

    def __init__(self, config):
        self.config = config

    async def extract(self, source: str) -> ExtractionResult:
        """Extrait la transcription complète d'un fichier audio.

        Args:
            source: Chemin vers le fichier audio.

        Returns:
            ExtractionResult avec chunks de la transcription.
        """
        from pathlib import Path
        p = Path(source)
        start_time = time.monotonic()

        if not p.exists():
            raise FileNotFoundError(f"Fichier audio non trouvé : {p}")

        # Phase 1 : tentative via Ollama (whisper model)
        transcription = await self._transcribe_ollama(str(p))

        if not transcription.strip():
            logger.info("Transcription Ollama vide/échoué, tentative fallback local...")
            transcription = await self._transcribe_local(str(p))

        if not transcription.strip():
            return ExtractionResult(
                chunks=[], source=str(source), content_type="audio",
                file_hash="", word_count=0, extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Transcription audio impossible (aucun backend disponible)"},
            )

        chunks = self._chunk(transcription)
        word_count = len(transcription.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            source=str(source),
            content_type="audio",
            file_hash=self._compute_file_hash(p),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={
                "transcription_method": "ollama" if transcription.strip() and not self._transcribe_local(str(p)) else "local",
                "file_size_bytes": p.stat().st_size,
            },
        )

    async def _transcribe_ollama(self, audio_path: str) -> str:
        """Transcription via Ollama (whisper model)."""
        try:
            import httpx

            with open(audio_path, "rb") as f:
                audio_data = f.read()

            # Whisper via Ollama : utiliser le modèle "whisper"
            # Note : l'API de whisper dans Ollama est différente du modèle standard
            payload = {
                "model": "whisper-medium",
                "prompt": "",
            }

            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{self.config.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                    data=audio_data,
                    headers={"Content-Type": "application/octet-stream"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")

        except FileNotFoundError:
            logger.error("ffmpeg manquant (nécessaire pour conversion audio).")
            return ""
        except ImportError:
            logger.debug("httpx non dispo pour transcrit Ollama.")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Transcrit Ollama échoué : %s", exc)
            return ""

    async def _transcribe_local(self, audio_path: str) -> str:
        """Transcription locale via openai-whisper (installé pip)."""
        try:
            import whisper  # type: ignore[import-not-found]

            logger.info("Chargement du modèle Whisper... (peut prendre quelques minutes)")
            model = whisper.load_model("small")  # "base" pour plus rapide, "large" pour plus précis
            result = model.transcribe(audio_path, language="fr")  # langue auto-détection possible
            return result.get("text", "")

        except ImportError:
            logger.debug("openai-whisper non installé : pip install openai-whisper")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Transcrit local échoué : %s", exc)
            return ""

    def _chunk(self, text: str) -> list[Chunk]:
        """Chunking par phrases (transcriptions sont longues)."""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if not sentences:
            return []

        chunks = []
        idx = 0
        offset = 0
        current = ""

        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current.strip() else sentence
            if len(candidate) > self.config.CHUNK_SIZE and current.strip():
                chunks.append(Chunk(text=current.strip(), index=idx, start_offset=offset))
                idx += 1
                offset += len(current.strip()) + 1
                current = sentence
            else:
                current = candidate

        if current.strip():
            chunks.append(Chunk(text=current.strip(), index=idx, start_offset=offset))

        return chunks

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
