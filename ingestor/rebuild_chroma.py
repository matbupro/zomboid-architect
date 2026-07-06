"""
rebuild_chroma — Reconstruit ChromaDB depuis les données brutes (data/raw/).

Pipeline : data/raw/**/<collection>/<hash>_*.json → extraction JSON → chunks
→ ChromaWriter.write_chunks_to_chroma() → collection cible.

Usage:
    python -m ingestor.rebuild_chroma              # dry-run (liste ce qui sera fait)
    python -m ingestor.rebuild_chroma --apply       # applique réellement
    python -m ingestor.rebuild_chroma --collection pz_text  # reconstruit une seule collection
    python -m ingestor.rebuild_chroma --since 2026-07-01   # seulement les fichiers >= date
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path
from typing import Any


async def _rebuild(apply: bool, collection_filter: str | None, since_date: str | None) -> dict[str, int]:
    """Logique principale de reconstruction."""
    from ingestor.config import load_config
    from ingestor.storage.chroma_writer import ChromaWriter

    config = load_config()
    raw_root = config.DATA_ROOT / "raw"
    writer = ChromaWriter(config.CHROMA_HOST, config.OLLAMA_BASE_URL)

    if not raw_root.exists():
        print(f"[ERR] Dossier brut introuvable: {raw_root}")
        return {"errors": 1}

    # Collecter tous les fichiers JSON bruts
    json_files = list(sorted(raw_root.rglob("*.json")))

    # Filtrage par date si demandé
    if since_date:
        from datetime import datetime, timezone
        cutoff = datetime.fromisoformat(since_date).replace(tzinfo=timezone.utc)
        filtered = []
        for f in json_files:
            # Essayer de lire saved_at depuis le meta
            try:
                with open(f) as fh:
                    payload = _json.load(fh)
                saved_at = payload.get("_meta", {}).get("saved_at", "")
                if saved_at:
                    file_dt = datetime.fromisoformat(saved_at)
                    if file_dt >= cutoff:
                        filtered.append(f)
                else:
                    # Pas de date, on garde par sécurité
                    filtered.append(f)
            except Exception:
                filtered.append(f)  # safe fallback
        json_files = filtered
        total_all = len(list(raw_root.rglob("*.json")))
        print(f"[FILTER] Fichiers apres {since_date} : {len(json_files)} (sur {total_all})")

    if collection_filter:
        json_files = [f for f in json_files if f.parent.name == collection_filter]
        print(f"[COLLECTION] Filtrage sur '{collection_filter} -> {len(json_files)} fichiers")

    stats = {"total": len(json_files), "ok": 0, "skipped": 0, "errors": 0}

    for filepath in json_files:
        try:
            with open(filepath, encoding="utf-8") as fh:
                payload = _json.load(fh)
        except Exception as exc:
            print(f"  [ERR] Lecture {filepath.name} : {exc}")
            stats["errors"] += 1
            continue

        meta = payload.get("_meta", {})
        collection = meta.get("collection", "pz_pdfs")
        source = meta.get("source", filepath.stem)
        content_type = meta.get("content_type", "text/plain")
        chunks_raw = payload.get("chunks", [])
        global_meta = payload.get("metadata", {})

        # Reconstruire les metadata par chunk (fusion avec _meta + chunk_meta)
        collection_meta = {
            "source": source,
            "content_type": content_type,
            "collection": collection,
            "raw_file": str(filepath),
            "ingest_time_from_raw": meta.get("saved_at", ""),
        }

        if apply:
            # Reconstruction des chunks au format attendu par ChromaWriter
            chunks = []
            for i, ch in enumerate(chunks_raw):
                chunk_meta = {**collection_meta}
                chunk_meta.update(ch.get("metadata", {}))
                chunk_meta["chunk_index"] = i

                from ingestor.processors.base import Chunk as EngineChunk
                chunks.append(EngineChunk(
                    text=ch.get("text", ""),
                    index=ch.get("index", i),
                    start_offset=ch.get("start_offset", 0),
                    metadata=chunk_meta,
                ))

            success = await writer.write_chunks_to_chroma(
                chunks=chunks,
                source=source,
                content_type=content_type,
                collection=collection,
                metadata={},  # déjà fusionné dans chaque chunk_meta
            )
            if success:
                stats["ok"] += 1
                print(f"  [OK] {filepath.name} -> {collection} ({len(chunks)} chunks)")
            else:
                stats["errors"] += 1
                print(f"  [ERR] write_chunks_to_chroma({filepath.name}) = False")
        else:
            stats["skipped"] += 1
            print(f"  [DRY-RUN] {filepath.name} -> {collection} ({len(chunks_raw)} chunks)")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruire ChromaDB depuis data/raw/")
    parser.add_argument("--apply", action="store_true", help="Appliquer la reconstruction")
    parser.add_argument("--collection", default=None, help="Reconstruire une seule collection")
    parser.add_argument("--since", default=None, help="Filtrer >= date (YYYY-MM-DD)")
    args = parser.parse_args()

    import asyncio
    stats = asyncio.run(_rebuild(apply=args.apply, collection_filter=args.collection, since_date=args.since))

    print(f"\n{'='*60}")
    print(f"Reconstruction ChromaDB : {stats['total']} fichiers bruts")
    print(f"  OK     : {stats['ok']}")
    print(f"  SKIP   : {stats['skipped']}")
    if stats["errors"]:
        print(f"  ERREUR : {stats['errors']}")


if __name__ == "__main__":
    main()
