"""
mod_ingester â€” Pipeline haut-niveau pour l'ingestion de mods Workshop.

Orchestre:
  1. Scan du repertoire mods (WorkshopScanner)
  2. Detection type fichier (.pbo, .lua, .txt, etc.)
  3. Extraction (PBOProcessor ou lecture directe)
  4. Chunking + embedding â†’ storage vectoriel (via storage/storage_writer)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import IngestorConfig, load_config
from ..storage.storage_writer import StorageWriter
from .workshop_scanner import WorkshopScanner, WorkshopModInfo
from ..processors.pbo import PBOProcessor

from src.governance.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModIngestionResult:
    """Resulat de l'ingestion d'un ou plusieurs mods."""
    mod_id: int | None = None
    success: bool = False
    chunks_written: int = 0
    collection: str = "pz_mods"
    errors: list[str] = field(default_factory=list)
    metadata_: dict[str, Any] = field(default_factory=dict)


# Collection routing by file type
MOD_COLLECTION_MAP: dict[str, str] = {
    ".lua": "pz_mod_lua_scripts",
    ".bin": "pz_mod_configs",
    ".cfg": "pz_mod_configs",
    ".pbo": "pz_mod_configs",
    ".pbosync": "pz_mod_configs",
}


def discover_mod_collections(config: IngestorConfig) -> dict[str, str]:
    """Retourne le mapping collection storage vectoriel pour les mods.

    Les collections sont automatiquement creees lors du premier write.

    Returns:
        Mapping extension/type â†’ nom de collection storage vectoriel.
    """
    return {
        "lua": "pz_mod_lua_scripts",
        "config": "pz_mod_configs",
        "text": "pz_mods",
        "pbo": "pz_mod_configs",
        "workshop_meta": "pz_workshop_items",
    }


async def ingest_single_mod(
    mod_path: Path | str,
    config: IngestorConfig | None = None,
    collection: str | None = None,
) -> ModIngestionResult:
    """Ingerer un seul mod (repertoire de mod ou fichier .pbo).

    Args:
        mod_path: Chemin vers le dossier du mod ou fichier .pbo.
        config: Configuration de l'ingestion. Defaut: load_config().
        collection: Collection storage vectoriel cible. Defaut: detection automatique.

    Returns:
        ModIngestionResult avec statistiques d'ingestion.
    """
    config = config or load_config()
    mod_path = Path(mod_path)
    writer = StorageWriter(ollama_url=config.OLLAMA_BASE_URL)

    result = ModIngestionResult(mod_id=None if not mod_path.is_dir() else None, success=False)

    try:
        if mod_path.suffix.lower() in (".pbo", ".pbosync"):
            # Single .pbo file â†’ extract and ingest
            processor = PBOProcessor(config)
            extraction = await processor.extract(str(mod_path))
            result.collection = extraction.collection or "pz_mod_configs"
            success = await writer.write_chunks_to_storage(
                chunks=extraction.chunks,
                source=str(mod_path),
                content_type=extraction.content_type,
                collection=result.collection,
                metadata={"mod_source": "pbo_file", "ingest_time_ms": extraction.extraction_time_ms},
            )
            result.chunks_written = len(extraction.chunks)
            result.success = success

        elif mod_path.is_dir():
            # Directory â€” scan all supported files
            result.mod_id = None  # Will be set if workshop scanner finds it
            collection = collection or "pz_mods"
            total_chunks = 0
            errors: list[str] = []

            for file_path in sorted(mod_path.rglob("*")):
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower()

                # .pbo files â†’ extract with PBOProcessor
                if ext in (".pbo", ".pbosync"):
                    try:
                        processor = PBOProcessor(config)
                        extraction = await processor.extract(str(file_path))
                        collection_for_file = extraction.collection or "pz_mod_configs"
                        success = await writer.write_chunks_to_storage(
                            chunks=extraction.chunks,
                            source=str(file_path),
                            content_type="application/x-pbo",
                            collection=collection_for_file,
                            metadata={"mod_source": "workshop_directory"},
                        )
                        total_chunks += len(extraction.chunks)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"PBO extraction failed for {file_path.name}: {exc}")

                # Text/config files â†’ direct ingest
                elif ext in (".lua", ".txt", ".bin", ".cfg", ".json", ".xml", ".toml"):
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="replace")
                        if not text.strip():
                            continue

                        chunk_meta = {
                            "source_file": str(file_path.relative_to(mod_path)),
                            "file_type": ext.lstrip("."),
                            "mod_source": "workshop_directory",
                        }

                        # Use text processor's chunking logic
                        from ..processors.text import TextProcessor, make_chunks as _make_text_chunks

                        text_proc = TextProcessor(config)
                        chunks = _make_text_chunks(text, file_path.name, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
                        for i, chunk in enumerate(chunks):
                            chunk.metadata.update(chunk_meta)
                            chunk.index = i

                        collection_for_file = MOD_COLLECTION_MAP.get(ext, "pz_mods")
                        success = await writer.write_chunks_to_storage(
                            chunks=chunks,
                            source=str(file_path),
                            content_type=f"text/x-pz-{ext.lstrip('.')}",
                            collection=collection_for_file,
                            metadata=chunk_meta,
                        )
                        total_chunks += len(chunks)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Ingest failed for {file_path.name}: {exc}")

            result.chunks_written = total_chunks
            result.success = total_chunks > 0
            result.errors = errors
            result.collection = collection

        else:
            raise FileNotFoundError(f"Mod path inexistant: {mod_path}")

    except Exception as exc:  # noqa: BLE001
        result.errors.append(str(exc))
        logger.error("Ingestion mod echoue %s: %s", mod_path, exc)

    return result


async def ingest_mods_from_directory(
    mods_dir: Path | str,
    config: IngestorConfig | None = None,
    collections: list[str] | None = None,
) -> list[ModIngestionResult]:
    """Scanner et ingÃ©rer tous les mods d'un repertoire (ex: steamapps/workshop/content/1042170).

    Args:
        mods_dir: Repertoire contenant les dossiers de mods.
        config: Configuration de l'ingestion. Defaut: load_config().
        collections: Liste de collections storage vectoriel a utiliser (defaut: detection automatique).

    Returns:
        Liste des resultats d'ingestion par mod.
    """
    if config is None:
        config = load_config()
    mods_dir = Path(mods_dir)

    if not mods_dir.exists():
        logger.error("Repertoire mods inexistant: %s", mods_dir)
        return []

    # Use WorkshopScanner to discover mods
    scanner = WorkshopScanner(mods_dir.parent / "workshop" / "content" / "1042170" if mods_dir.name == "1042170" else mods_dir)

    results: list[ModIngestionResult] = []

    # Scan all subdirectories as individual mods
    for mod_folder in sorted(mods_dir.iterdir()):
        if not mod_folder.is_dir():
            continue
        try:
            mod_id = int(mod_folder.name)
        except ValueError:
            logger.debug("Repertoire non-numeric ignore: %s", mod_folder.name)
            continue

        logger.info("Ingestion du mod workshop #%d...", mod_id)
        result = await ingest_single_mod(mod_folder, config=config)
        result.mod_id = mod_id
        results.append(result)

        status = f"{result.chunks_written} chunks" if result.success else f"ERREUR: {result.errors}"
        logger.info("Mod #%d termine: %s", mod_id, status)

    return results


