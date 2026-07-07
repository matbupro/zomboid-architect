"""
engine — Router de traitement.

Détecte le type de fichier/URL et délègue au processeur approprié.
Interface principale utilisée par cli.py pour orchestrer l'ingestion complète.
Ce module s'appuie sur `src/constants_shared.py` pour les mappings de fichiers
afin d'éviter la duplication (DRY).
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Centralisation des constantes partagées via constants_shared.py
from src.constants_shared import FILE_TYPE_MAP, MIME_TO_PROCESSOR_MAP
from .config import IngestorConfig, load_config
from .processors.base import Chunk, ExtractionResult

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Détecteur de type MIME / format
# ---------------------------------------------------------------------------


def _peek_text(path: Path | str) -> bool:
    """Retourne True si les premiers 1024 octets du fichier semblent etre du texte."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
        # Un fichier binaire contient des null bytes dans les premiers octets
        return b"\x00" not in chunk
    except Exception:
        return False


def detect_type(path: Path | str) -> tuple[str, str]:
    """Détecte le type de fichier et retourne (content_type, processor_key).

    Args:
        path: Chemin vers le fichier.

    Returns:
        Tuple (content_type MIME, nom du processeur à utiliser).
    Raises:
        ValueError: Si le type n'est pas supporté.
    """
    p = Path(path) if isinstance(path, str) else path

    # D'abord essayer l'extension
    ext = p.suffix.lower()
    extension_key = FILE_TYPE_MAP.get(ext, None)  # catégorie pour cette extension (si connue)
    content_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"

    # Si MIME guess échoue, utiliser le mapping extension centralisé
    if content_type == "application/octet-stream":
        content_type = ext_to_mime(ext)

    # Fallback : inspection du contenu (fichiers sans extension ou inconnus comme .env, Dockerfile)
    if not extension_key:
        try:
            is_text = _peek_text(p) or not p.stat().st_size  # texte OU fichier vide
        except FileNotFoundError:
            is_text = False
        name_lower = p.name.lower()
        known_config_exts = (".env", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf")
        known_config_names = ("dockerfile", "docker-compose.yml", "makefile", "license")
        if name_lower in known_config_names or is_text:
            content_type = "text/plain"
        else:
            content_type = "application/octet-stream"

    # Mappe content_type vers processor_key (utile pour les extensions connues dont le MIME != short key)
    processor_key = mime_to_processor(content_type)
    if not processor_key:
        raise ValueError(
            f"Type non supporté : {content_type} (fichier: {p.name})"
        )

    return content_type, processor_key


def detect_is_url(text: str) -> bool:
    """Détermine si une chaîne est une URL valide."""
    pattern = r'^https?://[a-zA-Z0-9]'
    return bool(re.match(pattern, text.strip()))


# ---------------------------------------------------------------------------
# Mapping MIME → processeur
# ---------------------------------------------------------------------------

def ext_to_mime(ext: str) -> str:
    """Conversion de l'extension vers MIME en utilisant FILE_TYPE_MAP.

    Ce mapping est dérivé des catégories de FILE_TYPE_MAP : chaque catégorie
    possède un préfixe MIME correspondant (ex: 'text' → 'text/plain').
    Les valeurs exactes sont vérifiées via les tests unitaires (test_engine.py).
    """
    category_to_mime = {
        "text": "text/plain",
        "web": "text/html",
        "xml": "application/xml",
        "lua": "text/x-lua",
        "pdf": "application/pdf",
        "image": "image/png",
        "audio": "audio/mpeg",
        "video": "video/mp4",
        "pbo": "application/x-pbo",
        "config_bin": "application/octet-stream",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "epub": "application/epub+zip",
        "texture": "image/png",
    }
    category = FILE_TYPE_MAP.get(ext)
    if not category:
        return "application/octet-stream"
    mime = category_to_mime.get(category, "text/plain")
    # Fallback : pour les images/audio/vidéo spécifiques, utiliser le mapping MIME_TO_PROCESSOR
    for mime_key, proc in MIME_TO_PROCESSOR_MAP.items():
        if mime_key.startswith("image/") and category == "image":
            return mime_key
        if mime_key.startswith("audio/") and category == "audio":
            return mime_key
        if mime_key.startswith("video/") and category == "video":
            return mime_key
    return mime


def mime_to_processor(content_type: str) -> str | None:
    """Mappe un type MIME vers le nom d'un processeur."""
    if content_type.startswith("text/") or content_type == "application/json":
        return "text"
    if "pdf" in content_type:
        return "pdf"
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    if "docx" in content_type:
        return "docx"
    if "epub" in content_type:
        return "epub"
    if "html" in content_type:
        return "web"  # pages HTML standalone
    if "pbo" in content_type:
        return "pbo"
    return None


# ---------------------------------------------------------------------------
# Router principal
# ---------------------------------------------------------------------------

class _HashIndex:
    """Stocke/recharge les hashes SHA-256 des fichiers ingeres (fichier .seen_hashes).

    Chaque entrée est : ``<sha256_hex>  <source_path>``.
    Persisté dans ``data/quarantine/.seen_hashes`` pour traverser les sessions.
    """

    _PATH_KEY = ".seen_hashes"

    @classmethod
    def load(cls) -> dict[str, str]:
        """Charge le fichier .seen_hashes → {hash: source}."""
        from ingestor.quarantine_manager import get_quarantine_path

        path = get_quarantine_path() / cls._PATH_KEY
        index: dict[str, str] = {}
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        index[parts[0]] = parts[1]
        return index

    @classmethod
    def save(cls, index: dict[str, str]) -> None:
        """Sauvegarde l'index sur disque (atomic write)."""
        from ingestor.quarantine_manager import get_quarantine_path

        path = get_quarantine_path() / cls._PATH_KEY
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for h, s in sorted(index.items()):
                f.write(f"{h}  {s}\n")
        shutil.move(tmp, str(path))


class IngestionEngine:
    """Orchestre l'ingestion : détection → processeur → embedding → storage.

    Supporte le mode incrementiel via ``hash_index`` : les fichiers déjà vus
    avec le même SHA-256 sont ignores (skip) pour éviter de re-traiter le contenu.
    """

    def __init__(self, config: IngestorConfig | None = None):
        self.config = config or load_config()

    # -- Ingestion d'un seul fichier/URL --

    async def ingest(self, source: str | Path, *, collection: str | None = None) -> ExtractionResult:
        """Ingest un seul fichier ou URL.

        Args:
            source: Chemin vers un fichier ou une URL.
            collection: Collection vectorielle cible (détection automatique si None).

        Returns:
            ExtractionResult avec chunks et metadata.
        """
        from .processors import text, pdf, image, video, audio, docx, epub, web as web_proc

        source_str = str(source)
        is_url = detect_is_url(source_str)

        if is_url:
            logger.info("Ingestion web : %s", source_str)
            result = await web_proc.WebProcessor(self.config).extract(source_str)
            collection = collection or "pz_web_pages"
        else:
            p = Path(source_str)
            if not p.exists():
                raise FileNotFoundError(f"Fichier non trouvé : {p}")

            content_type, processor_key = detect_type(p)
            logger.info("Ingestion fichier : %s (type=%s)", p.name, content_type)

            from .processors import pbo as pbo_proc
            from .processors import wikijson as wikijson_proc

            processors = {
                "text": text.TextProcessor(self.config),
                "pdf": pdf.PDFProcessor(self.config),
                "image": image.ImageProcessor(self.config),
                "video": video.VideoProcessor(self.config),
                "audio": audio.AudioProcessor(self.config),
                "docx": docx.DocxProcessor(self.config),
                "epub": epub.EpubProcessor(self.config),
                "pbo": pbo_proc.PBOProcessor(self.config),  # .pbo archive processing
            }

            # WikiJson — special case: source peut etre dossier OU fichier JSON
            if isinstance(source, Path) and source.is_dir():
                logger.info("Ingestion Data Drive (dossier) : %s", source.name)
                result = await wikijson_proc.WikiJsonProcessor(self.config).extract(str(source))
                collection = collection or "pz_items"
                # Sauvegarde brute (comme le path standard ci-dessous)
                raw_dir = self.config.DATA_ROOT / "raw"
                try:
                    saved_path = result.save_raw(raw_dir / collection)
                    logger.debug("Raw persiste : %s", saved_path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Echec sauvegarde brute de '%s' : %s", source_str, exc)
                logger.info("Ingestion Data Drive → %d chunks dans '%s'", len(result.chunks), collection)
                result.collection = collection
                return result

            # Si c'est un fichier .json → utiliser le text processor (pas wikijson automatique)
            # Le wikijson est appele via --ingest-wikidrive explicitement

            processor = processors.get(processor_key)
            if processor is None:
                raise ValueError(f"Pas de processeur pour '{processor_key}'")

            result = await processor.extract(source_str)
            # Sélection collection par défaut
            collection_map = {
                "text": "pz_text",
                "pdf": "pz_pdfs",
                "image": "pz_images",
                "video": "pz_videos",
                "audio": "pz_audios",
                "docx": "pz_docx",
                "epub": "pz_epub",
                "pbo": "pz_mod_configs",  # archive content → mod config collection
            }
            collection = collection or collection_map.get(processor_key, "pz_pdfs")

        result.collection = collection

        # -- Sauvegarde brute (source de vérité pour recharger le stockage vectoriel) --
        raw_dir = self.config.DATA_ROOT / "raw"
        try:
            saved_path = result.save_raw(raw_dir / collection)
            logger.debug("Raw persisté : %s", saved_path)
        except Exception as exc:  # noqa: BLE001 — ne pas bloquer l'ingestion
            logger.warning("Échec sauvegarde brute de '%s' : %s", source_str, exc)

        logger.info("Ingestion %s → %d chunks dans '%s'", source_str, len(result.chunks), collection)
        return result

    # -- Ingestion en batch (dossier) --

    @staticmethod
    def _file_sha256(filepath: Path) -> str:
        """Calcule le SHA-256 d'un fichier. Retourne '' si inaccessible."""
        try:
            h = hashlib.sha256()
            with open(filepath, "rb") as f:
                while True:
                    block = f.read(65536)  # 64 Ko par bloc
                    if not block:
                        break
                    h.update(block)
            return h.hexdigest()
        except OSError as exc:
            logger.warning("Impossible de hash %s : %s", filepath.name, exc)
            return ""

    async def ingest_directory(
        self, directory: str | Path, *, recursive: bool = True, collection: str | None = None
    ) -> list[ExtractionResult]:
        """Ingest tous les fichiers supportés d'un dossier.

        En mode incrémentiel (par défaut) : chaque fichier est hashé avant
        traitement. Si son SHA-256 correspond à une entrée dans le fichier
        ``data/quarantine/.seen_hashes``, il est ignoré car inchangé.

        Les fichiers échoués sont toujours re-traités (pas de skip par défaut sur erreur).
        Après ingestion réussie, le hash est persisté dans ``.seen_hashes``.

        Returns:
            La liste des résultats d'extraction pour les fichiers traités.
        """
        from .quarantine_manager import quarantine_file

        dir_path = Path(directory) if isinstance(directory, str) else directory
        results: list[ExtractionResult] = []

        # Charger l'index des hashes existants
        seen_index = _HashIndex.load()
        old_hashes_by_source = {s: h for h, s in seen_index.items()}

        pattern = "**/*" if recursive else "*"
        files = [f for f in dir_path.glob(pattern) if f.is_file()]

        # 1. Identifier les fichiers inchangés (skip par hash)
        to_skip: set[Path] = set()
        for filepath in files:
            current_hash = self._file_sha256(filepath)
            old_hash = old_hashes_by_source.get(str(filepath))
            if current_hash and current_hash == old_hash:
                logger.debug("Inchangé (hash OK) : %s", filepath.name)
                to_skip.add(filepath)

        # 2. Traiter uniquement les fichiers nouveaux/modifiés
        for filepath in files:
            if filepath in to_skip:
                continue

            try:
                content_type, processor_key = detect_type(filepath)
                if processor_key is None:
                    logger.warning("Type ignoré : %s (%s)", filepath.name, content_type)
                    continue
                result = await self.ingest(str(filepath), collection=collection)
                results.append(result)

                # Persister le hash après ingestion réussie
                current_hash = self._file_sha256(filepath)
                if current_hash:
                    seen_index[current_hash] = str(filepath)
            except Exception as exc:  # noqa: BLE001
                logger.error("Échec ingestion %s : %s", filepath.name, exc)
                quarantine_file(filepath, str(exc))

        # Sauvegarder l'index mis à jour
        _HashIndex.save(seen_index)

        skipped_count = len(to_skip)
        if skipped_count > 0:
            logger.info("Ingestion dossier : %d/%d fichiers ignorés (inchangés)",
                        skipped_count, len(files))

        return results


def run_engine() -> None:
    """Point d'entrée pour l'engine (utilisé par cli.py)."""
    config = load_config()
    engine = IngestionEngine(config)
    logger.info("Zomboid Knowledge Engine — Multi-Modal Ingestor v%s", __import__("ingestor").__version__)
    logger.info("Config : chunks=%d+%d, web_limit=%d req/min, ocr=%s",
                config.CHUNK_SIZE, config.CHUNK_OVERLAP, config.WEB_RATE_LIMIT, config.OCR_LANG)
