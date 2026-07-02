"""
video — Processeur vidéo avec extraction de frames + transcription audio.

Flux :
1. ffmpeg extrait des frames (images clés) de la vidéo (1 frame / 5s par défaut)
2. ffmpeg extrait l'audio pour transcriprion Whisper
3. easyocr OCR sur les frames importantes (détection de changement de scène)
4. whisper transcription du contenu audio
5. Fusion texte + descriptions des frames

Dépendances system : ffmpeg (winget install ffmpeg)
Dépendances python : ffmpeg-python, whisper, easyocr
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from .base import Chunk, ExtractionResult

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Extracteur de contenu vidéo (OCR frames + transcription audio)."""

    SUPPORTED_MIMES = {
        "video/mp4", "video/x-msvideo", "video/x-matroska",
        "video/webm", "video/quicktime", "video/x-ms-wmv",
    }

    def __init__(self, config):
        self.config = config
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="zomboid_video_"))

    async def extract(self, source: str) -> ExtractionResult:
        """Extrait le contenu d'un fichier vidéo (frames OCR + audio transcription).

        Args:
            source: Chemin vers le fichier vidéo.

        Returns:
            ExtractionResult avec chunks (texte frames OCR + transcrit audio).
        """
        from pathlib import Path
        p = Path(source)
        start_time = time.monotonic()

        if not p.exists():
            raise FileNotFoundError(f"Vidéo non trouvée : {p}")

        # Phase 1 : extraction des frames clés
        frames_dir = self._tmp_dir / f"frames_{p.stem}"
        frames_dir.mkdir(exist_ok=True)
        frame_paths = await self._extract_frames(str(p), str(frames_dir))

        # Phase 2 : OCR sur les frames (synthèse de texte visible)
        ocr_texts = []
        if frame_paths:
            for frame_path in frame_paths[:10]:  # max 10 frames pour éviter l'OOM
                ocr_text = self._ocr_frame(frame_path)
                if ocr_text.strip():
                    ocr_texts.append(ocr_text)

        # Phase 3 : transcription audio (si la vidéo a une piste audio)
        audio_text = await self._extract_audio_transcript(p)

        # Fusionner tout le contenu texte
        content_parts = []
        if ocr_texts:
            content_parts.append("--- TEXTES VISIBLES DANS LA VIDÉO ---\n" + "\n---\n".join(ocr_texts))
        if audio_text.strip():
            content_parts.append("--- TRANSCRIPTION AUDIO ---\n" + audio_text)

        full_text = "\n\n".join(content_parts) if content_parts else ""

        if not full_text.strip():
            return ExtractionResult(
                chunks=[], source=str(source), content_type="video",
                file_hash="", word_count=0, extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Aucun texte trouvé dans la vidéo (ni visible ni audio)"},
            )

        chunks = self._chunk(full_text)
        word_count = len(full_text.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            source=str(source),
            content_type="video",
            file_hash=self._compute_file_hash(p),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={
                "frames_extracted": len(frame_paths) if frame_paths else 0,
                "ocr_texts_found": len(ocr_texts),
                "audio_transcribed": bool(audio_text.strip()),
                "file_size_bytes": p.stat().st_size,
            },
        )

    async def _extract_frames(self, video_path: str, output_dir: str) -> list[str]:
        """Extrait des frames clés d'une vidéo via ffmpeg."""
        try:
            import subprocess
            # Extrait une frame toutes les 5 secondes (10 images max pour la vitesse)
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", r"select='eq(mod(n\,5)\,0)+eq(n\,0)'" + " -frames:v 10",  # frame 0 + une frame toutes les 5s (max 10)
                "-vsync", "vfr",
                str(output_dir) + "/frame_%04d.jpg",
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60.0,
            )

            if result.returncode != 0:
                logger.warning("ffmpeg frames extraction failed: %s", result.stderr[:200])
                return []

            # Lister les frames créées
            frames = sorted(Path(output_dir).glob("frame_*.jpg"))
            return [str(f) for f in frames if f.exists()]

        except FileNotFoundError:
            logger.error("ffmpeg non installé : winget install ffmpeg")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg timeout pendant frame extraction.")
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Frame extraction échouée : %s", exc)
            return []

    def _ocr_frame(self, frame_path: str) -> str:
        """OCR d'une frame via easyocr."""
        try:
            import easyocr  # type: ignore[import-not-found]
            reader = easyocr.Reader(
                self.config.OCR_LANG.split("+"),
                gpu=False,
            )
            results = reader.readtext(frame_path)

            text_parts = [line[1] for line in results if line[2] > 0.3]
            return "\n".join(text_parts[:5])  # max 5 lignes par frame

        except ImportError:
            logger.error("easyocr non installé : pip install easyocr")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR frame échoué (%s) : %s", frame_path, exc)
            return ""

    async def _extract_audio_transcript(self, video_path: Path) -> str:
        """Extrait et transcrit l'audio d'une vidéo."""
        audio_path = self._tmp_dir / f"audio_{video_path.stem}.wav"

        try:
            import subprocess
            # Extraire l'audio de la vidéo
            cmd = [
                "ffmpeg", "-i", str(video_path),
                "-vn",  # no video
                "-acodec", "pcm_s16le",  # WAV format
                "-ar", "16000",  # 16kHz (standard whisper)
                "-ac", "1",  # mono
                str(audio_path),
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120.0,
            )

            if result.returncode != 0 or not audio_path.exists():
                logger.warning("Extraction audio vidéo échouée : %s", video_path.name)
                return ""

            # Transcription avec whisper via Ollama (whisper-small modèle Ollama)
            return await self._transcribe_with_ollama(str(audio_path))

        except FileNotFoundError:
            logger.error("ffmpeg non installé : winget install ffmpeg")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning("Timeout extraction audio.")
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Extraction audio échouée : %s", exc)
            return ""

    async def _transcribe_with_ollama(self, audio_path: str) -> str:
        """Transcription audio via Ollama (modèle whisper)."""
        try:
            import httpx

            # Ollama supporte le Whisper via /api/generate avec le modèle "whisper"
            payload = {
                "model": "whisper-medium",
                "prompt": "",  # whisper n'a pas besoin de prompt
            }

            with open(audio_path, "rb") as f:
                audio_data = f.read()

            headers = {"Content-Type": "application/octet-stream"}
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.config.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                    data=audio_data,
                    headers=headers,
                    json=payload,  # modèle dans le JSON body (spécifique Ollama whisper)
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")

        except Exception as exc:  # noqa: BLE001
            logger.warning("Transcription Ollama échouée : %s", exc)
            return ""

    def _chunk(self, text: str) -> list[Chunk]:
        """Chunking simple par sections (OCR / Audio)."""
        import re
        # Split par les séparateurs de section
        sections = re.split(r'--- .* ---', text)
        chunks = []
        idx = 0
        offset = 0

        for i, section in enumerate(sections):
            stripped = section.strip()
            if not stripped:
                continue

            if len(stripped) > self.config.CHUNK_SIZE:
                # Split en sous-chunks (par phrases)
                sentences = re.split(r'(?<=[.!?])\s+', stripped)
                current = ""
                for s in sentences:
                    candidate = f"{current} {s}".strip()
                    if len(candidate) > self.config.CHUNK_SIZE and current.strip():
                        chunks.append(Chunk(text=current.strip(), index=idx, start_offset=offset))
                        idx += 1
                        offset += len(current.strip())
                        current = s
                    else:
                        current = candidate

                if current.strip():
                    chunks.append(Chunk(text=current.strip(), index=idx, start_offset=offset))
            else:
                chunks.append(Chunk(text=stripped, index=idx, start_offset=offset))

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
