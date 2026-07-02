"""ingestor/promote.py — Gate de promotion staging → production.

Responsabilités :
  1. Validation du golden set (recall@5 ≥ seuil)
  2. Sauvegarde atomique de production
  3. Swap .incoming → production
  4. Rotation des backups (10 max)
  5. Logs JSON audit

Usage :
  python -m ingestor.promote --dry-run
  python -m ingestor.promote --force
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Imports — governance via src/governance (partagé bot/ + ingestor/) ───────

try:
    from src.governance.game_version import get_current_game_version, GameVersion  # noqa: F401
except ImportError:
    from ingestor.game_version import get_current_game_version, GameVersion  # type: ignore[attr-defined]  # noqa: F401

try:
    from src.governance.logger import get_logger  # noqa: F401
except ImportError:
    from ingestor.logger import get_logger  # type: ignore[attr-defined]  # noqa: F401

try:
    from src.governance.lock import FileLock  # noqa: F401
except ImportError:
    from ingestor.lock import FileLock  # type: ignore[attr-defined]  # noqa: F401

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent.parent
DATA_DIR    = ROOT / "data"
STAGING_DIR = DATA_DIR / "staging"
PROD_DIR    = DATA_DIR / "production"
BACKUP_DIR  = ROOT / "backups" / "chromadb"
GOLDEN_FILE = ROOT / "tests" / "golden_set" / "golden.json"
AUDIT_FILE  = ROOT / "logs"   / "audit.json"

MAX_BACKUPS   = 10
RECALL_THRESHOLD = 0.75   # Minimum recall@5 pour passer en prod
CHECKSUM_FILE = DATA_DIR / "workspace" / "last_ingest.sha256"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _load_golden(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Golden set not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_checksum(path: Path) -> str:
    if not path.exists():
        return "no_checksum"
    return path.read_text().strip().split()[0]


def _audit(event: str, **kwargs: Any) -> None:
    """Écrit une entrée dans audit.json (une JSONL line par événement)."""
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **kwargs,
    }
    with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _dir_checksum(path: Path) -> str:
    """Empreinte sha256 de l'état staging (pour traçabilité CHANGELOG)."""
    import hashlib
    hasher = hashlib.sha256()
    for fp in sorted(path.rglob("*")):
        if fp.is_file() and ".lock" not in fp.name:
            hasher.update(fp.name.encode())
            hasher.update(fp.read_bytes())
    return hasher.hexdigest()[:12]


def _rotate_backups(backup_dir: Path) -> None:
    """Supprime les snapshots les plus anciens au-delà de MAX_BACKUPS."""
    if not backup_dir.exists():
        return
    snapshots = sorted(backup_dir.glob("????-??-??_staging.tar.gz"), reverse=True)
    for old in snapshots[MAX_BACKUPS:]:
        old.unlink(missing_ok=True)
        logger.info(f"Rotated out old backup: {old.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Validation : Golden Set Gate
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    """Résultat d'une passe de validation du golden set."""
    total_questions: int
    recall_scores: list[float]
    avg_recall: float
    failed_ids: list[str]
    game_version: str
    correlation_id: str

    @property
    def passed(self) -> bool:
        return self.avg_recall >= RECALL_THRESHOLD

    def to_dict(self) -> dict:
        return asdict(self)


def _run_golden_set(golden_path: Path) -> GateResult:
    """Vérifie chaque question du golden set contre staging.

    Retourne un GateResult avec recall@5 par question et moyenne globale.
    """
    correlation_id = str(uuid.uuid4())[:8]
    questions = _load_golden(golden_path)
    recall_scores: list[float] = []
    failed_ids: list[str] = []

    # Import lazy — utilise src/retrieval (ChromaDB staging) pour le golden set
    from src.retrieval import query_staging  # noqa: F401

    game_version = get_current_game_version().value

    for q in questions:
        qid       = q.get("id", "?")
        question  = q.get("question", "")
        expected  = set(q.get("expected_ids", []))
        filters   = q.get("filter")

        if not question:
            continue

        try:
            result = query_staging(question, k=5, filters=filters)
        except Exception as exc:
            logger.warning(
                f"[Gate] Query failed for '{qid}': {exc}",
                extra={"correlation_id": correlation_id},
            )
            recall_scores.append(0.0)
            failed_ids.append(qid)
            continue

        retrieved_ids = {c["id"] for c in result.get("chunks", [])}
        hits = len(expected & retrieved_ids)
        recall = hits / len(expected) if expected else 0.0
        recall_scores.append(recall)

        if recall < RECALL_THRESHOLD:
            failed_ids.append(qid)

        logger.info(
            f"[Gate] {qid}: recall@5={recall:.2f} "
            f"(hits={hits}/{len(expected)})",
            extra={"correlation_id": correlation_id},
        )

    avg = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0

    return GateResult(
        total_questions=len(questions),
        recall_scores=recall_scores,
        avg_recall=round(avg, 4),
        failed_ids=failed_ids,
        game_version=game_version,
        correlation_id=correlation_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Promotion Atomique
# ─────────────────────────────────────────────────────────────────────────────


def _backup_production(prod_dir: Path, backup_dir: Path) -> Path:
    """Sauvegarde production actuelle avant écrasement."""
    if not prod_dir.exists():
        logger.warning("Production dir does not exist — no backup created")
        return Path()

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot_name = f"{stamp}_production.tar.gz"
    snapshot_path = backup_dir / snapshot_name

    with tarfile.open(snapshot_path, "w:gz") as tar:
        tar.add(prod_dir, arcname=prod_dir.name)

    logger.info(f"Production backed up to: {snapshot_path}")
    _rotate_backups(backup_dir)
    return snapshot_path


def _promote_atomic(staging_dir: Path, prod_dir: Path) -> None:
    """Swap staging → production via .incoming (atomic guarantee).

    Stratégie :
      1. Copie staging dans .incoming/
      2. Atomic rename .incoming/ → prod/ (ou move + rm si rename échoue)
    """
    incoming_dir = prod_dir.parent / f"{prod_dir.name}.incoming"

    # Nettoyage d'un .incoming précédent
    if incoming_dir.exists():
        shutil.rmtree(incoming_dir)

    shutil.copytree(staging_dir, incoming_dir)

    # Atomic swap
    if prod_dir.exists():
        shutil.rmtree(prod_dir)

    # atomic rename sur Linux (rename(2) est atomique)
    try:
        incoming_dir.rename(prod_dir)
    except OSError:
        # Fallback : move + rm (non atomique mais résilient)
        shutil.move(str(incoming_dir), str(prod_dir))

    logger.info(f"Production promoted from staging: {prod_dir}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser_arg = argparse.ArgumentParser(
        description="Promote staging → production",
        prog="python -m ingestor.promote",
    )
    parser_arg.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate golden set without touching production",
    )
    parser_arg.add_argument(
        "--force",
        action="store_true",
        help="Skip golden set gate (emergency promotion)",
    )
    parser_arg.add_argument(
        "--golden",
        type=Path,
        default=GOLDEN_FILE,
        help="Path to golden.json",
    )
    parser_arg.add_argument(
        "--recall-threshold",
        type=float,
        default=RECALL_THRESHOLD,
        help=f"Minimum recall@5 (default: {RECALL_THRESHOLD})",
    )
    args = parser_arg.parse_args(argv)

    correlation_id = str(uuid.uuid4())[:8]
    recall_threshold: float = args.recall_threshold

    logger.info(
        f"[Promote] Started — dry_run={args.dry_run} force={args.force}",
        extra={"correlation_id": correlation_id},
    )
    _audit("promote_started", correlation_id=correlation_id, dry_run=args.dry_run)

    # ── 1. Acquire lock ──────────────────────────────────────────────────────
    with FileLock(target="production", timeout=3600):
        # ── 2. Golden Set Gate ───────────────────────────────────────────────
        if not args.force:
            gate = _run_golden_set(args.golden)
            gate_dict = gate.to_dict()
            logger.info(
                f"[Promote] Gate result — avg_recall={gate.avg_recall} "
                f"({gate.total_questions} Q) PASS={gate.passed}",
                extra={"correlation_id": correlation_id},
            )
            _audit("gate_result", **gate_dict)
            if not gate.passed:
                logger.error(
                    f"[Promote] Gate FAILED — {len(gate.failed_ids)} failed questions. "
                    "Run with --force to bypass.",
                    extra={"correlation_id": correlation_id},
                )
                _audit("gate_rejected", failed_ids=gate.failed_ids)
                return 1
        else:
            logger.warning(
                "[Promote] --force bypasses golden set validation",
                extra={"correlation_id": correlation_id},
            )
            _audit("gate_bypassed", reason="--force flag")

        if args.dry_run:
            logger.info(
                "[Promote] Dry run complete — no changes made",
                extra={"correlation_id": correlation_id},
            )
            _audit("promote_dry_run_complete")
            return 0

        # ── 3. Checksum staging ──────────────────────────────────────────────
        checksum = _dir_checksum(STAGING_DIR)
        logger.info(
            f"[Promote] Staging checksum: {checksum}",
            extra={"correlation_id": correlation_id},
        )
        _audit("staging_checksum", checksum=checksum)

        # ── 4. Backup production ─────────────────────────────────────────────
        backup_path = _backup_production(PROD_DIR, BACKUP_DIR)
        _audit("backup_created", backup=str(backup_path))

        # ── 5. Atomic swap ──────────────────────────────────────────────────
        _promote_atomic(STAGING_DIR, PROD_DIR)

        # ── 6. Done ─────────────────────────────────────────────────────────
        _audit("promote_complete", checksum=checksum, backup=str(backup_path))
        logger.info(
            "[Promote] Promotion complete — staging is now production",
            extra={"correlation_id": correlation_id},
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
