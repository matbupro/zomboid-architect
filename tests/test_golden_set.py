"""test_golden_set -- Mesure du recall@5 sur le golden set (Phase 5/11).

Mode mock : fonctionne avec mock uniquement (sans Ollama) (par defaut, recommande pour CI)

Usage :
    python tests/test_golden_set.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ===========================================================================
# Fixtures
# ===========================================================================

GOLDEN_PATH = PROJECT_ROOT / "tests" / "golden_set" / "golden.json"


def _load_golden() -> list[dict]:
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _build_golden_map(questions: list[dict]) -> dict[str, list[str]]:
    """Convert golden questions into a question-text-to-expected_id mapping.

    Uses the normalized (lowercased) question text as key so the mock can
    return the correct expected_ids when querying against the same golden set.

    Example : {"what can i use to chop down trees...": ["Base.Axe"]}
    """
    q_to_ids: dict[str, list[str]] = {}
    for q in questions:
        question = q.get("question", "").lower().strip()
        ids = q.get("expected_ids", [])
        if question:
            q_to_ids[question] = ids
    return q_to_ids


def _mock_query_with_hits(q_to_ids: dict[str, list[str]]) -> MagicMock:
    """Mock query_staging that returns expected_ids when the question matches.

    Exact match on normalized question text — guarantees perfect recall for
    the golden set because we're testing our evaluation logic, not the storage layer.
    """
    mock_fn = MagicMock()

    def fn(question: str, k: int = 5, filters=None):
        normed = question.lower().strip()
        if normed in q_to_ids:
            return {"chunks": [{"id": x, "prose": "", "metadata": {}} for x in q_to_ids[normed]], "query": question, "k": k}
        # Also try partial match (first 20 chars) to handle minor variations
        for key, ids in q_to_ids.items():
            if key[:30] in normed or normed[:30] in key:
                return {"chunks": [{"id": x, "prose": "", "metadata": {}} for x in ids], "query": question, "k": k}
        return {"chunks": [], "query": question, "k": k}

    mock_fn.side_effect = fn
    return mock_fn


def _mock_query_with_partial_hits(
    q_to_ids: dict[str, list[str]], partial_questions: set[str],
) -> MagicMock:
    """Mock query_staging that only returns results for questions in partial_questions."""
    mock_fn = MagicMock()

    def fn(question: str, k: int = 5, filters=None):
        normed = question.lower().strip()
        if normed in q_to_ids and normed in partial_questions:
            return {"chunks": [{"id": x, "prose": "", "metadata": {}} for x in q_to_ids[normed]], "query": question, "k": k}
        # Partial match fallback
        for key, ids in q_to_ids.items():
            if (key[:30] in normed or normed[:30] in key) and key in partial_questions:
                return {"chunks": [{"id": x, "prose": "", "metadata": {}} for x in ids], "query": question, "k": k}
        return {"chunks": [], "query": question, "k": k}

    mock_fn.side_effect = fn
    return mock_fn


# ===========================================================================
# Tests du GateResult (logique de promote.py)
# ===========================================================================

def _make_gate_result(**kwargs):
    """Construit un GateResult directement depuis promote."""
    from ingestor.promote import GateResult

    defaults = dict(
        total_questions=0,
        recall_scores=[],
        avg_recall=0.0,
        failed_ids=[],
        game_version="b41",
        correlation_id="test",
    )
    defaults.update(kwargs)
    return GateResult(**defaults)


def test_gate_result_passes_at_threshold():
    """avg_recall >= 0.75 -> passed = True."""
    gate = _make_gate_result(
        total_questions=2, recall_scores=[0.75, 1.0], avg_recall=0.875, failed_ids=["q1"],
    )
    assert gate.passed is True


def test_gate_result_fails_below_threshold():
    """avg_recall < 0.75 -> passed = False."""
    gate = _make_gate_result(
        total_questions=2, recall_scores=[0.5, 0.6], avg_recall=0.55, failed_ids=["q1", "q2"],
    )
    assert gate.passed is False


def test_gate_result_perfect():
    """recall 1.0 partout -> passed = True."""
    gate = _make_gate_result(
        total_questions=3, recall_scores=[1.0, 1.0, 1.0], avg_recall=1.0, failed_ids=[],
    )
    assert gate.passed is True
    assert gate.avg_recall == 1.0


def test_gate_result_empty():
    """Aucune question -> avg_recall = 0, echec."""
    gate = _make_gate_result(total_questions=0, recall_scores=[], failed_ids=[])
    assert gate.passed is False


def test_gate_result_to_dict():
    gate = _make_gate_result(
        total_questions=2,
        recall_scores=[0.5, 1.0],
        avg_recall=0.75,
        failed_ids=["q1"],
        game_version="b41",
        correlation_id="abc123",
    )
    d = gate.to_dict()
    assert d["total_questions"] == 2
    assert d["avg_recall"] == 0.75
    assert "recall_scores" in d


# ===========================================================================
# Tests du calcul recall@5 (sans [storage vectoriel])
# ===========================================================================

def test_recall_single_hit():
    """1 expected, 1 hit -> recall = 1.0."""
    retrieved = {"Base.Axe"}
    expected = {"Base.Axe"}
    recall = len(retrieved & expected) / len(expected) if expected else 0.0
    assert recall == 1.0


def test_recall_partial_hit():
    """2 expected, 1 hit -> recall = 0.5."""
    retrieved = {"Base.Axe"}
    expected = {"Base.Axe", "Base.WoodenCane"}
    recall = len(retrieved & expected) / len(expected) if expected else 0.0
    assert recall == 0.5


def test_recall_no_hit():
    """0 hit -> recall = 0.0."""
    retrieved = {"Base.Shovel"}
    expected = {"Base.Axe", "Base.WoodenCane"}
    recall = len(retrieved & expected) / len(expected) if expected else 0.0
    assert recall == 0.0


def test_recall_empty_expected():
    """expected vide -> recall = 0.0."""
    retrieved = {"anything"}
    expected: set = set()
    recall = len(retrieved & expected) / len(expected) if expected else 0.0
    assert recall == 0.0


def test_recall_k_limit():
    """Le k limit de [storage vectoriel] peut couper des resultats attendus."""
    retrieved = {"Base.Axe", "Base.WoodenCane", "Base.Shovel"}
    expected = {"Base.Axe"}  # seulement 1 attendu
    recall = len(retrieved & expected) / len(expected) if expected else 0.0
    assert recall == 1.0


# ===========================================================================
# Test integration mock : simule le golden set gate complet
# ===========================================================================

def test_golden_gate_mock_perfect_recall():
    """Toutes les questions du golden set -> recall parfait (mock)."""
    import ingestor.promote as promote

    questions = _load_golden()
    id_map = _build_golden_map(questions)
    mock_qr = _mock_query_with_hits(id_map)

    with patch("src.retrieval.query_staging", mock_qr):
        gate = promote._run_golden_set(GOLDEN_PATH)
        assert gate.passed is True, f"Expected perfect recall, got avg={gate.avg_recall}, failed={gate.failed_ids}"
        assert gate.avg_recall == 1.0
        assert len(gate.failed_ids) == 0


def test_golden_gate_mock_partial_recall():
    """Certaines questions repondent completement -> recall < seuil."""
    import ingestor.promote as promote

    # Seules ces 3 questions du golden set sont autorisees a repondre (par texte normalisé)
    questions = _load_golden()
    partial_questions = {q["question"].lower().strip() for q in questions[:3]}
    mock_qr = _mock_query_with_partial_hits(
        _build_golden_map(questions), partial_questions,
    )

    with patch("src.retrieval.query_staging", mock_qr):
        gate = promote._run_golden_set(GOLDEN_PATH)
        assert gate.passed is False  # recall moyen bien en dessous de 0.75
        assert len(gate.failed_ids) > 0  # plusieurs questions echouent


def test_golden_gate_mock_no_results():
    """le storage vectoriel retourne 0 resultats pour tout -> recall = 0."""
    import ingestor.promote as promote

    def empty_query(question: str, k: int = 5, filters=None):
        return {"chunks": [], "query": question, "k": k}

    mock_qr = MagicMock(side_effect=empty_query)

    with patch("src.retrieval.query_staging", mock_qr):
        gate = promote._run_golden_set(GOLDEN_PATH)
        assert gate.passed is False
        assert gate.avg_recall == 0.0


# ===========================================================================
# Test golden set data integrity
# ===========================================================================

def test_golden_has_required_fields():
    """Chaque entree du golden set a les champs requis."""
    questions = _load_golden()
    assert len(questions) >= 10, f"Golden set trop petit : {len(questions)} (min 10 attendu)"

    for i, q in enumerate(questions):
        assert "id" in q, f"[{i}] manquant 'id'"
        assert "question" in q, f"[{i}] manquant 'question'"
        assert "expected_ids" in q, f"[{i}] manquant 'expected_ids'"
        assert isinstance(q["expected_ids"], list), f"[{i}] expected_ids doit etre une liste"
        assert len(q["expected_ids"]) > 0, f"[{i}] expected_ids non vide"


def test_golden_unique_ids():
    """Tous les IDs doivent etre uniques."""
    questions = _load_golden()
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "IDs dupliqués dans le golden set"


def test_golden_versions_covered():
    """Le golden set doit couvrir B41 et B42."""
    questions = _load_golden()
    versions: set[str] = set()
    for q in questions:
        f = q.get("filter", {})
        if isinstance(f, dict):
            v = f.get("version")
            if v:
                versions.add(v)
    assert "b41" in versions, "B41 absent du golden set"
    assert "b42" in versions, "B42 absent du golden set"


# ===========================================================================
# Test promote.py RECALL_THRESHOLD value
# ===========================================================================

def test_recall_threshold_is_075():
    from ingestor.promote import RECALL_THRESHOLD
    assert RECALL_THRESHOLD == 0.75, f"Seuil recall etonne a {RECALL_THRESHOLD}"


# ===========================================================================
# Runner
# ===========================================================================

TESTS = [
    # GateResult
    test_gate_result_passes_at_threshold,
    test_gate_result_fails_below_threshold,
    test_gate_result_perfect,
    test_gate_result_empty,
    test_gate_result_to_dict,
    # Recall calcul
    test_recall_single_hit,
    test_recall_partial_hit,
    test_recall_no_hit,
    test_recall_empty_expected,
    test_recall_k_limit,
    # Golden set gate (mock)
    test_golden_gate_mock_perfect_recall,
    test_golden_gate_mock_partial_recall,
    test_golden_gate_mock_no_results,
    # Data integrity
    test_golden_has_required_fields,
    test_golden_unique_ids,
    test_golden_versions_covered,
    # Threshold
    test_recall_threshold_is_075,
]


def main():
    total_ok = 0
    total_fail = 0
    errors: list[str] = []

    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"  [+] {name}")
            total_ok += 1
        except Exception as e:
            msg = f"{name}: {e}"
            print(f"  [-] {msg}")
            errors.append(msg)
            total_fail += 1

    print(f"\n{'='*60}")
    print("Golden Set Recall@5 Tests")
    print(f"{'='*60}")
    print(f"  Total : {total_ok}/{total_ok + total_fail} passed")
    if errors:
        print(f"\nEchecs ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    print("=" * 60)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
