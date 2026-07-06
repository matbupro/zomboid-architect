"""
base — Interface commune pour tous les processeurs d'ingestion.

Chaque processeur implémente Processor.extract() qui retourne des Chunk avec le contenu textuel.
Le multi-modal (images, vidéo, audio) est transformé en texte via OCR/transcription/vision API.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.governance.logger import get_logger


def _datetime_now_utc() -> str:
    """Retourne l'heure actuelle en UTC format ISO 8601."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _detect_is_url(text: str) -> bool:
    """Simple URL detection (avoids circular import from engine.py)."""
    return text.strip().startswith("http://") or text.strip().startswith("https://")

logger = get_logger(__name__)


@dataclass
class Chunk:
    """Un segment de texte extrait d'un fichier/URL.

    Chaque chunk est indépendant et contient assez de contexte pour la recherche.
    """
    text: str                # Contenu textuel du chunk
    index: int               # Position dans le document original
    start_offset: int        # Position en caractères dans le doc complet (0-based)
    metadata: dict = field(default_factory=dict)  # Metadata (source, type, lang, etc.)


@dataclass
class ExtractionResult:
    """Résultat d'une extraction de fichier/URL."""
    chunks: list[Chunk] = field(default_factory=list)
    collection: str = "pz_pdfs"            # Collection ChromaDB cible
    source: str = ""                       # Chemin ou URL source
    content_type: str = ""                 # MIME type
    file_hash: str = ""                    # SHA-256 du contenu brut (dedup)
    word_count: int = 0                    # Total mots extraits
    extraction_time_ms: float = 0          # Temps d'extraction (ms)
    metadata: dict = field(default_factory=dict)  # Metadata globales

    def save_raw(self, dirpath: str | Path) -> Path:
        """Sauvegarde le résultat brut en JSON sur disque.

        Le fichier JSON contient TOUT l'ExtractionResult (chunks + metadata).
        C'est la source de vérité pour reconstruction ChromaDB si besoin.

        Args:
            dirpath: Dossier cible (ex: data/raw/pz_text/). Créé s'il n'existe pas.

        Returns:
            Chemin du fichier JSON sauvegardé.
        """
        import json as _json

        p = Path(dirpath)
        p.mkdir(parents=True, exist_ok=True)

        # Nom du fichier : <sha256_8chars>_<nom_original>.json
        # Sanitize for Windows: remove \ / : * ? " < > |
        _WIN_BAD = set(r'\/:*?"<>|')
        def _sanitize(text: str) -> str:
            return "".join(ch if ch not in _WIN_BAD else "_" for ch in text)

        if _detect_is_url(self.source):
            name_part = "url_" + _sanitize(self.source[:60])
        else:
            safe_name = Path(self.source).name
            name_part = _sanitize(safe_name) if safe_name else _sanitize(Path(self.source).stem)
        hash_part = self.file_hash[:12] if self.file_hash else "nohash"
        fname = f"{hash_part}_{name_part}.json"

        filepath = p / fname

        # Serialisation
        payload = {
            "_meta": {
                "format": "ingestion_raw_v1",
                "source": self.source,
                "content_type": self.content_type,
                "collection": self.collection,
                "file_hash": self.file_hash,
                "word_count": self.word_count,
                "extraction_time_ms": self.extraction_time_ms,
                "saved_at": _datetime_now_utc(),
            },
            "chunks": [
                {
                    "text": c.text,
                    "index": c.index,
                    "start_offset": c.start_offset,
                    "metadata": c.metadata,
                }
                for c in self.chunks
            ],
            "metadata": self.metadata,
        }

        tmp = str(filepath) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        import shutil as _shutil
        _shutil.move(tmp, str(filepath))

        logger.debug("Raw sauvegardé : %s (%d chunks)", filepath.name, len(self.chunks))
        return filepath


class Processor(ABC):
    """Interface abstraite pour tous les processeurs de format.

    Chaque sous-classe implémente :
      - extract(source) → ExtractionResult
      - chunk(text) → list[Chunk]  (optionnel, default dans base class)
    """

    def __init__(self, config):
        self.config = config
        self._cache: dict[str, Chunk] = {}  # cache pour dedup intra-chunk

    @abstractmethod
    async def extract(self, source: str) -> ExtractionResult:
        """Extrait le contenu textuel d'une source (fichier ou URL).

        Args:
            source: Chemin vers un fichier ou une URL.

        Returns:
            ExtractionResult avec chunks et metadata complètes.
        Raises:
            ValueError: Si la source n'est pas valide pour ce processeur.
            PermissionError: Si le fichier est protégé/mot de passe (PDF).
        """
        ...

    def chunk_text(self, text: str) -> list[Chunk]:
        """Découpe du texte brut en chunks avec chevauchement."""
        if not text or not text.strip():
            return []

        # Découpe par paragraphes d'abord (plus contextuellement cohérent)
        paragraphs = self._split_paragraphs(text)
        chunks: list[Chunk] = []
        idx = 0
        offset = 0

        current_chunk_text = ""
        chunk_start = 0

        for para in paragraphs:
            if not para.strip():
                continue

            # Si l'ajout dépasse CHUNK_SIZE, on ferme le chunk actuel
            if len(current_chunk_text) + len(para) > self.config.CHUNK_SIZE and current_chunk_text:
                chunks.append(Chunk(
                    text=current_chunk_text.strip(),
                    index=idx,
                    start_offset=chunk_start,
                    metadata={"paragraphs": para.count("\n") + 1},
                ))
                # Chevronnement (overlap) : on garde les derniers mots du chunk précédent
                overlap_words = self.config.CHUNK_OVERLAP
                if overlap_words > len(current_chunk_text):
                    overlap_words = len(current_chunk_text)

                # Split en mots et prend les derniers N mots comme overlap
                words = current_chunk_text.strip().split()
                if words and overlap_words > 0:
                    overlap_text = " ".join(words[-overlap_words:]) + " "
                else:
                    overlap_text = ""

                current_chunk_text = overlap_text
                idx += 1
            else:
                chunk_start = offset - len(overlap_text) if chunks and chunks[-1].text == current_chunk_text else offset

            current_chunk_text += "\n\n" + para if current_chunk_text.strip() else para
            offset += len(para) + 2  # +2 pour les sauts de ligne séparateurs

        # Chunk final
        if current_chunk_text.strip():
            chunks.append(Chunk(
                text=current_chunk_text.strip(),
                index=idx,
                start_offset=chunk_start,
                metadata={"paragraphs": len(chunks) if chunks else 1},
            ))

        return chunks

    def compute_hash(self, content: str | bytes) -> str:
        """Calcule SHA-256 pour deduplication."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    # -- Helpers internes --

    def _split_paragraphs(self, text: str) -> list[str]:
        """Découpe le texte en paragraphes (lignes double-sautées ou simples sauts de ligne)."""
        # Sépare par double saut de ligne ou triple (paragraphes)
        paragraphs = []
        current = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if current:
                    paragraph = "\n".join(current).strip()
                    if paragraph:
                        paragraphs.append(paragraph)
                    current = []
                continue
            current.append(line)

        # Dernier paragraphe
        if current:
            paragraph = "\n".join(current).strip()
            if paragraph:
                paragraphs.append(paragraph)

        # Fallback : si pas de paragraphes détectés, split par lignes non vides
        if not paragraphs and text.strip():
            return [text.strip()]

        return paragraphs
