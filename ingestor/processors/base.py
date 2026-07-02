"""
base — Interface commune pour tous les processeurs d'ingestion.

Chaque processeur implémente Processor.extract() qui retourne des Chunk avec le contenu textuel.
Le multi-modal (images, vidéo, audio) est transformé en texte via OCR/transcription/vision API.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


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
