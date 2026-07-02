"""src/governance -- Modules de gouvernance partagés.

Ce package est importé à la fois par bot/ et ingestor/.
Il contient les utilitaires transversaux :
  - parser: extraction XML/MD/Lua en ParsedChunk
  - game_version: enum GameVersion + tagging auto
  - logger: logs multi-output (console colorisée, fichier rotatif, JSON audit)
  - lock: FileLock cross-process exclusif
  - worker: WorkerContext avec cleanup garanti @exit
"""

from __future__ import annotations

import importlib
from pathlib import Path

__all__ = [
    "game_version",
    "logger",
    "lock",
    "parser",
    "worker",
]


# ── Version loading (lazy, on first import) ───────────────────────────────────

def _load_version() -> str:
    """Reads VERSION file from project root."""
    try:
        root = Path(__file__).parent.parent.parent  # project root
        ver_file = root / "VERSION"
        if ver_file.exists():
            return ver_file.read_text().strip().split()[0]
    except Exception:
        pass
    return "0.1.0-alpha"


__version__: str = _load_version()


def __getattr__(name: str):
    """Lazy import de sous-modules pour réduire l'overhead au démarrage."""
    if name in __all__:
        return importlib.import_module(f".{name}", __package__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
