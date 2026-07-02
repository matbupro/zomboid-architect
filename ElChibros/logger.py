"""Centralised logging configuration for the ingestor package.

Every module inside ``ingestor/`` uses ``get_logger(__name__)`` so that log
records carry the correct module path, correlation ID, and output format.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

# ─── Constants ───────────────────────────────────────────────────────────────

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "project.log"

_MAX_BYTES = 10 * 1024 * 1024   # 10 MB per file
_BACKUP_COUNT = 5               # rotate 5 historic files

# ─── Logger Factory ───────────────────────────────────────────────────────────


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """Return (or create) a configured ``logging.Logger`` for *name*.

    The logger writes to both:

    - ``logs/project.log`` — machine-readable JSON records (rotated).
    - ``stderr`` — human-readable coloured output (INFO and above).

    A ``correlation_id`` key can be attached to any log record via
    ``extra={"correlation_id": "..."}`` so that log lines can be grouped
    across components in a distributed trace.

    Args:
        name:   ``__name__`` of the calling module (e.g. ``"ingestor.engine"``).
        level:  Override the default logging level (default: ``INFO``).

    Returns:
        A fully-configured ``Logger`` instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured — avoid double handlers

    logger.setLevel(level or logging.INFO)

    # ── JSON file handler (machine-readable, rotated) ──────────────────────
    json_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    json_handler.setLevel(logging.DEBUG)  # capture everything in the file
    json_handler.setFormatter(JsonFormatter())
    logger.addHandler(json_handler)

    # ── Console handler (human-readable) ───────────────────────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ConsoleFormatter())
    logger.addHandler(console_handler)

    return logger


# ─── Formatters ──────────────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """One JSON object per log record, with a consistent schema."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # correlation_id is optional — only present when attached via extra=
        if hasattr(record, "correlation_id") and record.correlation_id:
            payload["correlation_id"] = record.correlation_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


class ConsoleFormatter(logging.Formatter):
    """Human-readable coloured format for stderr."""

    COLOURS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    RESET = "\033[0m"
    LEVEL_WIDTH = 7

    def format(self, record: logging.LogRecord) -> str:
        colour = self.COLOURS.get(record.levelname, "")
        reset  = self.RESET
        level  = record.levelname.ljust(self.LEVEL_WIDTH)
        name   = f"[{record.name}]".ljust(35)
        msg    = record.getMessage()

        corr = ""
        if hasattr(record, "correlation_id") and record.correlation_id:
            corr = f"  [{record.correlation_id}]"

        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        return f"{colour}{timestamp}  {level}  {name}{reset}  {msg}{corr}"
