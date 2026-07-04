"""
epub — Processeur pour eBooks (.epub).

Extraction du texte des chapitres + metadata (titre, auteur, etc.).
"""

from __future__ import annotations

import time
from pathlib import Path
from xml.etree import ElementTree as ET

from src.governance.logger import get_logger

logger = get_logger(__name__)


class EpubProcessor:
    """Extracteur de contenu eBook .epub (lecture de texte simple)."""

    SUPPORTED_EXTENSIONS = {".epub"}

    def __init__(self, config):
        self.config = config

    async def extract(self, source: str) -> "ExtractionResult":  # type: ignore[name-defined] # noqa: F821
        """Extrait le texte d'un fichier .epub.

        Returns:
            ExtractionResult avec chunks du contenu eBook.
        """
        from pathlib import Path
        from .base import Chunk, ExtractionResult
        import zipfile

        p = Path(source)
        start_time = time.monotonic()

        if not p.exists():
            raise FileNotFoundError(f"eBook non trouvé : {p}")

        try:
            # Un EPUB est une archive ZIP contenant des fichiers XHTML
            with zipfile.ZipFile(str(p)) as z:
                # Trouver le container.xml pour localiser OPF
                container_xml = None
                for name in z.namelist():
                    if 'META-INF/container.xml' in name:
                        container_xml = z.read(name).decode('utf-8')
                        break

                opf_path = None
                if container_xml:
                    import re
                    match = re.search(r'href=["\']([^"\']*\.opf)["\']', container_xml)
                    if match:
                        opf_rel = match.group(1)
                        # Chercher dans les fichiers de l'archive
                        for name in z.namelist():
                            if name.endswith(opf_rel):
                                opf_path = name
                                break

                # Extraire les textes des chapitres (fichiers XHTML)
                text_parts = []
                metadata = {}

                if opf_path:
                    try:
                        opf_content = z.read(opf_path).decode('utf-8')
                        root = ET.fromstring(opf_content)
                        # Extraire metadata Dublin Core
                        ns = {'dc': 'http://purl.org/dc/elements/1.1/',
                              'opf': 'http://www.idpf.org/2007/opf'}
                        title_el = root.find('.//dc:title', ns)
                        author_el = root.find('.//dc:creator', ns)
                        if title_el is not None:
                            metadata['title'] = title_el.text or ""
                        if author_el is not None:
                            metadata['author'] = author_el.text or ""
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Parsing OPF metadata échoué : %s", exc)

                # Extraire le contenu des chapitres (fichiers .xhtml/.xml dans spine)
                for name in z.namelist():
                    if not (name.endswith('.xhtml') or name.endswith('.html')):
                        continue
                    content = z.read(name).decode('utf-8', errors='replace')

                    # Enlever les balises XHTML pour garder le texte
                    import re
                    text = re.sub(r'<[^>]+>', ' ', content)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text:
                        text_parts.append(f"[{name}]\n{text}")

                full_text = "\n\n".join(text_parts)

        except zipfile.BadZipFile:
            raise ValueError("Fichier non un EPUB valide (zip corrompu)")
        except ImportError:
            logger.error("ebooklib manquant : pip install ebooklib")
            raise

        if not full_text.strip():
            return ExtractionResult(
                chunks=[], source=str(source), content_type="application/epub+zip",
                file_hash="", word_count=0, extraction_time_ms=(time.monotonic() - start_time) * 1000,
                metadata={"error": "Aucun contenu texte trouvé dans l'eBook"},
            )

        chunks = [Chunk(text=full_text[:self.config.CHUNK_SIZE], index=0, start_offset=0)]
        if len(full_text) > self.config.CHUNK_SIZE:
            remaining = full_text[self.config.CHUNK_SIZE:]
            chunks.append(Chunk(text=remaining[:self.config.CHUNK_SIZE], index=1, start_offset=self.config.CHUNK_SIZE))

        word_count = len(full_text.split())
        duration_ms = (time.monotonic() - start_time) * 1000

        return ExtractionResult(
            chunks=chunks,
            source=str(source),
            content_type="application/epub+zip",
            file_hash=self._compute_file_hash(p),
            word_count=word_count,
            extraction_time_ms=duration_ms,
            metadata={**metadata, "file_size_bytes": p.stat().st_size},
        )

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
