"""test_incremental_ingest — Tests du pipeline d'ingestion incrementale par hash.

Couvre :
  - _HashIndex load/save (persist + rechargement)
  - IngestionEngine._file_sha256 (hashing correct de fichiers)
  - ingest_directory() gate SHA-256 (skip files, process new/modified)
  - Edge cases: empty quarantine, missing hash file, corrupt index lines
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def sample_text_file(tmp_path: Path):
    """Fichier temporaire avec contenu previsible."""
    f = tmp_path / "test.txt"
    f.write_text("Bonjour monde — texte de test pour l'ingestion incrementale.", encoding="utf-8")
    return f


@pytest.fixture()
def sample_dir():
    """Repertoire temporaire isole avec 3 fichiers (ne contient PAS .seen_hashes)."""
    td = tempfile.mkdtemp(prefix="zombie_sample_")
    sd = Path(td)
    for name, content in [
        ("a.txt", "Contenu du fichier A"),
        ("b.md", "# Markdown\n\nLigne de test\n"),
        ("c.json", '{"cle": "valeur"}'),
    ]:
        (sd / name).write_text(content, encoding="utf-8")
    yield sd
    shutil.rmtree(td)


@pytest.fixture()
def quarantine_dir(tmp_path: Path):
    """Repertoire de quarantaine temporaire ( .seen_hashes vierge )."""
    qd = tmp_path / "quarantine_store"
    qd.mkdir(parents=True)
    (qd / ".seen_hashes").write_text("", encoding="utf-8")  # fichier vide par defaut
    return qd


# ===========================================================================
# Fixture partagée : nettoie le default .seen_hashes entre chaque test
# ===========================================================================


@pytest.fixture(autouse=True)
def _clear_default_seen(monkeypatch: pytest.MonkeyPatch):
    """Nettoie le fichier .seen_hashes du path PAR DEFAUT AVANT chaque test.

    get_quarantine_path() NE lit PAS QUARANTINE_PATH — c'est un argument Python.
    Donc monkeypatch.setenv ne fait RIEN. Le nettoyage se fait sur le defaut data/quarantine/.
    """
    default_q = Path("data") / "quarantine"
    seen = default_q / ".seen_hashes"
    if seen.exists():
        try:
            seen.unlink()
        except OSError:
            pass


def _quarantine_patch(monkeypatch: pytest.MonkeyPatch, qdir: Path):
    """Remplace get_quarantine_path par qdir pendant tout le reste du test.

    get_quarantine_path() NE lit PAS les env vars — il faut patcher la fonction elle-meme.
    Ce helper utilise monkeypatch.object qui persiste jusqu'a la teardown du test.
    """
    from ingestor.quarantine_manager import get_quarantine_path

    def _make_return(q: Path):
        target = q
        def _inner(data_root=None):
            return target
        return _inner

    monkeypatch.setattr(get_quarantine_path.__module__ + ".get_quarantine_path",
                        _make_return(qdir))


# ===========================================================================
# Tests : _HashIndex load/save
# ===========================================================================


# ===========================================================================
# Tests : _HashIndex load/save
# ===========================================================================


def test_hash_index_load_empty(quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Charger un index vide retourne un dictionnaire vide."""
    from ingestor.engine import _HashIndex

    (quarantine_dir / ".seen_hashes").write_text("", encoding="utf-8")
    _quarantine_patch(monkeypatch, quarantine_dir)

    index = _HashIndex.load()
    assert index == {}


def test_hash_index_load_with_entries(quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Charger un index avec des lignes retourne les paires hash→source."""
    from ingestor.engine import _HashIndex

    lines = "abc123  /path/to/file1.txt\ndef456  /path/to/file2.md\n"
    (quarantine_dir / ".seen_hashes").write_text(lines, encoding="utf-8")
    _quarantine_patch(monkeypatch, quarantine_dir)

    index = _HashIndex.load()
    assert len(index) == 2
    assert index["abc123"] == "/path/to/file1.txt"
    assert index["def456"] == "/path/to/file2.md"


def test_hash_index_load_skips_comments_and_empty(quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Les lignes de commentaire et vides sont ignorees."""
    from ingestor.engine import _HashIndex

    content = "# This is a comment\n\nabc123  /path/to/file.txt\n   \ndef456  /path/to/other.md\n"
    (quarantine_dir / ".seen_hashes").write_text(content, encoding="utf-8")
    _quarantine_patch(monkeypatch, quarantine_dir)

    index = _HashIndex.load()
    assert len(index) == 2


def test_hash_index_save_and_reload(quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Sauvegarder puis recharger → meme donnees."""
    from ingestor.engine import _HashIndex

    original = {"hashAAA": "/aaa.txt", "hashBBB": "/bbb.md"}
    (quarantine_dir / ".seen_hashes").write_text("", encoding="utf-8")  # clear first
    _quarantine_patch(monkeypatch, quarantine_dir)
    _HashIndex.save(original)
    reloaded = _HashIndex.load()

    assert reloaded == original


def test_hash_index_save_creates_file(tmp_path: Path, quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Le fichier .seen_hashes est cree s'il n'existe pas."""
    from ingestor.engine import _HashIndex

    hash_file = quarantine_dir / ".seen_hashes"
    if hash_file.exists():
        hash_file.unlink()

    _quarantine_patch(monkeypatch, quarantine_dir)
    _HashIndex.save({"h1": "/s"})
    assert (quarantine_dir / ".seen_hashes").exists()


# ===========================================================================
# Tests : _file_sha256
# ===========================================================================


def test_file_sha256_correct(sample_text_file: Path):
    """Le SHA-256 correspond a celui de hashlib standard."""
    from ingestor.engine import IngestionEngine

    computed = IngestionEngine._file_sha256(sample_text_file)
    expected = hashlib.sha256(sample_text_file.read_bytes()).hexdigest()
    assert computed == expected


def test_file_sha256_deterministic(sample_text_file: Path):
    """Meme fichier → meme hash a chaque appel."""
    from ingestor.engine import IngestionEngine

    h1 = IngestionEngine._file_sha256(sample_text_file)
    h2 = IngestionEngine._file_sha256(sample_text_file)
    assert h1 == h2
    assert len(h1) == 64


def test_file_sha256_different_content(tmp_path: Path):
    """Contenu different → hash different."""
    from ingestor.engine import IngestionEngine

    f1 = tmp_path / "a.txt"
    f1.write_text("contenu un", encoding="utf-8")
    f2 = tmp_path / "b.txt"
    f2.write_text("contenu deux", encoding="utf-8")

    h1 = IngestionEngine._file_sha256(f1)
    h2 = IngestionEngine._file_sha256(f2)
    assert h1 != h2


def test_file_sha256_missing_returns_empty():
    """Fichier inexistant → hash vide (pas d'exception)."""
    from ingestor.engine import IngestionEngine

    result = IngestionEngine._file_sha256(Path("/this/does/not/exist.txt"))
    assert result == ""


def test_file_sha256_large_file(tmp_path: Path):
    """Un fichier volumineux est hashé correctement (lecture par blocs)."""
    from ingestor.engine import IngestionEngine

    large_file = tmp_path / "big.bin"
    data = b"x" * (1024 * 1024)
    large_file.write_bytes(data)

    computed = IngestionEngine._file_sha256(large_file)
    expected = hashlib.sha256(data).hexdigest()
    assert computed == expected


# ===========================================================================
# Tests : ingest_directory avec gate SHA-256
# ===========================================================================


async def test_ingest_directory_detects_unchanged_files(
    sample_dir: Path, quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Fichiers dont le hash correspond sont ignores."""
    from ingestor.engine import _HashIndex, IngestionEngine

    file_hashes = {}
    for f in sample_dir.glob("*"):
        h = IngestionEngine._file_sha256(f)
        file_hashes[f] = h

    seen_index: dict[str, str] = {}
    seen_index.update((h, str(f)) for f, h in file_hashes.items())
    _quarantine_patch(monkeypatch, quarantine_dir)
    _HashIndex.save(seen_index)

    engine = IngestionEngine()
    results = await engine.ingest_directory(str(sample_dir))

    assert len(results) == 0


async def test_ingest_directory_processes_new_file(
    sample_dir: Path, quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Un fichier non present dans l'index est detecte.

    Les 3 fichiers existants sont deja indexes (hash correct dans .seen_hashes),
    donc seul le nouveau z_new.txt doit etre ingere.
    """
    from ingestor.engine import _HashIndex, IngestionEngine

    # Preparer l'index avec les hashes des 3 fichiers existants
    file_hashes = {}
    for f in sample_dir.glob("*"):
        h = IngestionEngine._file_sha256(f)
        file_hashes[f] = h

    _quarantine_patch(monkeypatch, quarantine_dir)
    _HashIndex.save({h: str(f) for f, h in file_hashes.items()})

    # Ajouter le nouveau fichier (non presente dans l'index)
    new_file = sample_dir / "z_new.txt"
    new_file.write_text("Nouveau fichier!", encoding="utf-8")

    engine = IngestionEngine()
    results = await engine.ingest_directory(str(sample_dir))
    assert len(results) == 1


async def test_ingest_directory_detects_modified_file(
    sample_dir: Path, quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Un fichier modifie (hash different) est re-traite."""
    from ingestor.engine import _HashIndex, IngestionEngine

    file_a = sample_dir / "a.txt"
    fake_hash = hashlib.sha256(b"fake content").hexdigest()

    _quarantine_patch(monkeypatch, quarantine_dir)
    _HashIndex.save({fake_hash: str(file_a)})  # only a.txt has a (fake) hash

    engine = IngestionEngine()
    results = await engine.ingest_directory(str(sample_dir))
    assert len(results) == 3


async def test_ingest_directory_updates_index_on_success(
    sample_dir: Path, quarantine_dir: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Apres traitement reussi, le hash est ajoute a .seen_hashes."""
    from ingestor.engine import _HashIndex, IngestionEngine

    _quarantine_patch(monkeypatch, quarantine_dir)
    _HashIndex.save({})  # empty → all files processed

    engine = IngestionEngine()
    await engine.ingest_directory(str(sample_dir))

    updated_index = _HashIndex.load()
    assert len(updated_index) > 0


def test_ingest_directory_empty():
    """Repertoire vide → retourne [] (pas d'erreur)."""
    from ingestor.engine import IngestionEngine

    engine = IngestionEngine()
    results = asyncio_run(engine.ingest_directory(Path("/tmp/empty_dir_xyz")))
    assert len(results) == 0


def test_hash_index_load_nonexistent_file():
    """Charger un index inexistante → {} (pas d'erreur)."""
    from ingestor.engine import _HashIndex

    with patch("ingestor.quarantine_manager.get_quarantine_path", return_value=Path("/nonexistent/xyz")):
        index = _HashIndex.load()

    assert index == {}


def test_hash_index_load_corrupted_lines(tmp_path: Path):
    """Les lignes corrompues (1 champ) sont ignorees."""
    from ingestor.engine import _HashIndex

    qd = tmp_path / "q"
    qd.mkdir(parents=True)
    content = "abc123  /valid/path\ncorrupted_line_no_space\n"
    (qd / ".seen_hashes").write_text(content, encoding="utf-8")

    with patch("ingestor.quarantine_manager.get_quarantine_path", return_value=qd):
        index = _HashIndex.load()

    assert len(index) == 1


# ===========================================================================
# Helpers
# ===========================================================================


def asyncio_run(coro):
    """Executer une coroutine async."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return coro
    return asyncio.run(coro)
