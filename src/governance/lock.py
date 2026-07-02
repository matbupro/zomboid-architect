"""File-based exclusive lock for ingestion runs.

``FileLock`` guarantees that only one ingestion process can run at a time,
even across multiple worker processes or cron jobs.  It is used by
``engine.py`` to guard the staging DB during ingestion.

Lock file format
----------------
Each lock file contains two whitespace-separated fields::

    {token} {monotonic_epoch}

The token identifies ownership; the monotonic timestamp enables stale-lock
detection (crash recovery) and periodic heartbeat writes from a background
thread.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
import contextlib

from ingestor.logger import get_logger

logger = get_logger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

LOCK_DIR = Path(__file__).parent.parent / "data" / "workspace"
LOCK_FILE = LOCK_DIR / ".ingest.lock"
LOCK_TIMEOUT = 60 * 60 * 24   # 24 hours — safe default for long jobs
_HEARTBEAT_INTERVAL = 30      # seconds between heartbeat writes
_MAX_AGING = 3600             # 1 hour — consider lock stale if older than this


# ─── FileLock ────────────────────────────────────────────────────────────────


class FileLock(contextlib.ContextDecorator):
    """Exclusive advisory file lock.

    Acquired atomically via ``os.open`` with ``O_EXCL`` (atomic creation).
    Released automatically on ``__exit__`` or ``release()``.

    **Crash recovery** — if the lock file is older than ``max_aging``, it is
    considered stale and will be reclaimed immediately.  A background heartbeat
    thread keeps the timestamp fresh while the lock holder is alive.

    Usage::

        lock = FileLock(target="staging", timeout=300)
        if not lock.acquire():
            raise RuntimeError("Another ingestion is already running")
        try:
            run_ingestion()
        finally:
            lock.release()
    """

    __slots__ = ("_target", "_timeout", "_token", "_acquired", "_lock_path",
                 "_heartbeat_interval", "_max_aging", "_hb_thread")

    def __init__(
        self,
        target: str = "staging",
        timeout: float = LOCK_TIMEOUT,
        lock_dir: Path = LOCK_DIR,
        heartbeat_interval: float = _HEARTBEAT_INTERVAL,
        max_aging: float = _MAX_AGING,
    ) -> None:
        self._target = target
        self._timeout = timeout
        self._lock_path = lock_dir / f".{target}.lock"
        self._token = str(uuid.uuid4())[:8]
        self._acquired = False
        self._heartbeat_interval = heartbeat_interval
        self._max_aging = max_aging
        self._hb_thread: threading.Thread | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    def acquire(self) -> bool:
        """Attempt to acquire the lock.

        Returns:
            True  — lock obtained (possibly reclaimed from a stale holder).
            False — lock held by another process (timeout expired or busy).
        """
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        started_at = time.monotonic()

        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                # Write token + heartbeat timestamp (new format)
                os.write(fd, f"{self._token} {time.monotonic():.6f}".encode("utf-8"))
                os.close(fd)
                self._acquired = True

                # Start background heartbeat thread
                self._hb_thread = threading.Thread(
                    target=self._heartbeat_loop, daemon=True,
                )
                self._hb_thread.start()

                logger.info(
                    "Lock acquired",
                    extra={"correlation_id": self._token},
                )
                return True

            except FileExistsError:
                # ── Stale detection ────────────────────────────────────────
                if self._lock_path.exists():
                    try:
                        content = self._lock_path.read_text().strip()
                        parts = content.split()
                        if len(parts) >= 2:
                            existing_ts = float(parts[1])
                            age = time.monotonic() - existing_ts
                            if age > self._max_aging:
                                logger.info(
                                    f"Lock stale ({age:.0f}s), taking over '{self._target}'",
                                    extra={"correlation_id": self._token},
                                )
                                # Try to remove the stale lock file so we can acquire
                                self._lock_path.unlink(missing_ok=True)
                                continue  # retry acquisition below
                    except (ValueError, OSError):
                        pass  # Malformed file — fall through to normal wait

                if time.monotonic() - started_at >= self._timeout:
                    logger.warning(
                        f"Lock acquisition timed out after {self._timeout}s",
                    )
                    return False
                time.sleep(2)

    def release(self) -> None:
        """Release the lock, verifying we are the owner."""
        if not self._acquired:
            return

        # Stop heartbeat thread
        self._acquired = False
        if self._hb_thread and self._hb_thread.is_alive():
            self._hb_thread.join(timeout=2)
            self._hb_thread = None

        try:
            if self._lock_path.exists():
                content = self._lock_path.read_bytes()
                # Parse new format: "token timestamp"
                parts = content.strip().split()
                if len(parts) >= 1 and parts[0] == self._token.encode("utf-8"):
                    self._lock_path.unlink()
                    logger.info(
                        "Lock released",
                        extra={"correlation_id": self._token},
                    )
                else:
                    # Token mismatch — we don't own this lock
                    logger.warning(
                        "Lock file exists but token mismatch — not releasing",
                    )
        except OSError as exc:
            logger.warning(f"Failed to release lock cleanly: {exc}")

    def is_locked(self) -> bool:
        """Return True if the lock file exists and is not stale."""
        if not self._lock_path.exists():
            return False
        try:
            content = self._lock_path.read_text().strip()
            parts = content.split()
            if len(parts) >= 2:
                age = time.monotonic() - float(parts[1])
                return age <= self._max_aging
            # Fallback for old-format (token-only) files
            return True
        except (ValueError, OSError):
            return True

    # ── Heartbeat ────────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Background loop that refreshes the lock timestamp periodically."""
        while self._acquired:
            time.sleep(self._heartbeat_interval)
            if not self._acquired:
                break
            try:
                with open(self._lock_path, "w") as f:
                    f.write(f"{self._token} {time.monotonic():.6f}")
            except OSError:
                pass  # File may have been removed externally

    # ── Context manager ─────────────────────────────────────────────────────

    def __enter__(self) -> "FileLock":
        if not self.acquire():
            raise RuntimeError(
                f"Cannot acquire lock for '{self._target}' — "
                f"another ingestion may be in progress"
            )
        return self

    def __exit__(self, *args: object) -> None:
        self.release()
