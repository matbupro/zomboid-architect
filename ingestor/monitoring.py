"""
monitoring — S7 : Monitoring, Observability & Alertes pour le pipeline d'ingestion PZ.

Fournit :
- Dashboard CLI (--ingest-status) avec stats aggregation par cycle/source
- Disk space monitor multi-collection (PG + Qdrant + SQLite)
- Alerts sur collections critiques (pz_items vide = tout le reste non fiable)
- Detection coverage drop (>10% entre deux cycles)

Utilisation :
    from ingestor.monitoring import IngestMonitor, check_critical_collections

    mon = IngestMonitor()
    await mon.dashboard_status()           # affichage terminal
    alerts = await mon.check_critical()    # liste d'alertes critiques
    drops  = await mon.detect_coverage_drop("pz_items")  # coverage drift
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Modeles de resultat S7
# ---------------------------------------------------------------------------

@dataclass
class CollectionHealth:
    """Sante d'une collection vectorielle."""
    name: str
    chunk_count: int
    vector_dim: int
    is_healthy: bool
    last_updated: str | None = None
    storage_backend: str = "unknown"  # postgres / qdrant / sqlite


@dataclass
class IngestionCycleStat:
    """Resume d'un cycle d'ingestion recente."""
    run_id: str
    source_type: str
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: float = 0.0
    chunks_generated: int = 0
    chunks_failed: int = 0
    errors: list[dict] = field(default_factory=list)


@dataclass
class CoverageSnapshot:
    """Snapshop de coverage d'une collection."""
    category: str
    covered: int
    expected: int
    coverage_pct: float
    avg_completeness: float
    last_ingested: str | None = None


@dataclass
class CoverageDropAlert:
    """Alerte : coverage drop entre deux cycles."""
    category: str
    prev_coverage_pct: float
    curr_coverage_pct: float
    drop_pct: float  # absolute drop (prev - curr)
    severity: str = "warning"  # warning / critical


@dataclass
class DiskUsageInfo:
    """Espace disque par destination de stockage."""
    path: str
    used_gb: float
    total_gb: float
    free_gb: float
    usage_pct: float
    backend: str  # pg, qdrant, sqlite, minio


@dataclass
class MonitoringAlert:
    """Alerte generique S7."""
    severity: str       # info / warning / critical
    collection: str     # nom de la collection ou "global"
    message: str
    recommendation: str | None = None


# ---------------------------------------------------------------------------
# Constants — collections critiques (si vide = pipeline broken)
# ---------------------------------------------------------------------------

CRITICAL_COLLECTIONS: list[str] = [
    "pz_items",       # base de toute la knowledge engine
    "pz_recipes",     # recipes sans items ne sont que du texte
    "pz_mechanics",   # skills/perks/weather/injuries
]


# ---------------------------------------------------------------------------
# Monitoring principal — dashboard + health checks
# ---------------------------------------------------------------------------

class IngestMonitor:
    """Monitor du pipeline d'ingestion PZ (S7).

    Combinaise les vues PG existantes (v_ingestion_health, v_coverage_summary)
    avec des checks addtionnels : disk space, critical collections, coverage drift.
    """

    def __init__(self):
        from ingestor.storage.pz_storage import get_pz_storage_ext

        self._ext = get_pz_storage_ext()

    # ------------------------------------------------------------------
    # S7-a : Dashboard --ingest-status (stats agregees par cycle/source)
    # ------------------------------------------------------------------

    async def dashboard_status(self) -> None:
        """Affiche un dashboard terminal complet de l'etat d'ingestion."""
        import sys

        width = 80
        sep = "=" * width

        logger.info("%s", sep)
        logger.info("  INGESTION DASHBOARD — %s", time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("%s", sep)

        # --- 1. Ingestion cycles recentes ---
        logger.info("")
        logger.info("[1] Derniers cycles d'ingestion (7 derniers jours)")
        logger.info("-" * 40)

        cycles = await self._recent_ingestion_cycles(limit=10)
        if not cycles:
            logger.info("  Aucun cycle d'ingestion trouve.")
        else:
            # Table format : status | source | chunks | duration
            header = f"  {'Status':<10} {'Source':<16} {'Chunks':>8} {'Failed':>8} {'Duration':>12}"
            logger.info(header)
            logger.info("  " + "-" * (len(header) - 2))

            for c in cycles:
                dur_str = self._format_duration_ms(c.duration_ms) if c.duration_ms else "N/A"
                status_color = self._status_emoji(c.status)
                logger.info(
                    "  %s %-9s %-16s %8d %8d %12s",
                    status_color, c.status[:7], c.source_type,
                    c.chunks_generated, c.chunks_failed, dur_str,
                )

        # --- 2. Coverage par category ---
        logger.info("")
        logger.info("[2] Coverage par collection PZ")
        logger.info("-" * 40)

        coverage = await self._get_coverage_by_category()
        if not coverage:
            logger.info("  Aucune donnee de coverage.")
        else:
            for cov in coverage:
                bar = self._progress_bar(cov.coverage_pct, width=30)
                status_icon = "OK" if cov.coverage_pct >= 95 else ("WARN" if cov.coverage_pct >= 80 else "FAIL")
                logger.info(
                    "  [%-4s] %-16s %s %.1f%% (%d/%d)",
                    status_icon, cov.category, bar, cov.coverage_pct, cov.covered, cov.expected,
                )

        # --- 3. Collection health ---
        logger.info("")
        logger.info("[3] Sante des collections vectorielles")
        logger.info("-" * 40)

        health_list = await self._get_collection_health()
        if not health_list:
            logger.info("  Aucun donnee de sante de collection.")
        else:
            for h in health_list:
                icon = "OK" if h.is_healthy else "FAIL"
                backend_tag = f"[{h.storage_backend}]"
                logger.info(
                    "  [%-4s] %-20s %8d vectors  %s %s",
                    icon, h.name, h.chunk_count, backend_tag,
                    f"(dim={h.vector_dim})" if h.vector_dim else "",
                )

        # --- 4. Disk usage ---
        logger.info("")
        logger.info("[4] Utilisation disque")
        logger.info("-" * 40)

        disk_infos = await self._disk_usage_multi_backend()
        for di in disk_infos:
            bar = self._progress_bar(di.usage_pct, width=25)
            logger.info(
                "  %-12s %s %.1f%%  %6.1f GB / %6.1f GB  (%5.1f GB libre)",
                di.backend, bar, di.usage_pct, di.used_gb, di.total_gb, di.free_gb,
            )

        # --- 5. Alerts recentes ---
        logger.info("")
        alerts = await self.check_critical()
        if alerts:
            logger.info("[5] Alertes actives (%d)", len(alerts))
            logger.info("-" * 40)
            for a in alerts:
                sev_icon = {"critical": "!!!", "warning": " ! ", "info": " i "}[a.severity]
                logger.info("  [%s] [%-12s] %s — %s", sev_icon, a.severity.upper(), a.collection, a.message)
        else:
            logger.info("[5] Aucune alerte active — tout est sain.")

        logger.info("")
        logger.info("%s", sep)

    async def ingest_status_short(self) -> str:
        """Retourne un resume court de l'etat d'ingestion (pour CI/logs automatises)."""
        cycles = await self._recent_ingestion_cycles(limit=1)
        coverage = await self._get_coverage_by_category()
        alerts = await self.check_critical()

        parts = []

        # Dernier cycle
        if cycles:
            c = cycles[0]
            parts.append(f"last_run={c.status} chunks={c.chunks_generated}")
        else:
            parts.append("last_run=none")

        # Global coverage
        total_cov = 0.0
        count = len(coverage) if coverage else 1
        for cov in (coverage or []):
            total_cov += cov.coverage_pct
        parts.append(f"avg_coverage={total_cov / count:.0f}%")

        # Alerts
        if alerts:
            crit_count = sum(1 for a in alerts if a.severity == "critical")
            parts.append(f"alerts={len(alerts)}(crit={crit_count})")
        else:
            parts.append("alerts=ok")

        return " | ".join(parts)

    # ------------------------------------------------------------------
    # S7-b : Multi-collection disk space monitor
    # ------------------------------------------------------------------

    async def disk_monitor(self) -> list[DiskUsageInfo]:
        """Retourne l'usage disque par destination de stockage."""
        return await self._disk_usage_multi_backend()

    # ------------------------------------------------------------------
    # S7-c : Critical collection alerts
    # ------------------------------------------------------------------

    async def check_critical(
        self,
        critical_collections: list[str] | None = None,
    ) -> list[MonitoringAlert]:
        """Verifie les collections critiques — retourne liste d'alertes."""
        collections = critical_collections or CRITICAL_COLLECTIONS
        alerts: list[MonitoringAlert] = []

        health_list = await self._get_collection_health()
        health_map = {h.name: h for h in (health_list or [])}

        # Check 1 : collection critique totalement vide
        for coll in collections:
            h = health_map.get(coll)
            if h and h.chunk_count == 0:
                alerts.append(MonitoringAlert(
                    severity="critical",
                    collection=coll,
                    message=f"Collection {coll} est totalement vide (0 chunks)",
                    recommendation=f"Relancer l'ingestion pour {coll} en priorite. Pipeline broken sans cette collection.",
                ))

        # Check 2 : coverage < 50% pour une collection critique
        coverage = await self._get_coverage_by_category()
        cov_map = {c.category: c.coverage_pct for c in (coverage or [])}
        for coll in collections:
            pct = cov_map.get(coll, -1)
            if pct >= 0 and pct < 50:
                alerts.append(MonitoringAlert(
                    severity="warning",
                    collection=coll,
                    message=f"Collection {coll} : coverage faible ({pct:.1f}%)",
                    recommendation=f"Ingestion incomplete — verifier les erreurs du dernier run.",
                ))

        # Check 3 : last ingestion > 24h ago (stale data)
        recent_cycles = await self._recent_ingestion_cycles(limit=50)
        if recent_cycles:
            for c in reversed(recent_cycles[-5:]):  # 5 derniers cycles de chaque source
                if c.ended_at:
                    try:
                        from datetime import datetime, timezone
                        ended = datetime.fromisoformat(c.ended_at.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        age_hours = (now - ended).total_seconds() / 3600
                        if age_hours > 48:
                            alerts.append(MonitoringAlert(
                                severity="info",
                                collection=c.source_type,
                                message=f"Derniere ingestion de {c.source_type} il y a {age_hours:.0f}h (stale)",
                                recommendation="Envisager un re-ingestion automatique.",
                            ))
                    except (ValueError, TypeError):
                        pass

        return alerts

    # ------------------------------------------------------------------
    # S7-d : Coverage drop detection
    # ------------------------------------------------------------------

    async def detect_coverage_drop(
        self,
        category: str,
        threshold_pct: float = 10.0,
    ) -> list[CoverageDropAlert]:
        """Detecte une baisse de coverage >threshold entre deux cycles successifs."""
        alerts: list[CoverageDropAlert] = []

        # Query les 2 derniers snapshots par category depuis data_coverage
        await self._ext.init_pg()
        cur = self._ext._cursor()
        try:
            # Derniers 10 records de coverage pour cette category, ordonnes par ingestion_run_id
            cur.execute(
                """SELECT category, is_documented, data_completeness_score, ingestion_run_id
                   FROM data_coverage
                   WHERE category = %s
                   ORDER BY ingestion_run_id DESC NULLS LAST
                   LIMIT 10""",
                (category,),
            )
            rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur detect_coverage_drop (%s) : %s", category, exc)
            return []

        if len(rows) < 2:
            return []  # pas assez de donnees pour comparer

        # grouper par run_id
        runs_map: dict[Any, list] = {}
        for row in rows:
            rid = row["ingestion_run_id"]
            runs_map.setdefault(rid, []).append(row)

        sorted_runs = sorted(runs_map.keys(), key=lambda r: str(r) or "", reverse=True)
        if len(sorted_runs) < 2:
            return []

        prev_run = sorted_runs[0]
        curr_run = sorted_runs[1]

        prev_docs = [r for r in runs_map[prev_run] if r["is_documented"]]
        curr_docs = [r for r in runs_map[curr_run] if r["is_documented"]]

        prev_pct = len(prev_docs) / max(len(runs_map[prev_run]), 1) * 100
        curr_pct = len(curr_docs) / max(len(runs_map[curr_run]), 1) * 100

        drop = prev_pct - curr_pct
        if drop >= threshold_pct:
            severity = "critical" if drop >= 25 else "warning"
            alerts.append(CoverageDropAlert(
                category=category,
                prev_coverage_pct=round(prev_pct, 2),
                curr_coverage_pct=round(curr_pct, 2),
                drop_pct=round(drop, 2),
                severity=severity,
            ))

        return alerts

    async def detect_all_coverage_drops(self, threshold_pct: float = 10.0) -> list[CoverageDropAlert]:
        """Check coverage drop sur TOUS les categories documentees."""
        await self._ext.init_pg()
        cur = self._ext._cursor()
        try:
            cur.execute("SELECT DISTINCT category FROM data_coverage ORDER BY category")
            rows = cur.fetchall()
            categories = [r["category"] for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur detect_all_coverage_drops : %s", exc)
            return []

        all_drops: list[CoverageDropAlert] = []
        for cat in categories:
            drops = await self.detect_coverage_drop(cat, threshold_pct)
            all_drops.extend(drops)

        if all_drops:
            logger.warning("Coverage drops detectes : %d categories affectees", len(all_drops))
        return all_drops


    # ------------------------------------------------------------------
    # Helpers PG / Storage
    # ------------------------------------------------------------------

    async def _recent_ingestion_cycles(self, limit: int = 10) -> list[IngestionCycleStat]:
        """Query les cycles d'ingestion recents via v_ingestion_health."""
        try:
            await self._ext.init_pg()
            cur = self._ext._cursor()
            cur.execute(
                """SELECT id, source_type, status, started_at, ended_at,
                          duration_ms, chunks_generated, chunks_failed, errors
                   FROM ingestion_runs
                   WHERE started_at > NOW() - INTERVAL '7 days'
                   ORDER BY started_at DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()

            return [
                IngestionCycleStat(
                    run_id=str(r["id"]),
                    source_type=r["source_type"],
                    status=r["status"],
                    started_at=str(r["started_at"]) if r.get("started_at") else None,
                    ended_at=str(r["ended_at"]) if r.get("ended_at") else None,
                    duration_ms=float(r["duration_ms"]) if r.get("duration_ms") else 0.0,
                    chunks_generated=int(r["chunks_generated"] or 0),
                    chunks_failed=int(r["chunks_failed"] or 0),
                    errors=r["errors"] if isinstance(r.get("errors"), list) else [],
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur _recent_ingestion_cycles : %s", exc)
            return []

    async def _get_coverage_by_category(self) -> list[CoverageSnapshot]:
        """Query v_coverage_summary + data_coverage pour avoir covered/expected."""
        try:
            await self._ext.init_pg()
            cur = self._ext._cursor()

            # On query directement data_coverage pour les stats fines
            cur.execute(
                """SELECT category,
                          SUM(CASE WHEN is_documented THEN 1 ELSE 0 END) AS covered,
                          COUNT(*) AS expected,
                          ROUND(AVG(data_completeness_score) * 100, 2) AS avg_completeness,
                          MAX(last_ingested_at) AS last_ingested
                   FROM data_coverage
                   GROUP BY category
                   ORDER BY category""",
            )
            rows = cur.fetchall()

            return [
                CoverageSnapshot(
                    category=r["category"],
                    covered=int(r["covered"]),
                    expected=int(r["expected"]),
                    coverage_pct=float(r["covered"]) / max(int(r["expected"]), 1) * 100,
                    avg_completeness=float(r["avg_completeness"]),
                    last_ingested=str(r["last_ingested"]) if r.get("last_ingested") else None,
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur _get_coverage_by_category : %s", exc)
            return []

    async def _get_collection_health(self) -> list[CollectionHealth]:
        """Query collection_health + detection backend."""
        try:
            await self._ext.init_pg()
            cur = self._ext._cursor()
            cur.execute(
                "SELECT * FROM collection_health ORDER BY chunk_count DESC"
            )
            rows = cur.fetchall()

            # Detection du backend courant
            from ingestor.config import load_config
            cfg = load_config()
            backend_type = os.getenv("STORAGE_BACKEND", cfg.STORAGE_BACKEND or "sqlite")

            return [
                CollectionHealth(
                    name=r["collection_name"],
                    chunk_count=int(r["chunk_count"] or 0),
                    vector_dim=int(r["vector_dim"] or 0),
                    is_healthy=bool(r.get("is_healthy", True)),
                    last_updated=str(r["updated_at"]) if r.get("updated_at") else None,
                    storage_backend=backend_type,
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur _get_collection_health : %s", exc)
            return []

    async def _disk_usage_multi_backend(self) -> list[DiskUsageInfo]:
        """Return disk usage par backend de stockage (PG, Qdrant, SQLite, MinIO)."""
        results: list[DiskUsageInfo] = []

        # --- PG data directory ---
        pg_data = os.getenv("PGDATA", "/var/lib/postgresql/data")
        try:
            du = self._disk_usage_path(pg_data)
            if du and du.total_gb > 0:
                results.append(DiskUsageInfo(
                    path=pg_data, used_gb=du[0], total_gb=du[1], free_gb=du[2],
                    usage_pct=du[3], backend="pg",
                ))
        except Exception:
            pass

        # --- SQLite storage ---
        sqlite_path = os.getenv("ZOMBOID_STORAGE_PATH", "data/storage/zomboid.db")
        if os.path.exists(sqlite_path):
            try:
                du = self._disk_usage_path(os.path.dirname(sqlite_path) or ".")
                db_size_gb = os.path.getsize(sqlite_path) / (1024 ** 3)
                if du and du[1] > 0:
                    results.append(DiskUsageInfo(
                        path=sqlite_path, used_gb=db_size_gb, total_gb=du[1], free_gb=du[2],
                        usage_pct=db_size_gb / du[1] * 100, backend="sqlite",
                    ))
            except Exception:
                pass

        # --- Qdrant data dir (via env ou default) ---
        qdrant_data = os.getenv("QDRANT_DATA_PATH", "data/qdrant")
        try:
            du = self._disk_usage_path(qdrant_data)
            if du and du[1] > 0:
                results.append(DiskUsageInfo(
                    path=qdrant_data, used_gb=du[0], total_gb=du[1], free_gb=du[2],
                    usage_pct=du[3], backend="qdrant",
                ))
        except Exception:
            pass

        return results

    @staticmethod
    def _disk_usage_path(path: str) -> tuple[float, float, float, float] | None:
        """Retourne (used_gb, total_gb, free_gb, usage_pct) pour un chemin."""
        try:
            total = _shutil_disk_usage(path).total
            free = _shutil_disk_usage(path).free
            used = total - free
            if total <= 0:
                return None
            return (used / (1024 ** 3), total / (1024 ** 3), free / (1024 ** 3), used / total * 100)
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Helpers UI (terminal formatting)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_duration_ms(ms: float) -> str:
        """Formate une duree en ms → lisible."""
        if ms < 1000:
            return f"{ms:.0f}ms"
        secs = ms / 1000
        if secs < 60:
            return f"{secs:.1f}s"
        mins = secs / 60
        if mins < 60:
            return f"{mins:.1f}m"
        hours = mins / 60
        return f"{hours:.1f}h"

    @staticmethod
    def _progress_bar(pct: float, width: int = 30) -> str:
        """Barre de progression ASCII : [████████░░]"""
        filled = int(width * min(max(pct, 0), 100) / 100)
        return f"[{'█' * filled}{'░' * (width - filled)}]"

    @staticmethod
    def _status_emoji(status: str) -> str:
        """Emoji pour un status d'ingestion."""
        mapping = {
            "done": "  [OK]",
            "success": "  [OK]",
            "partial": "  [WARN]",
            "failed": "  [FAIL]",
            "running": "  [RUNNING]",
        }
        return mapping.get(status.lower(), "  [OK]")


# ---------------------------------------------------------------------------
# Quick checks standalone (pour pre-commit hooks / CI)
# ---------------------------------------------------------------------------

async def check_critical_collections(
    critical: list[str] | None = None,
) -> list[MonitoringAlert]:
    """Check rapide des collections critiques — utilise IngestMonitor."""
    mon = IngestMonitor()
    return await mon.check_critical(critical or CRITICAL_COLLECTIONS)


async def coverage_drop_check(
    threshold_pct: float = 10.0,
) -> list[CoverageDropAlert]:
    """Check rapide de coverage drop sur toutes les categories."""
    mon = IngestMonitor()
    return await mon.detect_all_coverage_drops(threshold_pct)


def disk_usage_summary() -> list[DiskUsageInfo]:
    """Sync disk usage check — retourne summary immediat."""
    # Quick sync version pour hooks CI (no PG needed)
    results: list[DiskUsageInfo] = []

    for name, path in [
        ("pg", os.getenv("PGDATA", "/var/lib/postgresql/data")),
        ("sqlite", os.path.dirname(os.getenv("ZOMBOID_STORAGE_PATH", "data/storage/zomboid.db")) or "."),
        ("qdrant", os.getenv("QDRANT_DATA_PATH", "data/qdrant")),
    ]:
        if os.path.exists(path):
            du = _shutil_disk_usage(path)
            total = du.total / (1024 ** 3) if du.total > 0 else 1
            free = du.free / (1024 ** 3)
            used = total - free
            results.append(DiskUsageInfo(
                path=path, used_gb=used, total_gb=total, free_gb=free,
                usage_pct=(1 - free / max(total, 1)) * 100 if total > 0 else 0,
                backend=name,
            ))

    return results


def ensure_disk_space(min_free_gb: float = 5.0) -> MonitoringAlert | None:
    """Verifie qu'il y a assez d'espace disque libre global. Retourne alerte si pas assez."""
    try:
        root = _shutil_disk_usage("/")
        if root.free / (1024 ** 3) < min_free_gb:
            return MonitoringAlert(
                severity="critical",
                collection="global",
                message=f"Disque presque plein : {root.free / (1024 ** 3):.1f} GB libres (< {min_free_gb} GB minimum)",
                recommendation="Libérer de l'espace avant la prochaine ingestion.",
            )
        return None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Import utilitaire en fin de fichier (evite circular)
# ---------------------------------------------------------------------------

from shutil import disk_usage as _shutil_disk_usage  # aliased pour eviter conflit avec class DiskUsageInfo
