"""tests/test_tag_release.py — Tests du script de release tagging.

Couvre :
  - SemVer.from_string / __str__ / bump()
  - read_version / write_version (mocked file)
  - generate_changelog depuis des commits
  - _is_release_commit filtering
  - do_release flow avec git mock
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Tests : SemVer
# ===========================================================================


def test_semver_from_string_basic():
    """Parse '0.3.0' → SemVer(0, 3, 0)."""
    from ingestor.tag_release import SemVer

    v = SemVer.from_string("0.3.0")
    assert v.major == 0
    assert v.minor == 3
    assert v.patch == 0
    assert v.pre is None


def test_semver_from_string_with_prerelease():
    """Parse '1.0.0-alpha' → SemVer(1, 0, 0, 'alpha')."""
    from ingestor.tag_release import SemVer

    v = SemVer.from_string("1.0.0-beta.rc.2")
    assert v.major == 1
    assert v.minor == 0
    assert v.patch == 0
    assert v.pre == "beta.rc.2"


def test_semver_str_format():
    """__str__ → '0.3.0' / '1.0.0-alpha'."""
    from ingestor.tag_release import SemVer

    assert str(SemVer(0, 3, 0)) == "0.3.0"
    assert str(SemVer(1, 0, 0, "alpha")) == "1.0.0-alpha"


def test_semver_bump_major():
    """Bump major : 0.3.0 → 1.0.0 (reset pre)."""
    from ingestor.tag_release import SemVer

    v = SemVer(0, 3, 0)
    next_v = v.bump("major")
    assert next_v == SemVer(1, 0, 0, None)


def test_semver_bump_minor():
    """Bump minor : 0.3.0 → 0.4.0 (reset pre)."""
    from ingestor.tag_release import SemVer

    v = SemVer(0, 3, 0)
    next_v = v.bump("minor")
    assert next_v == SemVer(0, 4, 0, None)


def test_semver_bump_patch():
    """Bump patch : 0.3.0 → 0.3.1."""
    from ingestor.tag_release import SemVer

    v = SemVer(0, 3, 0)
    next_v = v.bump("patch")
    assert next_v == SemVer(0, 3, 1)


def test_semver_invalid_string():
    """Chaine invalide → ValueError."""
    from ingestor.tag_release import SemVer

    with pytest.raises(ValueError, match="Invalid version string"):
        SemVer.from_string("not-a-version")


# ===========================================================================
# Tests : read_version / write_version (mocked)
# ===========================================================================


def test_write_and_read_version(mock_golden_file: Path):
    """Ecrire '1.2.3' puis relire → 1.2.3."""
    import ingestor.tag_release as tr
    from ingestor.tag_release import SemVer

    # Mock la version file avec un tmpfile
    tmp = mock_golden_file.parent / "VERSION_test"
    tmp.write_text("0.5.0\n")

    with patch.object(tr, "VERSION_FILE", tmp):
        v = tr.read_version()
        assert str(v) == "0.5.0"

        tr.write_version(SemVer(1, 2, 3))
        v2 = tr.read_version()
        assert str(v2) == "1.2.3"


# ===========================================================================
# Tests : _is_release_commit
# ===========================================================================


def test_is_release_commit_matches():
    """Les commits de release sont detectes."""
    from ingestor.tag_release import _is_release_commit

    assert _is_release_commit("release: v0.3.0") is True
    assert _is_release_commit("version bump 1.0.0") is True


def test_is_release_commit_normal():
    """Les commits normaux ne sont PAS detectes comme release."""
    from ingestor.tag_release import _is_release_commit

    assert _is_release_commit("feat: add search command") is False
    assert _is_release_commit("fix: typo in README") is False


# ===========================================================================
# Tests : generate_changelog
# ===========================================================================


def test_generate_changelog_groups_by_type():
    """Les commits sont groupes par type conventional commit."""
    from ingestor.tag_release import generate_changelog

    commits = [
        {"hash": "abc", "message": "feat: new command /auth", "author": "mat", "date": "2026-07-04"},
        {"hash": "def", "message": "fix: crash on parse", "author": "elchibros", "date": "2026-07-03"},
        {"hash": "ghi", "message": "docs: update README", "author": "mat", "date": "2026-07-02"},
    ]

    output = generate_changelog(commits)

    # Verifier que chaque section est presente — utiliser des substrings robustes
    assert "Nouvelles" in output and "fonction" in output
    assert "Corrections" in output and "bugs" in output
    assert "Documentation" in output


def test_generate_changelog_excludes_release_commits():
    """Les commits release sont ignores du changelog."""
    from ingestor.tag_release import generate_changelog

    commits = [
        {"hash": "abc", "message": "release: v0.3.0", "author": "mat", "date": "2026-07-04"},
        {"hash": "def", "message": "feat: new feature", "author": "elchibros", "date": "2026-07-03"},
    ]

    output = generate_changelog(commits)
    assert "release:" not in output


# ===========================================================================
# Tests : do_release (mocked git)
# ===========================================================================


def test_do_release_full_flow(mock_golden_file: Path, tmp_path: Path):
    """Flux complet : bump → commit → tag → backup."""
    import ingestor.tag_release as tr

    # Mock VERSION file avec un tmpfile
    ver_file = tmp_path / "VERSION"
    ver_file.write_text("0.3.0\n")

    # Mock git pour eviter les vraies operations
    mock_git = MagicMock(return_value="v0.3.0")

    with patch.object(tr, "VERSION_FILE", ver_file):
        with patch.object(tr, "_git", mock_git):
            with patch.object(tr, "create_backup", return_value=Path()):
                info = tr.do_release(version_part="minor", no_push=True)

    assert info["new_version"] == "0.4.0"
    # Verifier que git add + commit + tag ont été appelés
    assert mock_git.call_count >= 3


def test_do_release_explicit_version(mock_golden_file: Path, tmp_path: Path):
    """Version explicite ignore bump major/minor."""
    import ingestor.tag_release as tr

    ver_file = tmp_path / "VERSION"
    ver_file.write_text("0.9.9\n")

    mock_git = MagicMock(return_value="")

    with patch.object(tr, "VERSION_FILE", ver_file):
        with patch.object(tr, "_git", mock_git):
            with patch.object(tr, "create_backup", return_value=Path()):
                info = tr.do_release(explicit_version="1.0.0-alpha", no_push=True)

    assert info["new_version"] == "1.0.0-alpha"


def test_do_release_changelog_only(mock_golden_file: Path):
    """--changelog-only ne fait PAS de commit ni tag."""
    import ingestor.tag_release as tr

    ver_content = "0.3.0\n"
    ver_file = mock_golden_file.parent / "VERSION_co"
    ver_file.write_text(ver_content)

    # get_last_tag() appelle _git("describe --tags") → si mock retourne une string,
    # last_tag n'est plus None et get_commits_since_tag est appele.
    # Donc on mock get_last_tag pour retourner None (pas de tag preexistant).
    with patch.object(tr, "VERSION_FILE", ver_file):
        with patch.object(tr, "get_last_tag", return_value=None):
            info = tr.do_release(changelog_only=True)

    # Aucun git call, pas de version modifiee
    assert info["new_version"] is None
    assert info["last_tag"] is None


# ===========================================================================
# Tests : get_commits_since_tag
# ===========================================================================


def test_get_commits_since_tag_format():
    """Les commits retournes ont les bons champs."""
    import ingestor.tag_release as tr

    fake_output = "abc123\nfeat: add feature\nmat\n2026-07-04T00:00:00+00:00\n---COMMIT_SEP---\ndef456\nfix: typo\nelchibros\n2026-07-03T00:00:00+00:00\n---COMMIT_SEP---\n"

    with patch.object(tr, "_git", return_value=fake_output):
        commits = tr.get_commits_since_tag(None)

    assert len(commits) == 2
    assert commits[0]["message"] == "feat: add feature"
    assert commits[1]["hash"] == "def456"[:8]


# ===========================================================================
# Helpers
# ===========================================================================


@pytest.fixture()
def mock_golden_file(tmp_path: Path):
    """Fichier golden temporaire pour tests tag_release (utilise par d'autres modules)."""
    f = tmp_path / "golden_test.json"
    f.write_text("[]", encoding="utf-8")
    return f
