"""File-based exclusive lock for ingestion runs.

``FileLock`` guarantees that only one ingestion process can run at a time,
even across multiple worker processes or cron jobs.  It is used by
``engine.py`` to guard the staging DB during ingestion.
"""

from __future__ import annotations

import os
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


# ─── FileLock ────────────────────────────────────────────────────────────────


class FileLock(contextlib.ContextDecorator):
    """Exclusive advisory file lock.

    Acquired atomically via ``os.open`` with ``O_EXCL`` (atomic creation).
    Released automatically on ``__exit__`` or ``release()``.

    Usage::

        lock = FileLock(target="staging", timeout=300)
        if not lock.acquire():
            raise RuntimeError("Another ingestion is already running")
        try:
            run_ingestion()
        finally:
            lock.release()
    """

    __slots__ = ("_target", "_timeout", "_token", "_acquired")

    def __init__(
        self,
        target: str = "staging",
        timeout: float = LOCK_TIMEOUT,
        lock_dir: Path = LOCK_DIR,
    ) -> None:
        self._target = target
        self._timeout = timeout
        self._lock_path = lock_dir / f".{target}.lock"
        self._token = str(uuid.uuid4())[:8]
        self._acquired = False

    # ── Public API ───────────────────────────────────────────────────────────

    def acquire(self) -> bool:
        """Attempt to acquire the lock.

        Returns:
            True  — lock obtained.
            False — lock held by another process (timeout expired or busy).
        """
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        started_at = time.monotonic()

        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                # Write token so we can verify we own the lock on release
                os.write(fd, self._token.encode("utf-8"))
                os.close(fd)
                self._acquired = True
                logger.info(
                    "Lock acquired",
                    extra={"correlation_id": self._token},
                )
                return True
            except FileExistsError:
                if time.monotonic() - started_at >= self._timeout:
                    logger.warning(
                        f"Lock acquisition timed out after {self._timeout}s"
                    )
                    return False
                time.sleep(2)

    def release(self) -> None:
        """Release the lock, verifying we are the owner."""
        if not self._acquired:
            return
        try:
            if self._lock_path.exists():
                content = self._lock_path.read_bytes()
                if content.strip() == self._token.encode("utf-8"):
                    self._lock_path.unlink()
                    logger.info(
                        "Lock released",
                        extra={"correlation_id": self._token},
                    )
                else:
                    logger.warning(
                        "Lock file exists but token mismatch — not releasing"
                    )
        except OSError as exc:
            logger.warning(f"Failed to release lock cleanly: {exc}")
        finally:
            self._acquired = False

    def is_locked(self) -> bool:
        return self._lock_path.exists()

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
