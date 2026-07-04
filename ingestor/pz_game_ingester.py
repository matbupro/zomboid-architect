"""pz_game_ingester — Ingestion complète du dossier de jeu Project Zomboid.

Strategie d'ingestion priorisee :
  1. media/lua/        → pz_lua_scripts      (logique jeu — priorite absolue)
  2. media/ configs    → pz_text               (tile defs, layouts, etc.)
  3. Racine game dir   → pz_configs            (launchers *.bat, *.json, serialize.lua)

Tous les chunks portent metadata avec source relative pour traçabilité.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Default paths (Windows Steam standard)
# ---------------------------------------------------------------------------

DEFAULT_GAME_PATH = Path("f:/Games/Steam/steamapps/common/ProjectZomboid")

# Collections ChromaDB cibles par type de fichier
COLLECTION_MAP: dict[str, str] = {
    ".lua": "pz_lua_scripts",
    ".json": "pz_json_configs",
    ".xml": "pz_xml_configs",
    ".txt": "pz_text",
    ".tiles": "pz_tile_definitions",
    ".pack": "pz_texture_packs",
}

# Extensions ignorees (assets binaires, executables, etc.)
SKIP_EXTENSIONS: frozenset[str] = frozenset({
    # Binaries / executables
    ".exe", ".dll", ".jar", ".bat", ".cmd", ".bin",
    # Images / textures
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg",
    ".psd", ".xcf", ".blend", ".glb",
    # Audio
    ".wav", ".ogg", ".mp3", ".flac", ".m4a",
    # Video / animation
    ".mkv", ".avi", ".mov", ".webm", ".wmv",
    ".fbx", ".animstates",
    # 3D models
    ".x",
    # Sound effect source
    ".sfk",
    # Archives / data non-textuelles
    ".pak", ".lotpack", ".lotheader",
    # Compiled bytecode PZ
    ".lbc",
    # Other game data
    ".bk2",
    # Binary large file
    ".dat",
})


# ---------------------------------------------------------------------------
# Ingestion par priorité
# ---------------------------------------------------------------------------

async def ingest_lua_scripts(game_path: Path | str) -> dict[str, Any]:
    """Ingerer tous les scripts Lua du jeu (priorite 1).

    Extraction + écriture ChromaDB → pz_lua_scripts.
    Retourne un resume d'ingestion : total_files, total_chunks, collection, duration_ms.
    """
    from .engine import IngestionEngine
    from .config import load_config
    # ChromaWriter imported at module level (line ~15)

    game_path = Path(game_path) if isinstance(game_path, str) else game_path
    lua_dir = game_path / "media" / "lua"

    if not lua_dir.exists():
        logger.warning("media/lua/ inexistant : %s", lua_dir)
        return {"total_files": 0, "total_chunks": 0, "collection": "pz_lua_scripts", "duration_ms": 0}

    logger.info("Ingestion scripts Lua depuis : %s", lua_dir)
    config = load_config()
    engine = IngestionEngine(config)
    writer = ChromaWriter(config.CHROMA_HOST, config.OLLAMA_BASE_URL)

    start_time = time.monotonic()
    total_files = 0
    total_chunks = 0
    errors: list[str] = []

    for lua_file in sorted(lua_dir.rglob("*.lua")):
        try:
            result = await engine.ingest(str(lua_file), collection="pz_lua_scripts")
            if result.chunks:
                success = await writer.write_chunks_to_chroma(
                    chunks=result.chunks,
                    source=str(lua_file.relative_to(game_path)),
                    content_type=result.content_type,
                    collection="pz_lua_scripts",
                    metadata={
                        "file_path": str(lua_file.relative_to(game_path)),
                        "extension": lua_file.suffix.lower(),
                        "game_root": str(game_path),
                    },
                )
                if success:
                    total_files += 1
                    total_chunks += len(result.chunks)
                    logger.info("  [%d chunks] %s", len(result.chunks), lua_file.relative_to(game_path))
                else:
                    errors.append(f"{lua_file.name}: write failed")
        except Exception as exc:
            errors.append(f"{lua_file.name}: {exc}")

    duration_ms = (time.monotonic() - start_time) * 1000

    summary = {
        "total_files": total_files,
        "total_chunks": total_chunks,
        "collection": "pz_lua_scripts",
        "duration_ms": round(duration_ms),
        "errors_count": len(errors),
        "errors": errors[:5],  # max 5 erreurs dans le resume
    }

    logger.info("Lua ingestion termine : %s", summary)
    return summary


# Need to import ChromaWriter at module level too
from .storage.chroma_writer import ChromaWriter


async def ingest_configs(game_path: Path | str) -> dict[str, Any]:
    """Ingerer les fichiers de config du jeu (priorite 2).

    Ecriture ChromaDB → pz_xml_configs + pz_text.
    Inclut: .json, .xml, .txt, .tiles non-binaires dans media/ + racine.
    """
    from .engine import IngestionEngine
    from .config import load_config

    game_path = Path(game_path) if isinstance(game_path, str) else game_path
    logger.info("Ingestion configs depuis : %s", game_path)
    config = load_config()
    engine = IngestionEngine(config)
    writer = ChromaWriter(config.CHROMA_HOST, config.OLLAMA_BASE_URL)

    start_time = time.monotonic()
    total_files = 0
    total_chunks = 0
    errors: list[str] = []

    # Collect files by type (no .bat or .exe — only text configs)
    text_extensions = {".json", ".xml", ".txt", ".tiles"}
    for pattern in ["media/**/*.json", "media/**/*.xml", "media/*.txt", "*.json"]:
        for file_path in game_path.glob(pattern):
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lower()
            if ext not in text_extensions:
                continue

            # Skip binary .dat files even though they might have text content
            if file_path.name == "binary.dat":
                logger.debug("Skip binary.dat (%s)", file_path.relative_to(game_path))
                continue

            try:
                result = await engine.ingest(str(file_path), collection="pz_xml_configs" if ext == ".xml" else "pz_text")
                if result.chunks:
                    col = "pz_xml_configs" if ext == ".xml" else "pz_text"
                    success = await writer.write_chunks_to_chroma(
                        chunks=result.chunks,
                        source=str(file_path.relative_to(game_path)),
                        content_type=result.content_type,
                        collection=col,
                        metadata={
                            "file_path": str(file_path.relative_to(game_path)),
                            "extension": ext,
                            "game_root": str(game_path),
                        },
                    )
                    if success:
                        total_files += 1
                        total_chunks += len(result.chunks)
                        logger.info("  [%d chunks] %s (%s)", len(result.chunks), file_path.relative_to(game_path), col)
                    else:
                        errors.append(f"{file_path.name}: write failed")
            except Exception as exc:
                errors.append(f"{file_path.name}: {exc}")

    duration_ms = (time.monotonic() - start_time) * 1000

    return {
        "total_files": total_files,
        "total_chunks": total_chunks,
        "collection": "pz_xml_configs / pz_text",
        "duration_ms": round(duration_ms),
        "errors_count": len(errors),
    }


async def ingest_full_game(game_path: Path | str = None) -> dict[str, Any]:
    """Ingestion complète du jeu (toutes les priorités)."""
    if game_path is None:
        game_path = DEFAULT_GAME_PATH

    if not Path(game_path).exists():
        logger.error("Game path inexistant : %s", game_path)
        return {"error": f"Path not found: {game_path}"}

    summaries = {}

    # Priority 1: Lua scripts (critical — core game logic)
    logger.info("=" * 60)
    logger.info("PRIORITY 1: Lua scripts")
    logger.info("=" * 60)
    summaries["lua"] = await ingest_lua_scripts(game_path)

    # Priority 2: Configs (tile defs, layouts, etc.)
    logger.info("=" * 60)
    logger.info("PRIORITY 2: Text configs")
    logger.info("=" * 60)
    summaries["configs"] = await ingest_configs(game_path)

    # Grand total
    grand_files = sum(s.get("total_files", 0) for s in summaries.values())
    grand_chunks = sum(s.get("total_chunks", 0) for s in summaries.values())
    grand_duration = sum(s.get("duration_ms", 0) for s in summaries.values())

    return {
        "game_path": str(game_path),
        "priorities": summaries,
        "grand_total_files": grand_files,
        "grand_total_chunks": grand_chunks,
        "grand_duration_ms": round(grand_duration / 1000),
        "grand_duration_str": f"{grand_duration // 60000}m{grand_duration % 60000 // 1000}s",
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def run_cli():
    """CLI entry point — usage: python -m ingestor.pz_game_ingester [game_path]"""
    import sys

    game_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GAME_PATH
    summary = await ingest_full_game(game_path)

    print(f"\n{'='*60}")
    print("Project Zomboid Game Ingestion — Summary")
    print(f"{'='*60}")
    for priority, data in summary.get("priorities", {}).items():
        chunks = data.get("total_chunks", 0)
        files = data.get("total_files", 0)
        errors = data.get("errors_count", 0)
        dur = data.get("duration_ms", 0) // 1000
        print(f"  {priority:>12} : {files:>5} files, {chunks:>6} chunks, {dur}s")
        if errors:
            print(f"             ⚠ {errors} errors")
    grand = summary.get("grand_total_chunks", 0)
    dur = summary.get("grand_duration_str", "?")
    print(f"\n{'='*60}")
    print(f"  TOTAL : {summary.get('grand_total_files', '?')} files, {grand} chunks ({dur})")
    print("=" * 60)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_cli())
