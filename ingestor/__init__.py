"""
ingestor — Moteur d'ingestion multi-format pour le Knowledge Engine Zomboid.

Supporte : PDF, images (OCR), vidéo/audio (transcription), documents (docx/epub/txt), web crawling.
Tout est vectorisé via nomic-embed-text et stocké via StorageBackend (PostgreSQL/pgvector + Qdrant).
"""

__version__ = "0.2.0-alpha"
