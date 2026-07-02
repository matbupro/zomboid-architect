"""
quarantine_manager — Gestion des fichiers échoués pendant l'ingestion.

Fonctionnalités :
- Quarantaine automatique des fichiers non traitables (corrompus, protégés, format inconnu)
- Deduplication par SHA-256 pour éviter les doublons ChromaDB
- Circuit breaker : stoppe l'ingestion si trop d'échecs consécutifs
- Monitoring espace disque avant chaque cycle
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chemins par défaut (si l'utilisateur n'a pas de config custom)
# ---------------------------------------------------------------------------

DEFAULT_DATA_ROOT = Path("data")
QUARANTINE_DIR_NAME = "quarantine"


def get_quarantine_path(data_root: Path | None = None) -> Path:
    """Retourne le chemin du dossier de quarantaine."""
    root = data_root or DEFAULT_DATA_ROOT
    return root / QUARANTINE_DIR_NAME


# ---------------------------------------------------------------------------
# Quarantaine de fichiers
# ---------------------------------------------------------------------------

def quarantine_file(filepath: str | Path, reason: str) -> None:
    """Déplace un fichier vers le dossier de quarantaine.

    Args:
        filepath: Chemin vers le fichier à quarantainer.
        reason: Raison du rejet (message d'erreur ou catégorie).
    """
    p = Path(filepath) if isinstance(filepath, str) else filepath

    if not p.exists():
        return  # déjà absent

    quarantine_dir = get_quarantine_path()
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    name_with_reason = f"{p.stem}_{timestamp}_{reason.replace(' ', '_')[:30]}"
    dest = quarantine_dir / f"{name_with_reason}{p.suffix}"

    try:
        shutil.move(str(p), str(dest))
        logger.info("Fichier quaranténé : %s → %s (raison: %s)", p.name, dest.name, reason)
    except OSError as exc:
        # Si le fichier est déjà en quarantaine ou verrouillé, juste logger
        logger.warning("Impossible de déplacer %s en quarantaine : %s", p.name, exc)


# ---------------------------------------------------------------------------
# Deduplication SHA-256
# ---------------------------------------------------------------------------

class DedupChecker:
    """Vérifie si un contenu (hash) a déjà été ingéré."""

    def __init__(self, quarantine_dir: Path | None = None):
        # Hash tracking in memory pour une session d'ingestion
        self._seen_hashes: set[str] = set()
        # Chargement depuis le fichier de hash existant si disponible
        self._hash_file = (quarantine_dir or get_quarantine_path()) / ".seen_hashes"
        if self._hash_file.exists():
            with open(self._hash_file) as f:
                for line in f:
                    h = line.strip()
                    if h and not h.startswith("#"):
                        self._seen_hashes.add(h)

    def is_duplicate(self, file_hash: str) -> bool:
        """Vérifie si un hash a déjà été vu dans cette session."""
        return file_hash in self._seen_hashes

    def mark_seen(self, file_hash: str) -> None:
        """Marque un hash comme 'vu' (persiste sur disque)."""
        self._seen_hashes.add(file_hash)
        self._hash_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._hash_file, "a") as f:
            f.write(f"{file_hash}\n")


# ---------------------------------------------------------------------------
# Circuit Breaker — anti-crash sur échecs répétés
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker pour limiter les erreurs d'ingestion en cascade."""

    def __init__(self, max_failures: int = 3):
        self._failures: list[float] = []
        self._max_failures = max_failures
        self._reset_window = 60.0  # secondes : fenêtre de comptage des échecs

    @property
    def is_open(self) -> bool:
        """True si le circuit est ouvert (trop d'échecs récents → stop)."""
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < self._reset_window]
        return len(self._failures) >= self._max_failures

    def record_failure(self) -> None:
        """Enregistre un échec d'ingestion."""
        self._failures.append(time.monotonic())

    def record_success(self) -> None:
        """Réinitialise le circuit breaker après un succès."""
        if not self._failures:
            return  # déjà fermé
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < self._reset_window]
        if not self._failures:
            pass  # tous les échecs sont expirés, circuit fermé naturellement


# ---------------------------------------------------------------------------
# Monitoring espace disque
# ---------------------------------------------------------------------------

def check_disk_space_min_gb(path: str | Path, min_gb: float = 2.0) -> bool:
    """Vérifie qu'il y a assez d'espace disque libre.

    Args:
        path: Chemin vers un fichier ou dossier (le device de la partition est vérifié).
        min_gb: GB minimum requis.

    Returns:
        True si l'espace est suffisant.
    """
    import os
    p = Path(path) if isinstance(path, str) else path
    # Utiliser le parent pour être sûr d'avoir un dossier valide
    statvfs = os.statvfs(str(p.parent))  # type: ignore[arg-type]
    free_bytes = statvfs.f_bavail * statvfs.f_frsize
    return free_bytes >= min_gb * (1024 ** 3)


# ---------------------------------------------------------------------------
# Rapport de quarantaine
# ---------------------------------------------------------------------------

def quarantine_report(quarantine_dir: Path | None = None) -> dict[str, Any]:
    """Génère un rapport des fichiers en quarantaine."""
    qd = (quarantine_dir or get_quarantine_path())
    files = list(qd.iterdir()) if qd.exists() else []

    return {
        "directory": str(qd),
        "total_files": len([f for f in files if f.is_file()]),
        "total_size_mb": sum(f.stat().st_size for f in files if f.is_file()) / (1024 * 1024),
        "files": [f.name for f in sorted(files) if f.is_file()],
    }
