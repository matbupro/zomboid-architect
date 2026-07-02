"""ingestor/engine.py — Orchestrateur d'ingestion.

Coordonne parser → ChromaDB avec :
  - verrou exclusif (lock.py)
  - validation game_version sur chaque chunk
  - support --incremental (checksum)
  - logs correlation_id
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ChromaDB — seulement si installé, sinon mode dégradé
try:
    import chromadb
    import chromadb.config
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

from ingestor.parser import Parser, ParsedChunk
from ingestor.game_version import get_current_game_version, GameVersion, tag_chunk_with_version
from ingestor.logger import get_logger
from ingestor.lock import FileLock

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

ROOT          = Path(__file__).parent.parent
SOURCES_DIR   = ROOT / "data" / "sources"
STAGING_DIR   = ROOT / "data" / "staging"
PROD_DIR      = ROOT / "data" / "production"
WORKSPACE_DIR = ROOT / "data" / "workspace"

CHECKSUM_FILE = WORKSPACE_DIR / "last_ingest.sha256"


# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB — abstraction lazy
# ─────────────────────────────────────────────────────────────────────────────


class ChromaClient:
    """Wrapper lazy autour du client ChromaDB.

    Permet de fonctionner en mode dégradé (sans ChromaDB installé)
    tant que les tests ne font pas appel à l'écriture.
    """

    def __init__(self, persist_dir: Path) -> None:
        self.persist_dir = persist_dir
        self._client: Optional[Any] = None

    @property
    def client(self) -> Any:
        if not CHROMADB_AVAILABLE:
            raise RuntimeError(
                "ChromaDB is not installed. Install it with: pip install chromadb"
            )
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=chromadb.config.Settings(anonymized_telemetry=False),
            )
        return self._client

    def get_or_create_collection(self, name: str) -> Any:
        return self.client.get_or_create_collection(
            name=name,
            metadata={"description": f"PZ RAG collection: {name}"},
        )

    def reset_collection(self, name: str) -> None:
        self.client.delete_collection(name)

    def collection_count(self, name: str) -> int:
        try:
            return self.client.get_collection(name).count()
        except Exception:
            return 0


def _chunk_to_chromadb(chunk: ParsedChunk) -> dict[str, Any]:
    """Convertit un ParsedChunk en document ChromaDB."""
    doc = {
        "id": chunk.id,
        "document": chunk.content,
        "metadata": {
            "type": chunk.type,
            "version": chunk.version,
            "title": chunk.title,
            "source_file": chunk.source_file,
            "parsed_at": chunk.parsed_at,
            **chunk.metadata,
        },
    }
    # Stamp game_version depuis la constante de runtime
    return tag_chunk_with_version(doc)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de checksum incrémental
# ─────────────────────────────────────────────────────────────────────────────


def _directory_checksum(root: Path) -> str:
    """Calcule un hash sha256 de tous les fichiers sources (hors .git, backup)."""
    hasher = hashlib.sha256()
    for fp in sorted(root.rglob("*")):
        if fp.is_file():
            parts = fp.parts
            if any(p in (".git", "backup", "__pycache__", ".lock") for p in parts):
                continue
            hasher.update(fp.name.encode())
            hasher.update(fp.read_bytes())
    return hasher.hexdigest()


def _load_last_checksum() -> Optional[str]:
    if CHECKSUM_FILE.exists():
        return CHECKSUM_FILE.read_text().strip().split()[0]
    return None


def _save_checksum(checksum: str) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    CHECKSUM_FILE.write_text(f"{checksum}  {datetime.now(timezone.utc).isoformat()}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Implémentation de query_staging (pour promote.py)
# ─────────────────────────────────────────────────────────────────────────────


def query_staging(question: str, k: int = 5, filters: Optional[dict] = None) -> dict:
    """Interroge la collection ChromaDB de staging.

    Cette fonction est la réimplémentation de ``src.retrieval.query_staging``
    pour les besoins du moteur d'ingestion et de promote.py.

    Args:
        question: Requête textuelle du joueur.
        k: Nombre de résultats à retourner.
        filters: Filtres de métadonnées (optionnel), ex: {"type": "item"}.

    Returns:
        dict avec clés : chunks (list), recall_at_k, query_id, duration_ms.
    """
    if not CHROMADB_AVAILABLE:
        logger.warning("[query_staging] ChromaDB not available — returning empty result")
        return {
            "chunks": [],
            "recall_at_k": 0.0,
            "query_id": str(uuid.uuid4()),
            "duration_ms": 0.0,
            "error": "chromadb_not_installed",
        }

    coll_name = "pz_staging"
    start = time.monotonic()
    query_id = str(uuid.uuid4())

    try:
        chroma_client = ChromaClient(STAGING_DIR / "chromadb")
        collection = chroma_client.get_or_create_collection(coll_name)

        where_clause = filters or {}
        results = collection.query(
            query_texts=[question],
            n_results=k,
            where=where_clause if where_clause else None,
        )

        duration_ms = (time.monotonic() - start) * 1000

        raw_chunks = results.get("documents", [[]])[0]
        ids        = results.get("ids", [[]])[0]
        metadatas  = results.get("metadatas", [[]])[0]
        distances  = results.get("distances", [[]])[0]

        chunks = []
        for i, (doc, cid, meta, dist) in enumerate(
            zip(raw_chunks, ids, metadatas, distances)
        ):
            chunks.append({
                "rank": i + 1,
                "id": cid,
                "content": doc,
                "metadata": meta,
                "distance": dist,
            })

        # Rappel approximatif : on ne le calcule correctement que via le golden set
        # Ici on retourne juste la confiance de ChromaDB
        avg_distance = sum(distances) / len(distances) if distances else 1.0
        recall_approx = max(0.0, 1.0 - avg_distance)

        return {
            "chunks": chunks,
            "recall_at_k": recall_approx,
            "query_id": query_id,
            "duration_ms": round(duration_ms, 2),
        }

    except Exception as exc:
        logger.error(f"[query_staging] Query failed: {exc}")
        return {
            "chunks": [],
            "recall_at_k": 0.0,
            "query_id": query_id,
            "duration_ms": 0.0,
            "error": str(exc),
        }


# ─────────────────────────────────────────────────────────────────────────────
# IngestionEngine
# ─────────────────────────────────────────────────────────────────────────────


class IngestionEngine:
    """Orchestrateur principal du pipeline d'ingestion.

    Usage::

        engine = IngestionEngine(target="staging")
        engine.ingest(incremental=True)
    """

    def __init__(
        self,
        target: str = "staging",
        collection_name: str = "pz_staging",
    ) -> None:
        if target not in ("staging", "production"):
            raise ValueError(f"target must be 'staging' or 'production', got '{target}'")
        self.target         = target
        self.collection_name = collection_name
        self.correlation_id  = str(uuid.uuid4())[:8]
        self._parser         = Parser()
        self._stats: dict[str, Any] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def ingest(self, incremental: bool = False) -> dict[str, Any]:
        """Exécute le pipeline complet d'ingestion.

        Args:
            incremental: Si True, compare les checksums avant de ré-ingérer.

        Returns:
            dict de statistiques (chunksWritten, duration_s, errors...).
        """
        start = time.monotonic()
        logger.info(
            f"[IngestionEngine] Starting ingestion → {self.target}",
            extra={"correlation_id": self.correlation_id},
        )

        # ── Verrou exclusif ─────────────────────────────────────────────────
        with FileLock(target=self.target, timeout=3600) as lock:
            # ── Checksum incrémental ────────────────────────────────────────
            if incremental:
                current_sum = _directory_checksum(SOURCES_DIR)
                last_sum    = _load_last_checksum()
                if current_sum == last_sum:
                    logger.info(
                        "Sources unchanged — skipping ingestion",
                        extra={"correlation_id": self.correlation_id},
                    )
                    return {"skipped": True, "checksum": current_sum}
                logger.info(
                    f"Checksum changed, proceeding with ingestion",
                    extra={"correlation_id": self.correlation_id},
                )

            # ── Parse ────────────────────────────────────────────────────────
            chunks = self._load_and_parse()
            if not chunks:
                logger.warning(
                    "No chunks produced — check quarantine/",
                    extra={"correlation_id": self.correlation_id},
                )

            # ── Validate game_version sur chaque chunk ───────────────────────
            invalid = [c for c in chunks if not c.version or c.version not in [gv.value for gv in GameVersion]]
            if invalid:
                logger.error(
                    f"{len(invalid)} chunks missing or invalid game_version",
                    extra={"correlation_id": self.correlation_id},
                )
                # On les corrige automatiquement
                gv = get_current_game_version()
                for c in invalid:
                    c.version = gv.value

            # ── Écriture ChromaDB ────────────────────────────────────────────
            written = self._write_chromadb(chunks)

            # ── Sauvegarde checksum ─────────────────────────────────────────
            if incremental:
                _save_checksum(_directory_checksum(SOURCES_DIR))

            elapsed = time.monotonic() - start
            self._stats = {
                "target": self.target,
                "correlation_id": self.correlation_id,
                "chunks_parsed": len(chunks),
                "chunks_written": written,
                "duration_s": round(elapsed, 2),
                "game_version": get_current_game_version().value,
            }
            logger.info(
                f"[IngestionEngine] Done — {written} chunks written in {elapsed:.1f}s",
                extra={"correlation_id": self.correlation_id},
            )
            return self._stats

    def stats(self) -> dict[str, Any]:
        return self._stats

    # ── Pipeline steps ─────────────────────────────────────────────────────

    def _load_and_parse(self) -> list[ParsedChunk]:
        """Scanne data/sources/ et parse tous les fichiers supportés."""
        if not SOURCES_DIR.exists():
            logger.warning(
                f"Sources directory not found: {SOURCES_DIR}",
                extra={"correlation_id": self.correlation_id},
            )
            return []

        chunks = self._parser.parse_directory(SOURCES_DIR)
        logger.info(
            f"Parsed {len(chunks)} chunks from {SOURCES_DIR}",
            extra={"correlation_id": self.correlation_id},
        )
        return chunks

    def _write_chromadb(self, chunks: list[ParsedChunk]) -> int:
        """Écrit les chunks dans ChromaDB. Retourne le nombre réellement écrits."""
        if not chunks:
            return 0

        if not CHROMADB_AVAILABLE:
            # Mode dégradé : écriture JSON pour vérification ultérieure
            dump_path = WORKSPACE_DIR / f"ingest_dump_{self.correlation_id}.json"
            with open(dump_path, "w", encoding="utf-8") as fh:
                json.dump([c.to_dict() for c in chunks], fh, indent=2, ensure_ascii=False)
            logger.warning(
                f"ChromaDB not installed — chunks dumped to {dump_path}",
                extra={"correlation_id": self.correlation_id},
            )
            return len(chunks)

        db_dir = STAGING_DIR / "chromadb" if self.target == "staging" else PROD_DIR / "chromadb"
        db_dir.mkdir(parents=True, exist_ok=True)

        chroma = ChromaClient(db_dir)
        collection = chroma.get_or_create_collection(self.collection_name)

        # Reset collection si target == staging (full re-ingest)
        # Production utilise upsert si disponible
        if self.target == "staging":
            try:
                chroma.reset_collection(self.collection_name)
                collection = chroma.get_or_create_collection(self.collection_name)
            except Exception:
                pass

        ids, docs, metas = [], [], []
        for chunk in chunks:
            doc = _chunk_to_chromadb(chunk)
            ids.append(doc["id"])
            docs.append(doc["document"])
            metas.append(doc["metadata"])

        collection.add(ids=ids, documents=docs, metadatas=metas)
        logger.info(
            f"Wrote {len(chunks)} chunks to collection '{self.collection_name}'",
            extra={"correlation_id": self.correlation_id},
        )
        return len(chunks)
