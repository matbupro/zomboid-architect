"""tests/test_regression.py — Tests du regression runner (golden set recall).

Couvre :
  - _load_golden() chargement et validation du golden.json
  - RegressionResult dataclass (passed, to_dict)
  - _run_campaign() avec mock StorageBackend (patch src.retrieval.query_staging)
  - Comparaison baseline (regressions / improvements detection)
  - CLI output JSON vs text
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GOLDEN_PATH = PROJECT_ROOT / "tests" / "golden_set" / "golden.json"


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def mock_questions():
    """Questions minimales pour le golden set."""
    return [
        {
            "id": "test-1",
            "question": "Query 1?",
            "expected_ids": ["item.A", "item.B"],
            "filter": {"type": "item", "version": "b41"},
        },
        {
            "id": "test-2",
            "question": "Query 2?",
            "expected_ids": ["item.C"],
            "filter": {"type": "mechanic", "version": "b42"},
        },
    ]


@pytest.fixture()
def mock_golden_file(tmp_path: Path):
    """Ecrit des questions dans un fichier golden temporaire."""
    questions = [
        {"id": "q1", "question": "What is an axe?", "expected_ids": ["Base.Axe"], "filter": {"type": "item"}},
        {"id": "q2", "question": "How to craft bread?", "expected_ids": ["Base.Bread", "Base.Wheat"], "filter": {}},
    ]
    f = tmp_path / "golden_test.json"
    f.write_text(json.dumps(questions), encoding="utf-8")
    return f


# ===========================================================================
# Tests : _load_golden
# ===========================================================================


def test_load_golden_from_real_file():
    """Charger le vrai golden.json ne leve pas d'exception."""
    from ingestor.regression import _load_golden

    questions = _load_golden(GOLDEN_PATH)
    assert len(questions) == 28


def test_load_golden_nonexistent(tmp_path: Path):
    """Charger un fichier inexistant → FileNotFoundError."""
    from ingestor.regression import _load_golden

    with pytest.raises(FileNotFoundError, match="Golden set not found"):
        _load_golden(tmp_path / "nonexistent.json")


def test_load_golden_returns_list():
    """Retourne une liste de dicts avec les champs attendus."""
    from ingestor.regression import _load_golden

    questions = _load_golden(GOLDEN_PATH)
    assert isinstance(questions, list)
    for q in questions:
        assert "id" in q
        assert "question" in q


# ===========================================================================
# Tests : RegressionResult dataclass
# ===========================================================================


def test_regression_result_passed_high_recall():
    """avg_recall >= 0.75 → passed=True."""
    from ingestor.regression import RegressionResult

    r = RegressionResult(
        campaign_id="abc", env="staging", game_version="b41",
        timestamp="2026-07-04T00:00:00+00:00", total_questions=5,
        passed_questions=5, failed_questions=0, avg_recall=0.95,
        min_recall=0.80, per_question=[], baseline_file=None,
    )
    assert r.passed is True


def test_regression_result_failed_low_recall():
    """avg_recall < 0.75 → passed=False."""
    from ingestor.regression import RegressionResult

    r = RegressionResult(
        campaign_id="abc", env="staging", game_version="b41",
        timestamp="2026-07-04T00:00:00+00:00", total_questions=5,
        passed_questions=3, failed_questions=2, avg_recall=0.65,
        min_recall=0.40, per_question=[], baseline_file=None,
    )
    assert r.passed is False


def test_regression_result_to_dict():
    """to_dict retourne un dict avec tous les champs y compris 'passed'."""
    from ingestor.regression import RegressionResult

    r = RegressionResult(
        campaign_id="abc", env="staging", game_version="b41",
        timestamp="2026-07-04T00:00:00+00:00", total_questions=3,
        passed_questions=3, failed_questions=0, avg_recall=1.0,
        min_recall=1.0, per_question=[], baseline_file=None,
    )
    d = r.to_dict()
    assert isinstance(d, dict)
    assert d["campaign_id"] == "abc"
    assert d["passed"] is True


# ===========================================================================
# Tests : _run_campaign avec mock StorageBackend
# ===========================================================================

# IMPORTANT : query_staging est importe lazy dans _run_campaign (from src.retrieval import ...)
# Donc on patch 'src.retrieval.query_staging' et non 'ingestor.regression.query_staging'


def test_run_campaign_all_pass(mock_golden_file: Path):
    """Toutes les questions recall@5=1.0 → campaign passed."""
    from ingestor.regression import _run_campaign

    def mock_query_fn(question, k, filters):
        if "axe" in question.lower():
            return {"chunks": [{"id": "Base.Axe", "distance": 0.1}]}
        return {"chunks": [
            {"id": "Base.Bread", "distance": 0.1},
            {"id": "Base.Wheat", "distance": 0.2},
        ]}

    with patch("src.retrieval.query_staging", side_effect=mock_query_fn):
        result = _run_campaign(mock_golden_file, env="staging")

    assert result.passed is True
    assert result.failed_questions == 0
    assert result.avg_recall > 0.75


def test_run_campaign_some_fail(mock_golden_file: Path):
    """Une question recall=0 → failed_questions = 1."""
    from ingestor.regression import _run_campaign

    def mock_query_func(question, k, filters):
        return {"chunks": [{"id": "Base.Axe", "distance": 0.1}]}

    with patch("src.retrieval.query_staging", side_effect=mock_query_func):
        result = _run_campaign(mock_golden_file, env="staging")

    assert result.passed is False
    assert result.failed_questions >= 1


def test_run_campaign_handles_missing_chunks(tmp_path: Path):
    """Pas de chunks dans la reponse → recall=0."""
    from ingestor.regression import _run_campaign

    golden = tmp_path / "golden_missing.json"
    golden.write_text('[{"id":"q1","question":"Q?","expected_ids":["x"],"filter":{}}]')

    with patch("src.retrieval.query_staging", return_value={"chunks": []}):
        result = _run_campaign(golden, env="staging")

    assert result.avg_recall < 1.0


def test_run_campaign_handles_query_exception(tmp_path: Path):
    """storage down → recall=0 pour cette question (pas d'exception)."""
    from ingestor.regression import _run_campaign

    golden = tmp_path / "golden_exc.json"
    golden.write_text('[{"id":"q1","question":"Q?","expected_ids":["x"],"filter":{}},{"id":"q2","question":"Q2?","expected_ids":["y"],"filter":{}}]')

    with patch("src.retrieval.query_staging", side_effect=ConnectionError("no storage vectoriel")):
        result = _run_campaign(golden, env="staging")

    assert len(result.per_question) == 2


def test_run_campaign_detects_game_version(tmp_path: Path):
    """La version dominante dans les filtres est detectee."""
    from ingestor.regression import _run_campaign

    questions_v42 = [
        {"id": "q1", "question": "Q?", "expected_ids": ["x"], "filter": {"version": "b42"}},
        {"id": "q2", "question": "Q?", "expected_ids": ["y"], "filter": {"version": "b42"}},
    ]
    tmp = tmp_path / "v42.json"
    tmp.write_text(json.dumps(questions_v42))

    with patch("src.retrieval.query_staging", return_value={"chunks": [{"id": "x"}]}):
        result = _run_campaign(tmp, env="staging")

    assert result.game_version == "b42"


# ===========================================================================
# Tests : Comparaison baseline
# ===========================================================================


def test_compare_baseline_detects_regression(mock_golden_file: Path, tmp_path: Path):
    """recall de 0.5 a 0.1 → regression detectee."""
    from ingestor.regression import _run_campaign, _compare_against_baseline

    # Mock query_staging pour avoir des scores controlés
    def mock_query(question, k, filters):
        return {"chunks": [{"id": "Base.Axe", "distance": 0.1}]}

    baseline_data = {
        "per_question": [
            {"id": "q1", "recall": 1.0},
            {"id": "q2", "recall": 1.0},
        ],
    }

    with patch("src.retrieval.query_staging", side_effect=mock_query):
        current = _run_campaign(mock_golden_file, env="staging")
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps(baseline_data))

    # Simuler regression manuelle
    for pq in current.per_question:
        pq["recall"] = 0.2

    result = _compare_against_baseline(current, baseline_file)
    assert "regressions" in (d := result.to_dict())
    assert len(d["regressions"]) == 2


# ===========================================================================
# Tests : CLI
# ===========================================================================


def test_cli_json_output(mock_golden_file: Path):
    """Output --json produce du JSON valide sur stdout."""
    import io
    from contextlib import redirect_stdout
    from ingestor.regression import RegressionResult, main as regression_main
    from datetime import datetime, timezone

    correlation_id = "test-001"

    # Patch _run_campaign pour éviter de charger le vrai golden.json (28 questions)
    def mock_run_camp(golden_path, env):
        per_question = [
            {"id": "q1", "recall": 1.0, "hits": 1, "expected": ["Base.Axe"], "missing": [], "question": "What is an axe?"},
            {"id": "q2", "recall": 1.0, "hits": 1, "expected": ["Base.Bread"], "missing": [], "question": "How to craft bread?"},
        ]
        return RegressionResult(
            campaign_id=correlation_id, env=env, game_version="mixed",
            timestamp=datetime.now(timezone.utc).isoformat(), total_questions=2,
            passed_questions=2, failed_questions=0, avg_recall=1.0,
            min_recall=1.0, per_question=per_question, baseline_file=None,
        )

    f = io.StringIO()
    with patch("ingestor.regression._run_campaign", mock_run_camp):
        with redirect_stdout(f):
            code = regression_main(["--golden", str(mock_golden_file), "--json"])

    output = f.getvalue()
    # La derniere ligne non vide est le JSON (indent=2, donc multi-lignes)
    # Trouver le debut du bloc JSON (ligne qui commence par "{")
    lines = output.strip().split("\n")
    json_start = None
    for i, l in enumerate(lines):
        if l.strip().startswith("{"):
            json_start = i
            break
    assert json_start is not None, f"Pas de JSON dans la sortie: {output!r}"
    # Reconstruire le bloc JSON complet (peut etre multi-lignes)
    json_str = " ".join(lines[json_start:])
    data = json.loads(json_str)
    assert "campaign_id" in data
    assert data["campaign_id"] == correlation_id
    assert code == 0


def test_cli_non_json_output(mock_golden_file: Path):
    """Sortie text normale (pas --json)."""
    import io
    from contextlib import redirect_stdout
    from ingestor.regression import RegressionResult, main as regression_main
    from datetime import datetime, timezone

    correlation_id = "test-002"

    def mock_run_camp(golden_path, env):
        per_question = [
            {"id": "q1", "recall": 1.0, "hits": 1, "expected": ["Base.Axe"], "missing": [], "question": "What is an axe?"},
        ]
        return RegressionResult(
            campaign_id=correlation_id, env=env, game_version="b41",
            timestamp=datetime.now(timezone.utc).isoformat(), total_questions=1,
            passed_questions=1, failed_questions=0, avg_recall=1.0,
            min_recall=1.0, per_question=per_question, baseline_file=None,
        )

    f = io.StringIO()
    with patch("ingestor.regression._run_campaign", mock_run_camp):
        with redirect_stdout(f):
            code = regression_main(["--golden", str(mock_golden_file)])

    assert "[Regression]" in f.getvalue()
    assert code == 0


def test_cli_invalid_env():
    """--env invalide → SystemExit (argparse choices)."""
    import sys
    from ingestor.regression import main

    with pytest.raises(SystemExit, match="2"):
        main(["--env", "invalid"])


def test_cli_nonexistent_golden(tmp_path: Path):
    """Fichier golden inexistant → return 1."""
    from ingestor.regression import main

    code = main(["--golden", str(tmp_path / "nope.json")])
    assert code == 1


# ===========================================================================
# Tests edge cases
# ===========================================================================


def test_empty_expected_ids(mock_golden_file: Path, tmp_path: Path):
    """expected_ids vide → recall=1.0 (pas d'items attendus = tout passe)."""
    from ingestor.regression import _run_campaign

    questions = [{"id": "q-no-expected", "question": "Q?", "expected_ids": [], "filter": {}}]
    f = tmp_path / "empty_expected.json"
    f.write_text(json.dumps(questions))

    with patch("src.retrieval.query_staging", return_value={"chunks": []}):
        result = _run_campaign(f, env="staging")

    assert len(result.per_question) == 1


def test_mixed_versions_in_golden(mock_golden_file: Path):
    """Golden set avec B41 + B42 → game_version='b41' (majority)."""
    from ingestor.regression import _run_campaign

    # 3x b41 + 1x b42 → Counter most_common = b41
    questions = [
        {"id": "b41-1", "question": "Q?", "expected_ids": ["x"], "filter": {"version": "b41"}},
        {"id": "b41-2", "question": "Q?", "expected_ids": ["y"], "filter": {"version": "b41"}},
        {"id": "b41-3", "question": "Q?", "expected_ids": ["z"], "filter": {"version": "b41"}},
        {"id": "b42-1", "question": "Q?", "expected_ids": ["w"], "filter": {"version": "b42"}},
    ]
    tmp = mock_golden_file.parent / "mixed.json"
    tmp.write_text(json.dumps(questions))

    with patch("src.retrieval.query_staging", return_value={"chunks": [{"id": "x"}]}):
        result = _run_campaign(tmp, env="staging")

    assert result.game_version == "b41"


def test_production_env_client(mock_golden_file: Path):
    """--env production utilise get_production_client()."""
    from ingestor.regression import _run_campaign

    # mock_golden_file a 2 questions → query appelee 2 fois
    mock_chroma = MagicMock()
    mock_storage_client.query.return_value = {"chunks": [{"id": "Base.Axe"}]}

    with patch("src.retrieval.get_production_client", return_value=mock_chroma):
        result = _run_campaign(mock_golden_file, env="production")

    assert mock_storage_client.query.call_count == 2
