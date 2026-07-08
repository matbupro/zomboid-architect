"""generate_report â€" Rapport de qualite pour le Zomboid Knowledge Engine.

Se connecte au storage vectoriel, calcule le recall du golden set, compte les entites
par collection, scan la quarantaine et verifie l'etat des services.

Usage :
    python -m ingestor.generate_report           # affichage terminal couleur
    python -m ingestor.cli --report              # via CLI principale
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from ingestor.config import load_config          # noqa: E402
from src.retrieval import list_collections, query_staging  # noqa: E402
from src.storage import StorageBackend, create_backend  # noqa: E402
from src.governance.logger import get_logger     # noqa: E402

logger = get_logger("ingestor.generate_report")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Golden set helpers â€” reuse de tests/test_golden_set.py
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

GOLDEN_PATH = PROJECT_ROOT / "tests" / "golden_set" / "golden.json"


def _load_golden() -> list[dict[str, Any]]:
    if not GOLDEN_PATH.exists():
        logger.warning("Golden set introuvable : %s", GOLDEN_PATH)
        return []
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Terminal colors â€” ANSI (dÃ©sactivÃ© sur Windows par defaut)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text  # pas de couleurs dans les pipes
    return f"{color}{text}{_RESET}"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Report data model
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class GoldenHit:
    recall: float
    expected: int
    found: int
    hit_at_rank: int | None = None
    missed_ids: list[str] = field(default_factory=list)


@dataclass
class CollectionInfo:
    name: str
    count: int
    avg_metadata_fields: int = 0


@dataclass
class QuarantineSummary:
    total_entries: int = 0
    by_date: dict[str, int] = field(default_factory=dict)
    recent_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ServiceHealth:
    ollama_online: bool = False
    ollama_models: list[str] = field(default_factory=list)
    storage_online: bool = False
    storage_version: str = ""
    disk_free_gb: float = 0.0


@dataclass
class GoldenReport:
    timestamp: str = ""
    collections: list[CollectionInfo] = field(default_factory=list)
    golden_recall: dict[str, GoldenHit] = field(default_factory=dict)
    golden_recall_summary: dict[str, Any] = field(default_factory=dict)
    quarantine: QuarantineSummary = field(default_factory=QuarantineSummary)
    health: ServiceHealth = field(default_factory=ServiceHealth)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "collections": [asdict(c) for c in self.collections],
            "golden_recall": {k: asdict(v) for k, v in self.golden_recall.items()},
            "golden_recall_summary": self.golden_recall_summary,
            "quarantine": asdict(self.quarantine),
            "health": asdict(self.health),
        }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Data collection
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _collect_collections() -> list[CollectionInfo]:
    """Liste les collections du storage et compte les documents."""
    from src.storage import create_backend

    backend = create_backend()
    infos: list[CollectionInfo] = []
    known = (
        "pz_items", "pz_recipes", "pz_mechanics",
        "pz_lua_api", "pz_java_api", "pz_web_pages",
        "pz_pdfs", "pz_images", "pz_videos", "pz_audios",
        "pz_mods", "pz_workshop_items", "pz_mod_lua_scripts", "pz_mod_configs",
    )

    collection_names: set[str] = set()
    try:
        for name in backend.list_collections():
            collection_names.add(name)
            count = backend.count_collection(name)
            infos.append(CollectionInfo(name=name, count=count if count >= 0 else 0))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossible de lister les collections : %s", exc)

    for name in known:
        if name not in collection_names:
            infos.append(CollectionInfo(name=name, count=0))

    return infos


def _compute_golden_recall(
    golden: list[dict],
) -> dict[str, GoldenHit]:
    """Calcule recall@5 par question du golden set via le storage (PostgreSQL/pgvector).

    Utilise query_staging (deleguÃ© au StorageBackend) pour interroger les collections.
    """
    hits: dict[str, GoldenHit] = {}
    col_names = ("pz_items", "pz_mechanics", "pz_recipes")

    for item in golden:
        question = item["question"]
        expected_ids = set(item.get("expected_ids", []))

        # Requete sur chaque collection pertinente
        found_ids: set[str] = set()
        total_chunks = 0

        try:
            for col in col_names:
                results = query_staging(question, k=5)
                chunks = results.get("chunks", [])
                total_chunks += len(chunks)
                for chunk in chunks:
                    chunk_id = chunk.get("id", "")
                    if isinstance(chunk_id, list):
                        chunk_id = chunk_id[0] if chunk_id else ""
                    found_ids.add(str(chunk_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Golden recall query echou pour '%s' : %s", question[:40], exc)

        hit_count = len(expected_ids & found_ids)
        hits[question] = GoldenHit(
            expected_ids=len(expected_ids),
            found_ids=hit_count,
            total_chunks=total_chunks,
            recall=hit_count / len(expected_ids) if expected_ids else 0.0,
        )

    return hits


def _compute_recall_summary(hits: dict[str, GoldenHit]) -> dict[str, Any]:
    """RÃ©sumÃ© du recall sur toutes les questions."""
    valid = [h for h in hits.values() if h.recall >= 0]
    if not valid:
        return {"avg_recall": 0.0, "questions_with_perfect_recall": 0, "total_questions": len(hits)}

    avg = sum(h.recall for h in valid) / len(valid)
    perfect = sum(1 for h in valid if h.recall >= 1.0)
    missed_ids = set()
    for h in valid:
        missed_ids.update(h.missed_ids)

    return {
        "avg_recall": round(avg, 3),
        "questions_with_perfect_recall": perfect,
        "total_questions": len(valid),
        "missed_ids": sorted(missed_ids),
    }


def _collect_quarantine() -> QuarantineSummary:
    """Scan les fichiers de quarantaine dans data/quarantine/."""
    summary = QuarantineSummary()
    qdir = PROJECT_ROOT / "data" / "quarantine"
    if not qdir.exists():
        return summary

    for fpath in sorted(qdir.glob("quarantine_*.jsonl")):
        try:
            stamp = fpath.stem.replace("quarantine_", "")
            count = 0
            with open(fpath, encoding="utf-8") as fh:
                for line_num, line in enumerate(fh):
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    count += 1
                    if line_num < 3:
                        summary.recent_errors.append({
                            "source": fpath.name,
                            "line": line_num + 1,
                            **{k: v for k, v in entry.items() if k != "raw_snippet"},
                        })
            summary.total_entries += count
            summary.by_date[stamp] = count
        except Exception:  # noqa: BLE001
            summary.total_entries += 1
            summary.by_date[fpath.stem[:8]] = -1

    if len(summary.recent_errors) > 5:
        summary.recent_errors = summary.recent_errors[-5:]

    return summary


def _check_services() -> ServiceHealth:
    """VÃ©rifie la disponibilitÃ© des services."""
    health = ServiceHealth()

    # Ollama
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://host.docker.internal:11434/api/tags", timeout=5)
        if resp.status == 200:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            health.ollama_online = True
            health.ollama_models = models[:5]
    except Exception:  # noqa: BLE001
        pass

    # Storage vectoriel (check de compatibilité)
    try:
        from src.storage import create_backend
        backend = create_backend()
        health.storage_online = True
        health.storage_mode = backend.backend_type  # type: ignore[union-attr]
        health.storage_version = f"v{backend.backend_type}"
    except Exception:  # noqa: BLE001
        pass

    # Disk free
    try:
        statvfs = __import__("os").statvfs(str(PROJECT_ROOT))
    except Exception:  # noqa: BLE001
        statvfs = None
    if statvfs:
        health.disk_free_gb = round(statvfs.f_bavail * statvfs.f_frsize / (1024 ** 3), 1)

    return health


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Report formatting
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _format_terminal(report: GoldenReport) -> None:
    """Affiche le rapport dans le terminal colorÃ©."""
    sep = "============================================================"

    print()
    print(sep)
    print("Zomboid Knowledge Engine â€” Rapport de QualitÃ©")
    print(f"GÃ©nÃ©rÃ© : {report.timestamp}")
    print(sep)

    # Collections
    print("\nCollections storage vectoriel")
    for col in sorted(report.collections, key=lambda c: c.name):
        if col.count < 0:
            status = " [ERREUR]"
        elif col.count == 0:
            status = " (vide)"
        else:
            status = ""
        print(f"   {col.name:<25} {col.count:>6d} docs  (avg_meta: {col.avg_metadata_fields}){status}")

    # Golden Recall
    print("\nGolden Set â€” Recall@5")
    for qid, hit in report.golden_recall.items():
        if hit.recall < 0:
            bar = f"[ERREUR]"
        elif hit.recall >= 1.0:
            bar = f"recall={hit.recall:.3f} ({hit.found}/{hit.expected})"
        else:
            bar = (f"recall={hit.recall:.3f} ({hit.found}/{hit.expected}"
                   + (f", hit@{hit.hit_at_rank}" if hit.hit_at_rank else "")
                   + f" â€” manquants: {', '.join(hit.missed_ids)}])")
        print(f"   {qid:<30}  {bar}")

    # Summary
    summary = report.golden_recall_summary
    avg = summary.get("avg_recall", 0)
    stars_ok = "â˜…" * int(avg * 10)
    stars_bad = "Â·" * (10 - int(avg * 10))
    print(f"\n   {stars_ok}{stars_bad} recall moyen: {avg:.3f}")
    print(f"   parfait: {summary.get('questions_with_perfect_recall', 0)}/{summary.get('total_questions', 0)}")
    if summary.get("missed_ids"):
        print(f"   IDs jamais trouvÃ©s : {', '.join(summary['missed_ids'][:10])}")

    # Quarantine
    print("\nQuarantaine")
    if report.quarantine.total_entries:
        for date, count in sorted(report.quarantine.by_date.items()):
            marker = "!" if count > 50 else ("~" if count > 10 else "+")
            print(f"   {date} : {count} erreurs {marker}")
        if report.quarantine.recent_errors:
            for err in report.quarantine.recent_errors[-3:]:
                snippet = err.get("snippet", str(err.get("exc_info", "N/A")))[:80]
                print(f"     {snippet}")
    else:
        print("   Aucune donnÃ©e quarantainÃ©e")

    # Health
    print("\nServices")
    ol = "âœ“ En ligne" if report.health.ollama_online else "âœ˜ Hors ligne"
    ol += f" â€” {', '.join(report.health.ollama_models[:3])}" if report.health.ollama_online else ""
    ch = "âœ“ En ligne" if report.health.storage_online else "âœ˜ Hors ligne"
    ch += f" v{report.health.storage_version}" if report.health.storage_online and report.health.storage_version else ""
    disk_color = "+" if report.health.disk_free_gb > 2 else "~"
    print(f"   Ollama : {ol}")
    print(f"   Storage vectoriel : {ch}")
    print(f"   Disque libre : {report.health.disk_free_gb} GB {disk_color}")

    print(f"\n{sep}\n")


def _format_markdown(report: GoldenReport) -> str:
    """GÃ©nÃ¨re un rapport Markdown."""
    lines = [
        "# Rapport de QualitÃ© â€” Zomboid Knowledge Engine",
        "",
        f"*GÃ©nÃ©rÃ© le {report.timestamp}*",
        "",
        "## Collections Storage Vectoriel",
        "",
        "| Collection | Nom | Docs | Avg Metadata |",
        "|---|---|---|---|",
    ]

    for col in sorted(report.collections, key=lambda c: c.name):
        lines.append(f"| â€¢ | `{col.name}` | {col.count} | {col.avg_metadata_fields} |")

    lines += ["", "## Golden Set â€” Recall@5", ""]

    header = "| Question ID | Recall | TrouvÃ©s/Attendus | Hit @ Rank | IDs manquÃ©s |"
    sep_line = "|---|---|---|---|---|"
    lines.extend([header, sep_line])

    for qid, hit in report.golden_recall.items():
        if hit.recall < 0:
            recall_str = "ERREUR"
            found = "erreur"
        else:
            recall_str = f"{hit.recall:.3f}"
            found = f"{hit.found}/{hit.expected}"

        missed_str = ", ".join(hit.missed_ids) if hit.missed_ids else "-"
        rank_str = f"@{hit.hit_at_rank}" if hit.hit_at_rank else "-"
        lines.append(f"| `{qid}` | {recall_str} | {found} | {rank_str} | {missed_str} |")

    s = report.golden_recall_summary
    lines += [
        "",
        f"**recall moyen** : {s.get('avg_recall', 0):.3f}   **parfait** : {s.get('questions_with_perfect_recall', 0)}/{s.get('total_questions', 0)}",
    ]
    if s.get("missed_ids"):
        lines.append(f"IDs jamais trouvÃ©s : {', '.join(s['missed_ids'])}")

    lines += ["", "## Quarantaine"]
    if report.quarantine.total_entries:
        lines.append(f"**Total** : {report.quarantine.total_entries} erreurs")
        for date, count in sorted(report.quarantine.by_date.items()):
            lines.append(f"- `{date}` : {count}")
        if report.quarantine.recent_errors:
            lines.append("**DerniÃ¨res erreurs :**")
            for err in report.quarantine.recent_errors[-3:]:
                snippet = err.get("snippet", str(err.get("exc_info", "N/A")))[:80]
                lines.append(f"- `{snippet}`")
    else:
        lines.append("*Aucune donnÃ©e quarantainÃ©e*")

    lines += ["", "## Services"]
    ol = f"{'âœ“' if report.health.ollama_online else 'âœ˜'} Ollama"
    if report.health.ollama_online:
        ol += f" â€” {', '.join(report.health.ollama_models[:3])}"
    ch = f"{'âœ“' if report.health.storage_online else 'âœ˜'} Storage vectoriel"
    if report.health.storage_online and report.health.storage_version:
        ch += f" v{report.health.storage_version}"
    lines.extend([ol, ch, f"**Disque libre** : {report.health.disk_free_gb} GB"])

    return "\n".join(lines)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Main entry point
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_report() -> GoldenReport:
    """GÃ©nÃ¨re le rapport complet et retourne l'objet structurÃ©."""
    report = GoldenReport(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M UTC"),
    )

    # Collections
    try:
        config = load_config()
        report.collections = _collect_collections()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Collections non accessibles : %s", exc)

    # Golden Recall
    golden = _load_golden()
    if golden:
        try:
            report.golden_recall = _compute_golden_recall(golden)
            report.golden_recall_summary = _compute_recall_summary(report.golden_recall)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Golden recall non calculÃ© : %s", exc)

    # Quarantine
    report.quarantine = _collect_quarantine()

    # Services health
    report.health = _check_services()

    return report


def main(output_json: bool = False, output_md: bool = False) -> GoldenReport:
    """Point d'entrÃ©e CLI â€” gÃ©nÃ©ration + affichage du rapport."""
    report = generate_report()

    # Affichage terminal couleur
    _format_terminal(report)

    # Fichiers de sortie
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if output_json or not output_md:
        json_path = reports_dir / f"golden_report_{stamp}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, ensure_ascii=False, indent=2)
        print(f"Rapport JSON : {json_path}")

    if output_md or not output_json:
        md_path = reports_dir / f"golden_report_{stamp}.md"
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(_format_markdown(report))
        print(f"Rapport Markdown : {md_path}")

    return report


if __name__ == "__main__":
    main()
