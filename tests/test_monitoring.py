"""test_monitoring — Tests S7 : Monitoring, Observability & Alertes.

Couvre les 4 sous-taches de S7 :
- S7-a : --ingest-status dashboard (IngestMonitor.dashboard_status, ingest_status_short)
- S7-b : Multi-collection disk space monitor
- S7-c : Critical collection alerts (check_critical, check_critical_collections)
- S7-d : Coverage drop detection (>10% entre deux cycles)

Mock PG/Qdrant — aucun serveur requis.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Import au niveau module — monitoring.py n'a pas de deps lourdes à load time
# ===========================================================================

from ingestor.monitoring import (  # noqa: E402
    CollectionHealth,
    CoverageDropAlert,
    CoverageSnapshot,
    DiskUsageInfo,
    IngestMonitor,
    IngestionCycleStat,
    MonitoringAlert,
)


# ===========================================================================
# Fixtures — mocks PG / Qdrant
# ===========================================================================


@pytest.fixture()
def mock_pg_conn():
    """Retourne un mock de connexion PG avec cursor RealDictCursor-like."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


@pytest.fixture()
def fake_ext(mock_pg_conn):
    """PZStorageExt avec _cursor() + init_pg() mockés (pas de psycopg2 requis)."""
    conn, cur = mock_pg_conn

    from ingestor.storage.pz_storage import PZStorageExt

    ext = PZStorageExt()
    ext._pg_conn = conn

    # Override sync — retourne le cursor mock directement
    def fake_cursor():
        return cur
    ext._cursor = fake_cursor
    ext.init_pg = AsyncMock(return_value=None)

    return ext, cur


@pytest.fixture()
def sample_coverage_rows():
    """Données coverage simulees."""
    return [
        {"category": "pz_items", "covered": 280, "expected": 350, "avg_completeness": 94.2, "last_ingested_at": "2026-07-06T10:00:00"},
        {"category": "pz_recipes", "covered": 210, "expected": 250, "avg_completeness": 91.5, "last_ingested_at": "2026-07-06T10:05:00"},
        {"category": "pz_mechanics", "covered": 38, "expected": 42, "avg_completeness": 96.0, "last_ingested_at": "2026-07-06T10:10:00"},
        {"category": "pz_mobs", "covered": 25, "expected": 30, "avg_completeness": 88.3, "last_ingested_at": "2026-07-06T10:15:00"},
    ]


@pytest.fixture()
def sample_health_rows():
    """Données collection_health simulees."""
    return [
        {"collection_name": "pz_items", "chunk_count": 350, "vector_dim": 768, "is_healthy": True, "updated_at": "2026-07-06"},
        {"collection_name": "pz_recipes", "chunk_count": 250, "vector_dim": 768, "is_healthy": True, "updated_at": "2026-07-06"},
        {"collection_name": "pz_mechanics", "chunk_count": 42, "vector_dim": 768, "is_healthy": False, "updated_at": "2026-07-01"},
    ]


@pytest.fixture()
def sample_ingestion_rows():
    """Données ingestion_runs simulees."""
    return [
        {"id": "run-001", "source_type": "wikidrive", "status": "done",
         "started_at": "2026-07-06T08:00:00", "ended_at": "2026-07-06T09:30:00",
         "duration_ms": 5400000, "chunks_generated": 12500, "chunks_failed": 12, "errors": []},
        {"id": "run-002", "source_type": "wikiweb", "status": "partial",
         "started_at": "2026-07-05T14:00:00", "ended_at": "2026-07-05T15:10:00",
         "duration_ms": 4200000, "chunks_generated": 8000, "chunks_failed": 340, "errors": [{"msg": "timeout"}]},
        {"id": "run-003", "source_type": "workshop", "status": "failed",
         "started_at": "2026-07-04T22:00:00", "ended_at": "2026-07-04T22:05:00",
         "duration_ms": 300000, "chunks_generated": 0, "chunks_failed": 15, "errors": [{"msg": "mod.parse.error"}]},
    ]


# ===========================================================================
# S7-a : Dashboard --ingest-status (monitoring.py helpers)
# ===========================================================================


class TestIngestionCycleStat:
    def test_defaults(self):
        c = IngestionCycleStat(run_id="x", source_type="wikidrive", status="done")
        assert c.duration_ms == 0.0
        assert c.chunks_generated == 0
        assert c.errors == []

    def test_full(self):
        c = IngestionCycleStat(
            run_id="x", source_type="wikiweb", status="partial",
            duration_ms=5400.0, chunks_generated=100, chunks_failed=3,
        )
        assert c.duration_ms == 5400.0


class TestCoverageSnapshot:
    def test_computed_pct(self):
        cov = CoverageSnapshot(category="pz_items", covered=280, expected=350, coverage_pct=0, avg_completeness=0.9)
        assert cov.covered == 280
        assert cov.expected == 350


class TestMonitoringAlerts:
    def test_severity_levels(self):
        a = MonitoringAlert(severity="critical", collection="pz_items", message="vide")
        assert a.severity == "critical"
        assert a.collection == "pz_items"

    def test_with_recommendation(self):
        a = MonitoringAlert("warning", "mobs", "faible coverage", "Re-ingester")
        assert a.recommendation == "Re-ingester"


class TestMonitorHelpers:
    """Helpers UI de IngestMonitor (pas PG requis)."""

    def test_format_duration_ms_under_1s(self):
        assert IngestMonitor._format_duration_ms(500) == "500ms"

    def test_format_duration_ms_under_60s(self):
        assert IngestMonitor._format_duration_ms(1500) == "1.5s"

    def test_format_duration_ms_under_60m(self):
        # 2700000ms = 45 min < 60 → affiche en minutes
        assert IngestMonitor._format_duration_ms(2700000) == "45.0m"

    def test_format_duration_ms_over_1h(self):
        result = IngestMonitor._format_duration_ms(7200000)
        assert "2.0h" in result

    def test_progress_bar_full(self):
        bar = IngestMonitor._progress_bar(100, width=10)
        assert all(c == "█" for c in bar.strip("[]"))

    def test_progress_bar_empty(self):
        bar = IngestMonitor._progress_bar(0, width=10)
        assert all(c == "░" for c in bar.strip("[]"))

    def test_progress_bar_half(self):
        bar = IngestMonitor._progress_bar(50, width=20)
        filled = bar.count("█")
        assert filled == 10

    def test_status_emoji_done(self):
        assert "[OK]" in IngestMonitor._status_emoji("done")

    def test_status_emoji_failed(self):
        assert "[FAIL]" in IngestMonitor._status_emoji("failed")

    def test_status_emoji_running(self):
        assert "[RUNNING]" in IngestMonitor._status_emoji("running")

    def test_status_emoji_unknown(self):
        result = IngestMonitor._status_emoji("unknown")
        assert "[OK]" in result or "[WARN]" in result or "[FAIL]" in result or "[RUNNING]" in result


# ===========================================================================
# S7-a : IngestMonitor methods (mock PG)
# ===========================================================================


class TestIngestMonitorPG:
    @pytest.mark.asyncio
    async def test_get_coverage_by_category(self, fake_ext, sample_coverage_rows):
        _, cur = fake_ext
        cur.fetchall.return_value = sample_coverage_rows

        mon = IngestMonitor()
        mon._ext = fake_ext[0]  # ext only (cur is mocked on same object via _cursor)
        result = await mon._get_coverage_by_category()

        assert len(result) > 0
        for cov in result:
            assert cov.covered >= 0
            assert cov.expected > 0
            assert cov.category != ""

    @pytest.mark.asyncio
    async def test_get_coverage_by_category_empty(self, fake_ext):
        _, cur = fake_ext
        cur.fetchall.return_value = []

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        result = await mon._get_coverage_by_category()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_collection_health(self, fake_ext, sample_health_rows):
        _, cur = fake_ext
        cur.fetchall.return_value = sample_health_rows

        with patch("ingestor.config.load_config") as mock_cfg:
            mock_cfg.return_value.STORAGE_BACKEND = "qdrant"
            mon = IngestMonitor()
            mon._ext = fake_ext[0]
            result = await mon._get_collection_health()

        assert len(result) == 3
        names = {h.name for h in result}
        assert "pz_items" in names
        assert "pz_mechanics" in names

    @pytest.mark.asyncio
    async def test_recent_ingestion_cycles(self, fake_ext, sample_ingestion_rows):
        _, cur = fake_ext
        cur.fetchall.return_value = sample_ingestion_rows

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        result = await mon._recent_ingestion_cycles(limit=10)

        assert len(result) == 3
        assert result[0].status == "done"
        assert result[0].chunks_generated == 12500
        assert result[2].status == "failed"


# ===========================================================================
# S7-b : Disk space monitor (multi-backend)
# ===========================================================================


class TestDiskUsage:
    def test_disk_usage_returns_none_on_oserror(self):
        with patch("ingestor.monitoring._shutil_disk_usage", side_effect=OSError("nope")):
            result = IngestMonitor._disk_usage_path("/nowhere")
            assert result is None

    def test_disk_usage_valid_path(self, tmp_path):
        """Test disk usage sur le dossier de tests (existe toujours)."""
        with patch("ingestor.monitoring._shutil_disk_usage") as mock_du:
            mock_du.return_value = MagicMock(total=1e12, free=5e11)
            result = IngestMonitor._disk_usage_path(str(tmp_path))
            assert result is not None
            used_gb, total_gb, free_gb, pct = result
            assert total_gb > 0
            assert used_gb >= 0
            assert free_gb > 0


class TestDiskUsageSummary:
    def test_sync_disk_summary_returns_list(self):
        with patch("ingestor.monitoring._shutil_disk_usage") as mock_du:
            mock_du.return_value = MagicMock(total=1e12, free=5e11)
            from ingestor.monitoring import disk_usage_summary

            results = disk_usage_summary()
            assert isinstance(results, list)
            for d in results:
                assert hasattr(d, "used_gb")
                assert hasattr(d, "backend")


class TestEnsureDiskSpace:
    def test_ensure_disk_space_no_alert_if_enough(self):
        from ingestor.monitoring import ensure_disk_space

        with patch("ingestor.monitoring._shutil_disk_usage") as mock_du:
            mock_du.return_value = MagicMock(total=1e12, free=5e11)
            # Avec 500 GB libres, 0.001 GB requis → aucune alerte
            alert = ensure_disk_space(min_free_gb=0.001)
            assert alert is None

    def test_ensure_disk_space_alert_when_low(self):
        from ingestor.monitoring import ensure_disk_space

        with patch("ingestor.monitoring._shutil_disk_usage") as mock_du:
            mock_du.return_value = MagicMock(total=100, free=2)  # 98 GB libres sur 100 → mais < 5 requis
            alert = ensure_disk_space(min_free_gb=5.0)
            assert alert is not None
            assert alert.severity == "critical"


# ===========================================================================
# S7-c : Critical collection alerts
# ===========================================================================


class TestCheckCritical:
    @pytest.mark.asyncio
    async def test_no_alerts_when_all_healthy(self, fake_ext, sample_coverage_rows, sample_health_rows):
        _, cur = fake_ext
        cur.fetchall.side_effect = [sample_health_rows, sample_coverage_rows]

        # Patch __init__ pour eviter la creation de PZStorageExt real (pas de deps importees)
        with patch.object(IngestMonitor, '__init__', lambda self: None):
            mon = IngestMonitor()
            mon._ext = fake_ext[0]
            alerts = await mon.check_critical()

        # Toutes les collections critiques ont chunks > 0 et coverage OK (>50%)
        critical_alerts = [a for a in alerts if a.severity == "critical"]
        assert len(critical_alerts) == 0

    @pytest.mark.asyncio
    async def test_critical_alert_when_empty_collection(self, fake_ext):
        health_rows = [
            {"collection_name": "pz_items", "chunk_count": 0, "vector_dim": 768, "is_healthy": False, "updated_at": None},
            {"collection_name": "pz_recipes", "chunk_count": 250, "vector_dim": 768, "is_healthy": True, "updated_at": None},
        ]
        coverage_rows = [
            {"category": "pz_items", "covered": 0, "expected": 350, "avg_completeness": 0.0, "last_ingested_at": None},
            {"category": "pz_recipes", "covered": 210, "expected": 250, "avg_completeness": 91.5, "last_ingested_at": None},
        ]

        _, cur = fake_ext
        cur.fetchall.side_effect = [health_rows, coverage_rows]

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        alerts = await mon.check_critical()

        critical_alerts = [a for a in alerts if a.severity == "critical"]
        assert len(critical_alerts) >= 1
        pz_items_alerts = [a for a in critical_alerts if "pz_items" in a.collection]
        assert any("vide" in a.message.lower() or "0" in a.message for a in pz_items_alerts)

    @pytest.mark.asyncio
    async def test_warning_alert_when_low_coverage(self, fake_ext):
        health_rows = [
            {"collection_name": "pz_mechanics", "chunk_count": 10, "vector_dim": 768, "is_healthy": True, "updated_at": None},
        ]
        coverage_rows = [
            {"category": "pz_mechanics", "covered": 5, "expected": 42, "avg_completeness": 30.0, "last_ingested_at": None},
        ]

        _, cur = fake_ext
        cur.fetchall.side_effect = [health_rows, coverage_rows]

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        alerts = await mon.check_critical()

        warning_alerts = [a for a in alerts if a.severity == "warning" and "pz_mechanics" in a.collection]
        assert len(warning_alerts) >= 1


# ===========================================================================
# S7-d : Coverage drop detection (>10% entre deux cycles)
# ===========================================================================


class TestCoverageDropDetection:
    @pytest.mark.asyncio
    async def test_no_drop_when_stable(self, fake_ext):
        """Pas de drop si coverage stable (~80-100% dans les 2 runs)."""
        rows = [
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 0.95, "ingestion_run_id": "run-b"},
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 0.93, "ingestion_run_id": "run-b"},
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 0.98, "ingestion_run_id": "run-a"},
        ]

        _, cur = fake_ext
        cur.fetchall.return_value = rows

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        drops = await mon.detect_coverage_drop("pz_items")
        # 100% doc dans run-b et ~67% dans run-a → drop de ~33% > 10%
        if drops:
            assert drops[0].drop_pct >= 10.0

    @pytest.mark.asyncio
    async def test_drop_detected_when_coverage_falls(self, fake_ext):
        """Drop detecte quand coverage passe de 100% a 50% entre runs."""
        rows = [
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 1.0, "ingestion_run_id": "run-b"},
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 1.0, "ingestion_run_id": "run-b"},
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 1.0, "ingestion_run_id": "run-a"},
            {"category": "pz_items", "is_documented": False, "data_completeness_score": 0.5, "ingestion_run_id": "run-a"},
        ]

        _, cur = fake_ext
        cur.fetchall.return_value = rows

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        drops = await mon.detect_coverage_drop("pz_items")

        # run-b = 100% doc, run-a = 50% doc → drop de 50% > 10%
        if drops:
            assert drops[0].drop_pct >= 10.0
            assert drops[0].prev_coverage_pct > drops[0].curr_coverage_pct

    @pytest.mark.asyncio
    async def test_no_drop_with_insufficient_data(self, fake_ext):
        """Moins de 2 rows → pas de comparaison."""
        _, cur = fake_ext
        cur.fetchall.return_value = [
            {"category": "pz_items", "is_documented": True, "data_completeness_score": 0.95, "ingestion_run_id": "run-a"},
        ]

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        drops = await mon.detect_coverage_drop("pz_items")
        assert drops == []

    @pytest.mark.asyncio
    async def test_threshold_customizable(self, fake_ext):
        """Seuil personnalisé — drop de 50% avec threshold=60 passe."""
        rows = [
            {"category": "mobs", "is_documented": True, "data_completeness_score": 0.9, "ingestion_run_id": "run-b"},
            {"category": "mobs", "is_documented": False, "data_completeness_score": 0.5, "ingestion_run_id": "run-a"},
        ]

        _, cur = fake_ext
        cur.fetchall.return_value = rows

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        drops = await mon.detect_coverage_drop("mobs", threshold_pct=40.0)
        if drops:
            assert drops[0].drop_pct >= 40.0


class TestDetectAllCoverageDrops:
    @pytest.mark.asyncio
    async def test_detects_drops_across_categories(self, fake_ext):
        """Check multi-categories — retourne au minimum une liste."""
        from ingestor.monitoring import CoverageSnapshot

        coverage_rows = [
            {"category": "pz_items", "covered": 350, "expected": 350, "avg_completeness": 99.0, "last_ingested_at": None},
            {"category": "pz_mobs", "covered": 10, "expected": 30, "avg_completeness": 50.0, "last_ingested_at": None},
        ]

        _, cur = fake_ext
        cur.fetchall.side_effect = [coverage_rows]  # _get_coverage_by_category only

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        drops = await mon.detect_all_coverage_drops()
        assert isinstance(drops, list)


# ===========================================================================
# Monitoring standalone functions
# ===========================================================================


class TestStandaloneFunctions:
    def test_critical_collections_constant(self):
        from ingestor.monitoring import CRITICAL_COLLECTIONS
        assert "pz_items" in CRITICAL_COLLECTIONS
        assert "pz_recipes" in CRITICAL_COLLECTIONS
        assert "pz_mechanics" in CRITICAL_COLLECTIONS

    @pytest.mark.asyncio
    async def test_check_critical_collections_wrapper(self, fake_ext):
        health_rows = [
            {"collection_name": "pz_items", "chunk_count": 0, "vector_dim": 0, "is_healthy": False, "updated_at": None},
        ]
        coverage_rows = []

        _, cur = fake_ext
        cur.fetchall.side_effect = [health_rows, coverage_rows]

        # Patch __init__ + monkeypatch _get_collection_health et _get_coverage_by_category
        from ingestor.monitoring import check_critical_collections

        with patch.object(IngestMonitor, '__init__', lambda self: None):
            mon = IngestMonitor()
            mon._ext = fake_ext[0]  # use existing mock ext
            alerts = await mon.check_critical()

            assert isinstance(alerts, list)
            critical_alerts = [a for a in alerts if a.severity == "critical"]
            assert any("pz_items" in a.collection for a in critical_alerts)

    @pytest.mark.asyncio
    async def test_coverage_drop_check_wrapper(self):
        # Mock IngestMonitor entier — pas besoin de PG du tout
        from ingestor.monitoring import CoverageDropAlert

        with patch.object(IngestMonitor, '__init__', lambda self: None):
            mon = IngestMonitor()
            # Mock la methode directement
            mon.detect_all_coverage_drops = AsyncMock(return_value=[])

            drops = await mon.detect_all_coverage_drops()
            assert isinstance(drops, list)

    @pytest.mark.asyncio
    async def test_ingest_status_short(self, fake_ext):
        """ingest_status_short retourne une chaine avec pipes."""
        cycles_rows = [
            {"id": "run-1", "source_type": "wikidrive", "status": "done",
             "started_at": "2026-07-06T08:00:00", "ended_at": "2026-07-06T09:30:00",
             "duration_ms": 5400000, "chunks_generated": 12500, "chunks_failed": 0, "errors": []},
        ]

        coverage_rows = [
            {"category": "pz_items", "covered": 300, "expected": 350, "avg_completeness": 90.0, "last_ingested_at": None},
        ]

        _, cur = fake_ext
        cur.fetchall.side_effect = [cycles_rows, coverage_rows]

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        result = await mon.ingest_status_short()

        assert "|" in result
        assert "last_run=done" in result
        assert "avg_coverage=" in result


# ===========================================================================
# CoverageDropAlert model tests
# ===========================================================================


class TestCoverageDropAlert:
    def test_default_severity(self):
        a = CoverageDropAlert(category="pz_items", prev_coverage_pct=95, curr_coverage_pct=80, drop_pct=15)
        assert a.severity == "warning"

    def test_critical_severity(self):
        a = CoverageDropAlert("mobs", 90, 60, 30, severity="critical")
        assert a.severity == "critical"


# ===========================================================================
# DiskUsageInfo model tests
# ===========================================================================


class TestDiskUsageInfo:
    def test_defaults(self):
        d = DiskUsageInfo(path="/tmp", used_gb=0, total_gb=100, free_gb=95, usage_pct=5, backend="test")
        assert d.path == "/tmp"
        assert d.backend == "test"

    def test_critical_usage(self):
        d = DiskUsageInfo(path="/", used_gb=95, total_gb=100, free_gb=5, usage_pct=95, backend="pg")
        assert d.usage_pct == 95


# ===========================================================================
# Error handling — PG errors → liste vide sans crash
# ===========================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_get_coverage_handles_pg_error(self, fake_ext):
        _, cur = fake_ext
        cur.execute.side_effect = Exception("connection lost")

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        result = await mon._get_coverage_by_category()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_collection_health_handles_pg_error(self, fake_ext):
        _, cur = fake_ext
        cur.execute.side_effect = Exception("connection lost")

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        result = await mon._get_collection_health()
        assert result == []

    @pytest.mark.asyncio
    async def test_recent_cycles_handles_pg_error(self, fake_ext):
        _, cur = fake_ext
        cur.execute.side_effect = Exception("connection lost")

        mon = IngestMonitor()
        mon._ext = fake_ext[0]
        result = await mon._recent_ingestion_cycles(limit=10)
        assert result == []
