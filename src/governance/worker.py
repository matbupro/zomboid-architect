"""ingestor/worker.py — Worker context pour tâches asynchrones.

Provides a **context manager** guaranteeing status transitions and cleanup
on exit (including when exceptions occur).

Usage
-----
    from ingestor.worker import create_worker

    async with create_worker(task_id="task-001") as worker:
        worker.mark_running()
        # ... process chunks ...
        worker.mark_done(chunks=42)
    # on exit (even via exception): status auto-set to failed if not already done
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ingestor.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WorkerContext:
    """Contexte attaché à chaque tâche asynchrone du pipeline.

    Attributes:
        task_id:         Identifiant unique de la tâche.
        correlation_id:  ID de corrélation pour tracer le pipeline complet.
        started_at:      Horodatage ISO-8601 UTC du démarrage.
        target:          "staging" | "production".
        status:          "pending" | "running" | "done" | "failed".
        error:           Message d'erreur si status == "failed".
        chunks_processed: Nombre de chunks traités.
    """
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    target: str = "staging"
    status: str = "pending"
    error: Optional[str] = None
    chunks_processed: int = 0
    completed_at: Optional[str] = None

    def mark_running(self) -> None:
        self.status = "running"
        logger.info(
            f"[Worker] Task {self.task_id} started",
            extra={"correlation_id": self.correlation_id},
        )

    def mark_done(self, chunks: int = 0) -> None:
        self.status = "done"
        self.chunks_processed = chunks
        self.completed_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"[Worker] Task {self.task_id} done — {chunks} chunks",
            extra={"correlation_id": self.correlation_id},
        )

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.now(timezone.utc).isoformat()
        logger.error(
            f"[Worker] Task {self.task_id} failed: {error}",
            extra={"correlation_id": self.correlation_id},
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "started_at": self.started_at,
            "target": self.target,
            "status": self.status,
            "error": self.error,
            "chunks_processed": self.chunks_processed,
            "completed_at": self.completed_at,
        }


# ── Context manager factory ───────────────────────────────────────────────────

@contextmanager
def create_worker(
    task_id: str | None = None,
    target: str = "staging",
) -> WorkerContext:
    """Factory returning a context-managed WorkerContext.

    Guarantees:
      - If ``mark_done()`` was called → status remains ``done``.
      - On exception exit (and not already ``done`` or ``failed``) → auto-fail.
      - Logs the final state unconditionally on every exit.

    Example
    -------
    >>> with create_worker(task_id="task-001") as w:
    ...     w.mark_running()
    ...     # process...
    ...     w.mark_done(42)
    """
    worker = WorkerContext(task_id=task_id or str(uuid.uuid4()), target=target)
    try:
        yield worker
    except Exception as exc:
        if worker.status not in ("done", "failed"):
            worker.mark_failed(str(exc))
        raise
    finally:
        logger.info(
            f"[Worker] Task {worker.task_id} exited with status={worker.status}",
            extra={"correlation_id": worker.correlation_id},
        )
