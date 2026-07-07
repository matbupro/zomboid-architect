"""
processors — Tous les processeurs d'ingestion multi-format.

Chaque module implémente un processeur pour un type de contenu spécifique.
L'interface commune est Processor.extract() retournant ExtractionResult.
"""

from .text import TextProcessor
from .pdf import PDFProcessor
from .image import ImageProcessor
from .video import VideoProcessor
from .audio import AudioProcessor
from .docx import DocxProcessor
from .epub import EpubProcessor
from .web import WebProcessor
from .pbo import PBOProcessor
from .wikijson import WikiJsonProcessor

__all__ = [
    "TextProcessor",
    "PDFProcessor",
    "ImageProcessor",
    "VideoProcessor",
    "AudioProcessor",
    "DocxProcessor",
    "EpubProcessor",
    "WebProcessor",
    "PBOProcessor",
    "WikiJsonProcessor",
]
