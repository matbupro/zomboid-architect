"""
pz_storage — Extension StorageWriter pour l'infrastructure PZ Agent (PostgreSQL + Qdrant).

Gere les tables additionnelles du pipeline de production :
- ingestion_runs    : suivi de chaque cycle d'ingestion
- data_coverage     : tracking % coverage par category vs total connu
- collection_health : monitoring qualite des collections vectorielles
- data_links        : graph de connaissances croisees (items <-> recipes <-> mobs)

Utilisation :
    from ingestor.storage.pz_storage import PZStorageExt

    ext = PZStorageExt(ollama_url="http://localhost:11434")
    await ext.init_pg()       # se connecter a PostgreSQL
    run_id = await ext.start_ingestion_run("wikidrive", source_url=wiki_url)
    ...
    await ext.complete_ingestion_run(run_id, chunks_generated=12345, chunks_failed=0)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from src.governance.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schémas de résultat pour les requetes PG
# ---------------------------------------------------------------------------

@dataclass
class CoverageRecord:
    """Un enregistrement de coverage pour une entite PZ."""
    category: str
    item_name: str
    is_documented: bool
    data_completeness_score: float  # 0-1
    last_ingested_at: str | None = None
    notes: str | None = None


@dataclass
class DataLink:
    """Lien entre deux entites du graph de connaissances."""
    source_category: str
    source_name: str
    target_category: str
    target_name: str
    link_type: str
    confidence: float = 1.0


@dataclass
class IngestionRunSummary:
    """Resume d'un cycle d'ingestion (pour les rapports)."""
    source_type: str
    status: str
    run_count: int
    avg_duration_ms: float
    total_chunks: int
    total_failures: int


# ---------------------------------------------------------------------------
# Extension PZ — methods additionnelles sur le pipeline de production
# ---------------------------------------------------------------------------

class PZStorageExt:
    """Extension du StorageWriter pour les tables PG du pipeline de production.

    Cette classe ne remplace pas StorageWriter (qui gere le storage vectoriel).
    Elle ajoute des methodes pour :
    - Suivre les cycles d'ingestion (ingestion_runs)
    - Track la coverage par category (data_coverage)
    - Monitorer la sante des collections (collection_health)
    - Gerer les liens croises entre donnees (data_links)
    """

    def __init__(self, ollama_url: str | None = None):
        self.ollama_url = ollama_url or "http://host.docker.internal:11434"
        self._pg_conn: Any = None          # lazy init — set par init_pg()
        self._backend_storage_writer: Any = None  # reference au StorageWriter existant

    # ------------------------------------------------------------------
    # Connexion PostgreSQL (lazy)
    # ------------------------------------------------------------------

    async def init_pg(self) -> None:
        """Se connecte a PostgreSQL (lazy — le premier appel cree la connexion)."""
        if self._pg_conn is not None:
            return

        try:
            import psycopg2.pool
            from psycopg2.extras import RealDictCursor
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5,
                host="localhost", port=5432,
                dbname="pz_agent", user="pz_agent",
                password=self._get_pg_password(),
            )
            self._pg_conn = pool.getconn()
            logger.info("Connexion PostgreSQL etablie.")
        except ImportError:
            logger.warning(
                "psycopg2 non installe. Installation requise pour PostgreSQL : pip install psycopg2-binary"
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Erreur connexion PG : %s", exc)
            raise

    def _get_pg_password(self) -> str:
        """Lit le mot de passe PG depuis l'environnement ou .env.unified."""
        import os
        pw = os.getenv("STORAGE_PG_PASS")
        if pw:
            return pw
        # Fallback sur les valeurs de config existantes
        from ingestor.config import load_config
        cfg = load_config()
        return cfg.STORAGE_PG_PASS or ""

    def _cursor(self):
        """Retourne un cursor PG avec RealDictCursor."""
        if not self._pg_conn:
            raise RuntimeError("Call init_pg() first")
        return self._pg_conn.cursor(cursor_factory=RealDictCursor)

    # ------------------------------------------------------------------
    # Ingestion runs tracking
    # ------------------------------------------------------------------

    async def start_ingestion_run(
        self,
        source_type: str,
        source_url: str | None = None,
        source_file: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Demare un cycle d'ingestion et retourne son run_id.

        Args:
            source_type: wikidrive, wikiweb, workshop, classz, modguide
            source_url: URL de la source (optionnel)
            source_file: Chemin local si fichier
            metadata: Details specifiques a la source

        Returns:
            UUID du run cree en base.
        """
        await self.init_pg()
        cur = self._cursor()
        try:
            cur.execute(
                """INSERT INTO ingestion_runs (source_type, source_url, source_file, status, metadata)
                   VALUES (%s, %s, %s, 'running', %s) RETURNING id""",
                (source_type, source_url, source_file, json.dumps(metadata or {})),
            )
            self._pg_conn.commit()
            run_id = str(cur.fetchone()["id"])
            logger.info("Ingestion run demarre : %s (source=%s)", run_id[:8], source_type)
            return run_id
        except Exception as exc:  # noqa: BLE001
            self._pg_conn.rollback()
            logger.error("Erreur start_ingestion_run : %s", exc)
            raise

    async def complete_ingestion_run(
        self,
        run_id: str,
        *,
        status: str = "done",
        chunks_generated: int = 0,
        chunks_failed: int = 0,
        errors: list[dict] | None = None,
    ) -> None:
        """Complete un cycle d'ingestion avec les resultats.

        Args:
            run_id: ID du run a completer
            status: done / failed / partial
            chunks_generated: nombre de chunks writes avec succes
            chunks_failed: nombre de chunks en erreur
            errors: liste d'objets erreurs detaillees
        """
        await self.init_pg()
        cur = self._cursor()
        try:
            cur.execute(
                """UPDATE ingestion_runs
                   SET status=%s, chunks_generated=%s, chunks_failed=%s,
                       errors=%s, ended_at=NOW()
                   WHERE id=%s""",
                (status, chunks_generated, chunks_failed,
                 json.dumps(errors or []), run_id),
            )
            self._pg_conn.commit()
            logger.info(
                "Ingestion run termine : %s → %s (%d chunks gen, %d errors)",
                run_id[:8], status, chunks_generated, chunks_failed,
            )
        except Exception as exc:  # noqa: BLE001
            self._pg_conn.rollback()
            logger.error("Erreur complete_ingestion_run : %s", exc)
            raise

    async def get_coverage_summary(self) -> list[CoverageRecord]:
        """Retourne le % coverage par category (via v_coverage_summary view)."""
        await self.init_pg()
        cur = self._cursor()
        try:
            cur.execute("SELECT * FROM v_coverage_summary ORDER BY coverage_pct ASC")
            rows = cur.fetchall()
            return [
                CoverageRecord(
                    category=r["category"],
                    item_name=r["category"],  # aggregate — item_name non pertinent ici
                    is_documented=bool(r["documented"]) if r.get("documented") else False,
                    data_completeness_score=float(r["avg_completeness_pct"]) / 100 if r.get("avg_completeness_pct") else 0.0,
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur get_coverage_summary : %s", exc)
            return []

    async def update_data_coverage(
        self,
        category: str,
        item_name: str,
        is_documented: bool = True,
        completeness_score: float = 1.0,
        ingestion_run_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Met a jour le statut de coverage d'une entite PZ."""
        await self.init_pg()
        cur = self._cursor()
        try:
            cur.execute(
                """INSERT INTO data_coverage (category, item_name, is_documented,
                   data_completeness_score, ingestion_run_id, notes)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (category, item_name, is_documented, completeness_score, ingestion_run_id, notes),
            )
            self._pg_conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._pg_conn.rollback()
            logger.warning("Erreur update_data_coverage (%s/%s) : %s", category, item_name, exc)

    async def upsert_collection_health(
        self,
        collection_name: str,
        chunk_count: int = 0,
        vector_dim: int = 0,
        is_healthy: bool = True,
        error_detail: str | None = None,
    ) -> None:
        """Met a jour la sante d'une collection vectorielle."""
        await self.init_pg()
        cur = self._cursor()
        try:
            cur.execute(
                """INSERT INTO collection_health (collection_name, chunk_count, vector_dim, is_healthy)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (collection_name) DO UPDATE SET
                       chunk_count=EXCLUDED.chunk_count, vector_dim=EXCLUDED.vector_dim,
                       is_healthy=EXCLUDED.is_healthy, updated_at=NOW()""",
                (collection_name, chunk_count, vector_dim, is_healthy),
            )
            self._pg_conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._pg_conn.rollback()
            logger.warning("Erreur upsert_collection_health (%s) : %s", collection_name, exc)

    async def add_data_link(
        self,
        source_cat: str,
        source_name: str,
        target_cat: str,
        target_name: str,
        link_type: str,
        confidence: float = 1.0,
    ) -> None:
        """Ajoute un lien croise dans le graph de connaissances."""
        await self.init_pg()
        cur = self._cursor()
        try:
            cur.execute(
                """INSERT INTO data_links (source_category, source_name, target_category,
                   target_name, link_type, confidence)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (source_cat, source_name, target_cat, target_name, link_type, confidence),
            )
            self._pg_conn.commit()
        except Exception as exc:  # noqa: BLE001
            self._pg_conn.rollback()
            logger.warning("Erreur add_data_link (%s→%s) : %s", source_name, target_name, exc)

    async def get_data_links(
        self,
        category: str | None = None,
        name: str | None = None,
        link_type: str | None = None,
    ) -> list[DataLink]:
        """Retrieve les liens croises d'une entite."""
        await self.init_pg()
        cur = self._cursor()
        try:
            conditions = []
            params = []
            if category:
                conditions.append("source_category = %s")
                params.append(category)
            if name:
                conditions.append("(source_name = %s OR target_name = %s)")
                params.extend([name, name])
            if link_type:
                conditions.append("link_type = %s")
                params.append(link_type)

            sql = "SELECT * FROM data_links"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY confidence DESC, source_category, source_name"

            cur.execute(sql, params)
            rows = cur.fetchall()
            return [
                DataLink(
                    source_category=r["source_category"],
                    source_name=r["source_name"],
                    target_category=r["target_category"],
                    target_name=r["target_name"],
                    link_type=r["link_type"],
                    confidence=float(r.get("confidence", 1.0)),
                )
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Erreur get_data_links : %s", exc)
            return []

    async def close(self) -> None:
        """Ferme la connexion PG."""
        if self._pg_conn:
            try:
                self._pg_conn.close()
                self._pg_conn = None
                logger.debug("Connexion PG fermee.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Erreur fermeture PG : %s", exc)


# ---------------------------------------------------------------------------
# Singleton global (pour reutilisation entre sessions d'ingestion)
# ---------------------------------------------------------------------------

_instance: PZStorageExt | None = None


def get_pz_storage_ext(ollama_url: str | None = None) -> PZStorageExt:
    """Retourne l'instance unique de PZStorageExt (singleton)."""
    global _instance
    if _instance is None or ollama_url and _instance.ollama_url != ollama_url:
        _instance = PZStorageExt(ollama_url=ollama_url)
    return _instance


# ---------------------------------------------------------------------------
# Aliases backward-compatibilite
# ---------------------------------------------------------------------------

PZStorageExt = PZStorageExt  # self-alias pour compatibilite globale
