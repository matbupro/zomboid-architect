#!/usr/bin/env python3
"""backups/restore.py — List, restore, or rollback production snapshots.

Usage
-----
    python backups/restore.py list
    python backups/restore.py restore <backup_id>
    python backups/restore.py rollback-latest

    make rollback-latest   (via Makefile)

All operations are logged via ingestor.logger so they appear in
stdout (coloured), project.log (rotating), and audit.json (daily JSON).

Backup format note
------------------
Promote.py writes tar.gz archives to BACKUP_DIR.  This module must handle:
  - Directories created by manual ``cp`` or previous restore.py snapshots
  - .tar.gz archives created by promote.py (the primary production path)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.governance._import_compat import get_logger  # noqa: F401

# ── Paths ──────────────────────────────────────────────────────────────────────

_ROOT:        Path = Path(__file__).parent.parent.resolve()
_BACKUP_DIR:  Path = _ROOT / "backups" / "chromadb"
_PROD_PATHS: list[Path] = [          # Where promote.py writes production
    _ROOT / "data" / "production",   # promote.py canonical path
    _ROOT / "db" / "production",     # legacy compat — keep as fallback
]
_LOCK_NAME:   str  = "restore"

# ── Logger ─────────────────────────────────────────────────────────────────────

log = get_logger("ingestor.restore")


def _get_prod_dir() -> Path:
    """Return whichever production directory exists, or the canonical path."""
    for p in _PROD_PATHS:
        if p.exists():
            return p
    log.warning("no existing production dir found — will create on restore", extra={"candidate": str(_PROD_PATHS[0])})
    return _PROD_PATHS[0]


def _human_size(path: Path) -> str:
    """Human-readable size of a directory tree."""
    if not path.exists():
        return "0 B"
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.1f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


def _parse_backup_id(backup_path: Path) -> dict:
    """Extract structured metadata from a backup name (dir or archive)."""
    name = backup_path.name

    # ── Detect directory-based backup ("2025-01-15_staging") ──
    if backup_path.is_dir():
        ts_str  = name.rsplit("_", 1)[0] if "_" in name else name
        date_str = _ts_to_date(ts_str)
        return {
            "id":          ts_str,
            "display_name": name,
            "date":        date_str,
            "size":        _human_size(backup_path),
            "kind":        "dir",
        }

    # ── Detect tar.gz backup ("2025-01-15_staging.tar.gz") ──
    if name.endswith(".tar.gz"):
        ts_str = name.rsplit("_", 1)[0].removesuffix(".tar.gz") if "_" in name else name.removesuffix(".tar.gz")
        date_str = _ts_to_date(ts_str)
        return {
            "id":          ts_str,
            "display_name": name,
            "date":        date_str,
            "size":        f"{backup_path.stat().st_size / 1024 / 1024:.1f} MB",
            "kind":        "tar.gz",
            "file_path":   str(backup_path),
        }

    # ── Fallback: unrecognised name ──
    return {
        "id":          name,
        "display_name": name,
        "date":        "unknown",
        "size":        "0 B",
        "kind":        "unknown",
    }


def _ts_to_date(ts_str: str) -> str:
    """Try to parse a timestamp prefix into a readable date."""
    for fmt in ("%Y-%m-%d", "%Y%m%d-%H%M%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            continue
    return ts_str


# ── Commands ───────────────────────────────────────────────────────────────────

def list_backups() -> list[dict]:
    """Print a table of all available snapshots (dirs + .tar.gz)."""
    if not _BACKUP_DIR.is_dir():
        log.warning("backup directory missing", extra={"backup_dir": str(_BACKUP_DIR)})
        return []

    rows: list[dict] = []

    # Directories
    entries = sorted(
        (p for p in _BACKUP_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    print()
    print(f"  {'ID':<18}  {'DATE':<22}  {'SIZE':<8}  KIND  NAME")
    print(f"  {'-'*16}  {'-'*20}  {'-'*6}  {'-'*4}  {'-'*35}")

    for entry in entries:
        meta = _parse_backup_id(entry)
        rows.append(meta)
        print(
            f"  {meta['id']:<18}  {meta['date']:<22}  {meta['size']:<8}  "
            f"{meta['kind']:<4}  {meta['display_name']}"
        )

    # .tar.gz files
    archives = sorted(
        (p for p in _BACKUP_DIR.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for entry in archives:
        meta = _parse_backup_id(entry)
        rows.append(meta)
        print(
            f"  {meta['id']:<18}  {meta['date']:<22}  {meta['size']:<8}  "
            f"{meta['kind']:<4}  {meta['display_name']}"
        )

    print()
    log.info(f"listed {len(rows)} backups", extra={"count": len(rows)})
    return rows


def restore(backup_id: str) -> bool:
    """
    Restore a specific snapshot to production.

    Handles both directory snapshots and .tar.gz archives (promote.py format).

    Parameters
    ----------
    backup_id : str
        Snapshot timestamp prefix (e.g. "20260115-143022" or "2025-01-15").

    Returns
    -------
    bool
        True if the restore succeeded.
    """
    prod_target = _get_prod_dir()

    # ── 1. Try to find the backup (by prefix match on id) ──
    candidates: list[Path] = []
    for p in sorted(_BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.startswith(backup_id):
            candidates.append(p)

    # Also do a simple substring match as fallback
    if not candidates:
        for p in sorted(_BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if backup_id.lower() in p.name.lower():
                candidates.append(p)

    if not candidates:
        log.error("backup not found", extra={"backup_id": backup_id})
        print(f"  ✗ Backup '{backup_id}' not found.")
        return False

    snapshot = candidates[0]
    log.info("Found candidate backup", extra={"snapshot": str(snapshot)})

    if not prod_target.exists():
        prod_target.mkdir(parents=True, exist_ok=True)

    # ── 2. Snapshot current production before overwriting ──
    pre_backup_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S_pre_restore")
    pre_dest      = _BACKUP_DIR / f"{pre_backup_id}_pre_restore"
    if prod_target.exists():
        shutil.copytree(prod_target, pre_dest, symlinks=True)
        log.info("pre-restore backup created", extra={
            "pre_backup_id": pre_backup_id,
            "pre_backup_dir": str(pre_dest),
        })
        print(f"  💾 Pre-restore snapshot: {pre_dest.name}")

    # ── 3. Restore from directory or tar.gz ──
    if snapshot.suffixes == [".tar", ".gz"]:
        # ── .tar.gz archive ──
        log.info("Restoring from .tar.gz archive", extra={"archive": str(snapshot)})
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            with tarfile.open(snapshot, "r:gz") as tar:
                tar.extractall(path=tmpdir_path)

            # The tar usually has the folder name inside — find it
            top_dirs = [d for d in tmpdir_path.iterdir() if d.is_dir()]
            if len(top_dirs) == 1:
                source = top_dirs[0]
            else:
                source = tmpdir_path

            shutil.rmtree(prod_target, ignore_errors=True)
            shutil.copytree(source, prod_target, symlinks=True)

        print(f"  ✓ Restored archive: {snapshot.name}  →  {str(prod_target)}")
    elif snapshot.is_dir():
        # ── Directory backup ──
        log.info("Restoring from directory snapshot", extra={"source": str(snapshot)})
        shutil.rmtree(prod_target, ignore_errors=True)
        shutil.copytree(snapshot, prod_target, symlinks=True)

        print(f"  ✓ Restored: {snapshot.name}  →  {str(prod_target)}")
    else:
        log.error("unrecognized backup format", extra={"path": str(snapshot)})
        print(f"  ✗ Unrecognized backup format: {snapshot.name}")
        return False

    # ── 4. Audit trail ──
    log.info("restore complete", extra={
        "backup_id":  backup_id,
        "source":     str(snapshot),
        "target":     str(prod_target),
        "size":       _human_size(prod_target),
    })
    return True


def rollback_latest() -> bool:
    """
    Restore the most recent production snapshot.

    Emergency fallback after a failed promotion.
    Searches both directories and .tar.gz archives created by promote.py.
    """
    if not _BACKUP_DIR.is_dir():
        log.error("no backups available for rollback")
        return False

    # Search all entries — dirs AND tar.gz archives with production reference
    prod_backups = sorted(
        (p for p in _BACKUP_DIR.iterdir()
         if ("_production" in p.name or "staging" in p.name) and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not prod_backups:
        log.error("no production backups found")
        print("  ✗ No production backups found.")
        return False

    latest = prod_backups[0]
    meta   = _parse_backup_id(latest)

    log.warning(
        "rollback initiated",
        extra={"target_backup": meta["display_name"], "backup_date": meta["date"]},
    )
    print(f"  ⚡ Rollback to: {meta['display_name']}  ({meta['date']})")

    return restore(meta["id"])


# ── Main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python backups/restore.py",
        description="Production snapshot management (dirs + .tar.gz)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all available backups")

    restore_p = sub.add_parser("restore", help="Restore a specific backup")
    restore_p.add_argument("backup_id", help="Backup ID (e.g. 20260115-143022)")

    sub.add_parser("rollback-latest", help="Restore most recent production snapshot")

    args = parser.parse_args(argv)

    log.info(
        "restore command invoked",
        extra={"command": args.command},
    )

    if args.command == "list":
        list_backups()
        return 0

    if args.command == "restore":
        ok = restore(args.backup_id)
        return 0 if ok else 1

    if args.command == "rollback-latest":
        ok = rollback_latest()
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
