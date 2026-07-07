"""ingestor/regression.py — Regression tester le golden set contre un environnement storage vectoriel.

Responsabilites :
  1. Rejouer chaque question du golden set contre staging ou production
  2. Calculer recall@5 par question et moyenne globale
  3. Retourner un resultat structure avec les echecs detailles
  4. Comparer deux campagnes (avant/apres MAJ) pour detecter les regressions

Usage :
  python -m ingestor.regression --env staging         # contre staging
  python -m ingestor.regression --env production       # contre production
  python -m ingestor.regression --baseline golden_run1.json   # comparer vs baseline
  python -m ingestor.regression --json                 # output JSON pour CI
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent
GOLDEN_FILE = ROOT / "tests" / "golden_set" / "golden.json"


# ── Resultats ────────────────────────────────────────────────────────────────


@dataclass
class RegressionResult:
    """Une campagne de regression test."""
    campaign_id: str
    env: str                      # staging | production
    game_version: str             # b41 / b42 (global)
    timestamp: str                # ISO 8601
    total_questions: int
    passed_questions: int
    failed_questions: int
    avg_recall: float             # moyenne recall@5
    min_recall: float             # recall le plus bas
    per_question: list[dict]      # [{id, recall, hits, missing, question}]
    baseline_file: Optional[str]  # si on compare vs un fichier
    regressions: Optional[list[dict]] = None  # si comparaison avec baseline
    improvements: Optional[list[dict]] = None  # si comparaison avec baseline

    @property
    def passed(self) -> bool:
        return self.avg_recall >= 0.75   # seuil identique a promote.py

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passed"] = self.passed  # property non serialise automatiquement par dataclass
        return d


# ── Runner ───────────────────────────────────────────────────────────────────


def _load_golden(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Golden set not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _run_campaign(
    golden_path: Path,
    env: str = "staging",
) -> RegressionResult:
    """Lance le golden set sur l'environnement specifie.

    Args:
        golden_path: Chemin vers golden.json.
        env: 'staging' ou 'production'.

    Returns:
        RegressionResult avec tous les details de la campagne.
    """
    correlation_id = str(uuid.uuid4())[:8]
    questions = _load_golden(golden_path)
    per_question: list[dict] = []
    recall_scores: list[float] = []

    # Import lazy — selectionne le bon client storage vectoriel
    if env == "staging":
        from src.retrieval import query_staging as query_fn  # type: ignore[misc]
    elif env == "production":
        from src.retrieval import get_production_client  # type: ignore[misc]
        storage_client = get_production_client()
        query_fn = storage_client.query
    else:
        raise ValueError(f"Unknown env: {env!r}. Use 'staging' or 'production'.")

    # Detect game_version dominant dans les filtres
    versions_seen: list[str] = []
    for q in questions:
        fv = (q.get("filter") or {}).get("version")
        if fv:
            versions_seen.append(fv)

    game_version = "mixed"
    if versions_seen:
        from collections import Counter
        most_common = Counter(versions_seen).most_common(1)[0][0]
        game_version = most_common

    for q in questions:
        qid = q.get("id", "?")
        question = q.get("question", "")
        expected = set(q.get("expected_ids", []))
        filters = q.get("filter")

        if not question:
            continue

        try:
            result = query_fn(question, k=5, filters=filters)
        except Exception as exc:
            score_entry = {
                "id": qid,
                "recall": 0.0,
                "hits": 0,
                "missing": list(expected),
                "question": question[:80],
                "error": str(exc),
            }
            per_question.append(score_entry)
            recall_scores.append(0.0)
            continue

        retrieved_ids = {c["id"] for c in result.get("chunks", [])}
        hits = len(expected & retrieved_ids)
        missing = expected - retrieved_ids
        recall = hits / len(expected) if expected else 0.0
        recall_scores.append(recall)

        per_question.append({
            "id": qid,
            "recall": round(recall, 4),
            "hits": hits,
            "expected": list(expected),
            "missing": list(missing),
            "question": question[:80],
        })

    avg = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0
    failed_ids = [pq["id"] for pq in per_question if pq["recall"] < 0.75]
    passed_count = len(per_question) - len(failed_ids)

    return RegressionResult(
        campaign_id=correlation_id,
        env=env,
        game_version=game_version,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_questions=len(per_question),
        passed_questions=passed_count,
        failed_questions=len(failed_ids),
        avg_recall=round(avg, 4),
        min_recall=round(min(recall_scores), 4) if recall_scores else 0.0,
        per_question=per_question,
        baseline_file=None,
    )


# ── Comparaison baseline ────────────────────────────────────────────────────


def _compare_against_baseline(
    current: RegressionResult,
    baseline_path: Path,
) -> RegressionResult:
    """Compare la campagne actuelle vs un fichier de baseline JSON."""
    with open(baseline_path, encoding="utf-8") as fh:
        baseline_data = json.load(fh)

    baseline_dict = baseline_data if isinstance(baseline_data, dict) else {}
    current_dict = current.to_dict()
    current_dict["baseline_file"] = str(baseline_path)

    # Detect regressions par question
    baseline_by_id: dict[str, float] = {
        pq["id"]: pq["recall"] for pq in baseline_data.get("per_question", [])
    }
    regressions: list[dict] = []
    improvements: list[dict] = []
    for pq in current.per_question:
        qid = pq["id"]
        old_recall = baseline_by_id.get(qid, 0.0)
        new_recall = pq["recall"]
        delta = new_recall - old_recall
        if delta < -0.1:
            regressions.append({"id": qid, "old": old_recall, "new": new_recall, "delta": round(delta, 4)})
        elif delta > 0.1:
            improvements.append({"id": qid, "old": old_recall, "new": new_recall, "delta": round(delta, 4)})

    current_dict["regressions"] = regressions
    current_dict["improvements"] = improvements

    # Ne pas propager les champs non-__init__ (passed ajoute par to_dict, per_question passed separately)
    excluded = {"per_question", "passed"}
    kwargs = {k: v for k, v in current_dict.items() if k not in excluded}
    return RegressionResult(
        **kwargs,
        per_question=current.per_question,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regression tester le golden set contre storage vectoriel.",
        prog="python -m ingestor.regression",
    )
    parser.add_argument(
        "--env",
        choices=["staging", "production"],
        default="staging",
        help="Environnement cible (default: staging)",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=GOLDEN_FILE,
        help="Chemin vers golden.json (default: tests/golden_set/golden.json)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Fichier baseline JSON pour comparer (detecte les regressions)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output resultat en JSON sur stdout",
    )
    args = parser.parse_args(argv)

    try:
        result = _run_campaign(args.golden, args.env)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.baseline:
        result = _compare_against_baseline(result, args.baseline)

    # Affichage console
    status = "PASS" if result.passed else "FAIL"
    print(f"[Regression] env={result.env} game_version={result.game_version}")
    print(f"[Regression] {result.passed_questions}/{result.total_questions} passes (avg recall={result.avg_recall:.4f}) [{status}]")

    if result.failed_questions > 0:
        print(f"\n[Regression] Questions échouées:")
        for pq in result.per_question:
            if pq["recall"] < 0.75:
                missing = pq.get("missing", [])
                print(f"  ✗ {pq['id']}: recall={pq['recall']:.2f} missing={missing}")

    # Regressions vs baseline
    if args.baseline and "regressions" in (result_dict := result.to_dict()):
        reals = result_dict["regressions"]
        if reals:
            print(f"\n[Regression] Regressions détectées:")
            for r in reals:
                print(f"  ✗ {r['id']}: {r['old']:.2f} → {r['new']:.2f} ({r['delta']:+.4f})")

    # Output JSON si demande
    if args.json:
        result_dict = result.to_dict()
        if args.baseline and "regressions" in result_dict:
            pass  # regressions deja ajoutees dans _compare_against_baseline
        print(json.dumps(result_dict, ensure_ascii=False, indent=2))

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
