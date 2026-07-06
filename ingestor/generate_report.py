"""generate_report — Rapport de qualite pour le Zomboid Knowledge Engine.

Connecte a ChromaDB, calcule le recall du golden set, compte les entites
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

from ingestor.config import load_config          # noqa: E402
from src.retrieval.chroma_client import ChromaClient  # noqa: E402
from src.governance.logger import get_logger     # noqa: E402

logger = get_logger("ingestor.generate_report")

# ──────────────────────────────────────────────────────────────────────────────
# Golden set helpers — reuse de tests/test_golden_set.py
# ──────────────────────────────────────────────────────────────────────────────

GOLDEN_PATH = PROJECT_ROOT / "tests" / "golden_set" / "golden.json"


def _load_golden() -> list[dict[str, Any]]:
    if not GOLDEN_PATH.exists():
        logger.warning("Golden set introuvable : %s", GOLDEN_PATH)
        return []
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ──────────────────────────────────────────────────────────────────────────────
# Terminal colors — ANSI (désactivé sur Windows par defaut)
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Report data model
# ──────────────────────────────────────────────────────────────────────────────

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
    chroma_online: bool = False
    chroma_version: str = ""
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


# ──────────────────────────────────────────────────────────────────────────────
# Data collection
# ──────────────────────────────────────────────────────────────────────────────

def _collect_collections(chroma: ChromaClient) -> list[CollectionInfo]:
    """Liste les collections ChromaDB et compte les documents via API raw."""
    import chromadb  # noqa: E402

    infos: list[CollectionInfo] = []
    known = (
        "pz_items", "pz_recipes", "pz_mechanics",
        "pz_lua_api", "pz_java_api", "pz_web_pages",
        "pz_pdfs", "pz_images", "pz_videos", "pz_audios",
        "pz_mods", "pz_workshop_items", "pz_mod_lua_scripts", "pz_mod_configs",
    )

    # Connexion directe via HTTP ou file store (comme ChromaClient)
    host = chroma._chroma_host if hasattr(chroma, "_chroma_host") else "http://localhost:8000"  # noqa: SLF001
    client: Any | None = None

    try:
        client = chromadb.HttpClient(host=host)
    except Exception:  # noqa: BLE001
        # Fallback local (si pas de serveur Docker)
        try:
            client = chromadb.PersistentClient(path=str(PROJECT_ROOT / "data" / "staging"))
        except Exception:  # noqa: BLE001
            pass

    collections = []
    collection_names: set[str] = set()
    if client:
        try:
            collections = list(client.list_collections())
            collection_names = {c.name for c in collections}
        except Exception:  # noqa: BLE001
            pass

    # Collections existantes
    for col in collections:
        count = 0
        try:
            count = col.count()
        except Exception:  # noqa: BLE001
            pass
        infos.append(CollectionInfo(name=col.name, count=count))

    # Collections connues sans docs (non creees dans ChromaDB)
    for name in known:
        if name not in collection_names:
            infos.append(CollectionInfo(name=name, count=0))

    return infos


def _compute_golden_recall(
    chroma: ChromaClient, golden: list[dict]
) -> dict[str, GoldenHit]:
    """Calcule recall@5 par question du golden set via ChromaDB reel."""
    hits: dict[str, GoldenHit] = {}

    for entry in golden:
        qid = entry.get("id", "unknown")
        question = entry.get("question", "")
        expected_ids = set(entry.get("expected_ids", []))
        filter_params = entry.get("filter")

        try:
            # Utiliser les collections connues (ChromaClient.query ne prend pas de liste)
            results = chroma.query(
                question=question,
                k=max(5, len(expected_ids) * 3),
                filters={
                    "$and": [filter_params]
                } if filter_params else None,
            )

            hit_at_rank: int | None = None
            found_ids: set[str] = set()
            chunks = results.get("chunks", [])

            for rank, chunk in enumerate(chunks, start=1):
                cid = chunk.get("id", "")
                meta = chunk.get("metadata", {})
                candidates = {cid}
                if isinstance(meta, dict):
                    for key in ("item_id", "id", "name", "result"):
                        val = meta.get(key)
                        if val:
                            candidates.add(str(val))

                for exp in list(expected_ids):
                    if exp.lower() in {c.lower() for c in candidates} or exp in candidates:
                        found_ids.add(exp)
                        if hit_at_rank is None:
                            hit_at_rank = rank

            recall = len(found_ids & expected_ids) / max(1, len(expected_ids))
            missed = expected_ids - found_ids

            hits[qid] = GoldenHit(
                recall=round(recall, 3),
                expected=len(expected_ids),
                found=len(found_ids),
                hit_at_rank=hit_at_rank,
                missed_ids=sorted(missed),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Golden recall %s échoué : %s", qid, exc)
            hits[qid] = GoldenHit(recall=-1, expected=len(expected_ids), found=0, missed_ids=sorted(expected_ids))

    return hits


def _compute_recall_summary(hits: dict[str, GoldenHit]) -> dict[str, Any]:
    """Résumé du recall sur toutes les questions."""
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
    """Vérifie la disponibilité des services."""
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

    # ChromaDB
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://host.docker.internal:8000/api/v2/heartbeat", timeout=5)
        if resp.status == 200:
            health.chroma_online = True
            health.chroma_version = resp.read().decode()[:10]
    except Exception:  # noqa: BLE001
        try:
            import urllib.request
            resp = urllib.request.urlopen("http://host.docker.internal:8000/api/v2", timeout=5)
            if resp.status == 200:
                health.chroma_online = True
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


# ──────────────────────────────────────────────────────────────────────────────
# Report formatting
# ──────────────────────────────────────────────────────────────────────────────

def _format_terminal(report: GoldenReport) -> None:
    """Affiche le rapport dans le terminal coloré."""
    sep = "============================================================"

    print()
    print(sep)
    print("Zomboid Knowledge Engine — Rapport de Qualité")
    print(f"Généré : {report.timestamp}")
    print(sep)

    # Collections
    print("\nCollections ChromaDB")
    for col in sorted(report.collections, key=lambda c: c.name):
        if col.count < 0:
            status = " [ERREUR]"
        elif col.count == 0:
            status = " (vide)"
        else:
            status = ""
        print(f"   {col.name:<25} {col.count:>6d} docs  (avg_meta: {col.avg_metadata_fields}){status}")

    # Golden Recall
    print("\nGolden Set — Recall@5")
    for qid, hit in report.golden_recall.items():
        if hit.recall < 0:
            bar = f"[ERREUR]"
        elif hit.recall >= 1.0:
            bar = f"recall={hit.recall:.3f} ({hit.found}/{hit.expected})"
        else:
            bar = (f"recall={hit.recall:.3f} ({hit.found}/{hit.expected}"
                   + (f", hit@{hit.hit_at_rank}" if hit.hit_at_rank else "")
                   + f" — manquants: {', '.join(hit.missed_ids)}])")
        print(f"   {qid:<30}  {bar}")

    # Summary
    summary = report.golden_recall_summary
    avg = summary.get("avg_recall", 0)
    stars_ok = "★" * int(avg * 10)
    stars_bad = "·" * (10 - int(avg * 10))
    print(f"\n   {stars_ok}{stars_bad} recall moyen: {avg:.3f}")
    print(f"   parfait: {summary.get('questions_with_perfect_recall', 0)}/{summary.get('total_questions', 0)}")
    if summary.get("missed_ids"):
        print(f"   IDs jamais trouvés : {', '.join(summary['missed_ids'][:10])}")

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
        print("   Aucune donnée quarantainée")

    # Health
    print("\nServices")
    ol = "✓ En ligne" if report.health.ollama_online else "✘ Hors ligne"
    ol += f" — {', '.join(report.health.ollama_models[:3])}" if report.health.ollama_online else ""
    ch = "✓ En ligne" if report.health.chroma_online else "✘ Hors ligne"
    ch += f" v{report.health.chroma_version}" if report.health.chroma_online and report.health.chroma_version else ""
    disk_color = "+" if report.health.disk_free_gb > 2 else "~"
    print(f"   Ollama : {ol}")
    print(f"   ChromaDB : {ch}")
    print(f"   Disque libre : {report.health.disk_free_gb} GB {disk_color}")

    print(f"\n{sep}\n")


def _format_markdown(report: GoldenReport) -> str:
    """Génère un rapport Markdown."""
    lines = [
        "# Rapport de Qualité — Zomboid Knowledge Engine",
        "",
        f"*Généré le {report.timestamp}*",
        "",
        "## Collections ChromaDB",
        "",
        "| Collection | Nom | Docs | Avg Metadata |",
        "|---|---|---|---|",
    ]

    for col in sorted(report.collections, key=lambda c: c.name):
        lines.append(f"| • | `{col.name}` | {col.count} | {col.avg_metadata_fields} |")

    lines += ["", "## Golden Set — Recall@5", ""]

    header = "| Question ID | Recall | Trouvés/Attendus | Hit @ Rank | IDs manqués |"
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
        lines.append(f"IDs jamais trouvés : {', '.join(s['missed_ids'])}")

    lines += ["", "## Quarantaine"]
    if report.quarantine.total_entries:
        lines.append(f"**Total** : {report.quarantine.total_entries} erreurs")
        for date, count in sorted(report.quarantine.by_date.items()):
            lines.append(f"- `{date}` : {count}")
        if report.quarantine.recent_errors:
            lines.append("**Dernières erreurs :**")
            for err in report.quarantine.recent_errors[-3:]:
                snippet = err.get("snippet", str(err.get("exc_info", "N/A")))[:80]
                lines.append(f"- `{snippet}`")
    else:
        lines.append("*Aucune donnée quarantainée*")

    lines += ["", "## Services"]
    ol = f"{'✓' if report.health.ollama_online else '✘'} Ollama"
    if report.health.ollama_online:
        ol += f" — {', '.join(report.health.ollama_models[:3])}"
    ch = f"{'✓' if report.health.chroma_online else '✘'} ChromaDB"
    if report.health.chroma_online and report.health.chroma_version:
        ch += f" v{report.health.chroma_version}"
    lines.extend([ol, ch, f"**Disque libre** : {report.health.disk_free_gb} GB"])

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def generate_report() -> GoldenReport:
    """Génère le rapport complet et retourne l'objet structuré."""
    report = GoldenReport(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M UTC"),
    )

    # Collections
    try:
        config = load_config()
        chroma = ChromaClient(host=config.CHROMA_HOST)
        report.collections = _collect_collections(chroma)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Collections non accessibles : %s", exc)

    # Golden Recall
    golden = _load_golden()
    if golden:
        try:
            config = load_config()
            chroma = ChromaClient(host=config.CHROMA_HOST)
            report.golden_recall = _compute_golden_recall(chroma, golden)
            report.golden_recall_summary = _compute_recall_summary(report.golden_recall)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Golden recall non calculé : %s", exc)

    # Quarantine
    report.quarantine = _collect_quarantine()

    # Services health
    report.health = _check_services()

    return report


def main(output_json: bool = False, output_md: bool = False) -> GoldenReport:
    """Point d'entrée CLI — génération + affichage du rapport."""
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
