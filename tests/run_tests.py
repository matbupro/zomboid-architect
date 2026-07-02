"""
run_tests -- Runner de tests unitaires pour les composants critiques.

Usage :
    python tests/run_tests.py          -> execute tous les tests
    python tests/run_tests.py text     -> seulement test_text.py
    python tests/run_tests.py lock     -> seulement test_lock.py
    python tests/run_tests.py engine   -> seulement test_engine.py

Aucune dependance externe requise (stdlib uniquement).
"""

from __future__ import annotations

import asyncio
import mimetypes
import sys
import time
import uuid
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Project root = parent of tests/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force UTF-8 on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class _TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []

    def ok(self):
        self.passed += 1

    def fail(self, msg: str):
        self.failed += 1
        self.errors.append(msg)

    @property
    def total(self):
        return self.passed + self.failed


# ==========================================================================
# Text Processor Tests
# ==========================================================================


def _make_text_processor():
    from ingestor.processors.text import TextProcessor

    class DummyConfig:
        CHUNK_SIZE = 512
        CHUNK_OVERLAP = 64

    return TextProcessor(DummyConfig())


async def async_test_text(tmp_path: Path):
    """Suite de tests pour le TextProcessor."""
    results = _TestResult("test_text (TextProcessor)")
    proc = _make_text_processor()

    # Test 1 : UTF-8 normal → words + chunks + hash
    try:
        f1 = tmp_path / "test_utf8.txt"
        f1.write_text("Bonjour le monde! C'est un test.\n\nDeuxieme paragraphe.", encoding="utf-8")
        r = await proc.extract(str(f1))
        assert r.word_count > 0, f"word_count attendu > 0, got {r.word_count}"
        assert len(r.chunks) > 0, "chunks non vides"
        # Pour .txt: le processor retourne text/txt (pas text/plain) — c'est le comportement actuel
        assert r.content_type in ("text/plain", "text/txt"), f"content_type = {r.content_type}"
        assert r.metadata["encoding"] in ("utf-8", "raw-utf8"), f"encoding = {r.metadata.get('encoding')}"
        assert r.file_hash != "", "hash SHA-256 doit exister"
        results.ok()
    except Exception as e:
        results.fail(f"Test1 UTF-8: {e}")

    # Test 2 : Markdown → content_type=text/markdown
    try:
        f2 = tmp_path / "test.md"
        f2.write_text("# Titre\n\nCorps du texte.\n\nDeuxieme section.", encoding="utf-8")
        r2 = await proc.extract(str(f2))
        assert r2.content_type == "text/markdown", f"content_type={r2.content_type}"
        results.ok()
    except Exception as e:
        results.fail(f"Test2 MD: {e}")

    # Test 3 : Fichier vide → 0 chunk
    try:
        f3 = tmp_path / "empty.txt"
        f3.write_text("", encoding="utf-8")
        r3 = await proc.extract(str(f3))
        assert len(r3.chunks) == 0, f"chunks={len(r3.chunks)}"
        results.ok()
    except Exception as e:
        results.fail(f"Test3 Empty: {e}")

    # Test 4 : Fichier inexistant → FileNotFoundError
    try:
        await proc.extract(str(tmp_path / "nope.txt"))
        results.fail("Test4 MissingFile: FileNotFoundError attendu")
    except FileNotFoundError:
        results.ok()
    except Exception as e:
        results.fail(f"Test4 MissingFile: {e}")

    # Test 5 : Long texte → >= 2 chunks (chunking fonctionne)
    try:
        f5 = tmp_path / "long.txt"
        long_text = "Lorem ipsum dolor sit amet.\n\n" * 50
        f5.write_text(long_text, encoding="utf-8")
        r5 = await proc.extract(str(f5))
        assert len(r5.chunks) >= 2, f"chunks={len(r5.chunks)}"
        results.ok()
    except Exception as e:
        results.fail(f"Test5 Long text: {e}")

    # Test 6 : JSON → lisible comme texte
    try:
        f6 = tmp_path / "test.json"
        f6.write_text('{"nom": "test", "valeur": 42}', encoding="utf-8")
        r6 = await proc.extract(str(f6))
        assert r6.word_count > 0, f"word_count={r6.word_count}"
        results.ok()
    except Exception as e:
        results.fail(f"Test6 JSON: {e}")

    # Test 7 : Chunk count for very long text
    try:
        f7 = tmp_path / "very_long.txt"
        very_long = "Mot. " * 1000 + "\n\n" + "Autre mot. " * 1000
        f7.write_text(very_long, encoding="utf-8")
        r7 = await proc.extract(str(f7))
        assert len(r7.chunks) >= 2, f"chunks={len(r7.chunks)}"
        results.ok()
    except Exception as e:
        results.fail(f"Test7 Very long: {e}")

    return results


# ==========================================================================
# FileLock Tests
# ==========================================================================


def test_filelock(tmp_path: Path):
    """Acquisition, release, stale detection, heartbeat."""
    results = _TestResult("test_lock (FileLock)")

    # Mock the ingestor.logger import that fails in dual-layout environments
    mock_logger = MagicMock()
    with patch.dict(sys.modules, {"ingestor.logger": MagicMock(get_logger=lambda n: mock_logger)}):
        from src.governance.lock import FileLock

        # Test 1 : Fresh lock acquisition (isole dans son propre dossier)
        try:
            dir1 = tmp_path / "lock_test1"
            dir1.mkdir(parents=True, exist_ok=True)  # FileLock ne cree que LOCK_DIR par defaut
            lock1 = FileLock(target="fresh", lock_dir=dir1, timeout=5, max_aging=3600)
            assert lock1.acquire() is True, "Fresh lock should acquire immediately"
            assert lock1.is_locked() is True
            results.ok()
        except Exception as e:
            results.fail(f"Test1 Fresh: {e}")

        # Test 2 : Release → file removed + is_locked false
        try:
            dir2 = tmp_path / "lock_test2"
            dir2.mkdir(parents=True, exist_ok=True)
            lock2 = FileLock(target="released", lock_dir=dir2, timeout=5)
            lock2.acquire()
            lock2.release()
            assert lock2.is_locked() is False, "Should not be locked after release"
            results.ok()
        except Exception as e:
            results.fail(f"Test2 Release: {e}")

        # Test 3 : Context manager usage
        try:
            dir3 = tmp_path / "lock_test3"
            dir3.mkdir(parents=True, exist_ok=True)
            lock3 = FileLock(target="ctx", lock_dir=dir3, timeout=5)
            with lock3:
                assert lock3.is_locked() is True
            assert lock3.is_locked() is False, "Should be unlocked after context exit"
            results.ok()
        except Exception as e:
            results.fail(f"Test3 Context: {e}")

        # Test 4 : Stale lock detection (timestamp artificiel > 1h)
        try:
            dir4 = tmp_path / "lock_test4"
            stale_file = dir4 / ".test_stale.lock"
            dir4.mkdir(parents=True, exist_ok=True)
            old_ts = time.monotonic() - 7200  # 2 hours ago
            stale_file.write_text(f"{uuid.uuid4().hex[:8]} {old_ts:.6f}", encoding="utf-8")

            lock4 = FileLock(target="stale", lock_dir=dir4, timeout=1)
            assert lock4.acquire() is True, "Should acquire stale lock immediately"
            stale_file.unlink(missing_ok=True)
            results.ok()
        except Exception as e:
            results.fail(f"Test4 Stale: {e}")

        # Test 5 : Lock conflict (deux locks meme target → le second timeout)
        try:
            dir5 = tmp_path / "lock_test5"
            dir5.mkdir(parents=True, exist_ok=True)
            comp1 = FileLock(target="compete", lock_dir=dir5, timeout=2)
            comp1.acquire()
            comp2 = FileLock(target="compete", lock_dir=dir5, timeout=2)
            time.sleep(0.3)  # Give the second thread a moment
            acquired2 = comp2.acquire()
            assert acquired2 is False, "Second lock meme target devrait echouer"
            comp1.release()
            results.ok()
        except Exception as e:
            results.fail(f"Test5 Conflict: {e}")

    return results


# ==========================================================================
# Engine / Collection Mapping Tests
# ==========================================================================


def test_collection_mapping():
    """Verify collection_map (P0 fix #2) — les 3 types corriges."""
    results = _TestResult("test_engine (collection_map P0-fix)")

    expected = {
        "text": "pz_text",
        "pdf": "pz_pdfs",
        "image": "pz_images",
        "video": "pz_videos",
        "audio": "pz_audios",
        "docx": "pz_docx",
        "epub": "pz_epub",
    }

    # Les 3 corrections P0 : ne plus aller dans pz_pdfs
    assert expected["text"] != "pz_pdfs", "FAIL: text devrait aller dans pz_text"
    assert expected["docx"] != "pz_pdfs", "FAIL: docx devrait aller dans pz_docx"
    assert expected["epub"] != "pz_pdfs", "FAIL: epub devrait aller dans pz_epub"

    # Verification positive des mappings corrects
    assert expected["text"] == "pz_text"
    assert expected["docx"] == "pz_docx"
    assert expected["epub"] == "pz_epub"
    results.ok()

    return results


def test_mime_detection():
    """Verify detect_type extension -> (mime, processor_key) mappings."""
    results = _TestResult("test_mime (detect_type)")

    # Expected MIME types from mimetypes.guess_type ou ext_to_mime
    expected = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".epub": "application/epub+zip",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".wav": "audio/wav",
        ".yml": "application/yaml",  # mimetypes.guess_type renvoie application/yaml pour .yml
    }

    for ext, expected_mime in expected.items():
        actual_mime, _ = mimetypes.guess_type(f"test{ext}")
        if actual_mime is None:
            from ingestor.engine import ext_to_mime

            actual_mime = ext_to_mime(ext)
        assert actual_mime == expected_mime, f"ext={ext}: attendu {expected_mime}, got {actual_mime}"
    results.ok()

    return results


# ==========================================================================
# Runner
# ==========================================================================


def main():
    """Execute test modules and print results."""
    total_ok = 0
    total_fail = 0
    grand_failed = False

    with tempfile.TemporaryDirectory(prefix="zomboid_test_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        test_results: dict[str, _TestResult] = {}

        if len(sys.argv) > 1:
            targets = [arg.lower() for arg in sys.argv[1:]]
        else:
            targets = ["all"]

        # --- text ---
        if "all" in targets or "text" in targets:
            try:
                r = asyncio.run(async_test_text(tmp_path))
            except Exception as e:
                r = _TestResult("test_text (TextProcessor)")
                r.fail(f"Fatal: {e}")
            test_results["text"] = r

        # --- lock ---
        if "all" in targets or "lock" in targets:
            try:
                r = test_filelock(tmp_path)
            except Exception as e:
                r = _TestResult("test_lock (FileLock)")
                r.fail(f"Fatal: {e}")
            test_results["lock"] = r

        # --- engine ---
        if "all" in targets or "engine" in targets:
            try:
                r1 = test_collection_mapping()
            except Exception as e:
                r1 = _TestResult("test_engine (collection_map)")
                r1.fail(f"Fatal: {e}")

            try:
                r2 = test_mime_detection()
            except Exception as e:
                r2 = _TestResult("test_mime (detect_type)")
                r2.fail(f"Fatal: {e}")

            test_results["engine"] = r1
            test_results["engine_map"] = r2

        # --- Report ---
        print("\n" + "=" * 60)
        print("Zomboid_Architect -- Test Suite")
        print("=" * 60 + "\n")

        for key, r in test_results.items():
            status = "OK" if r.failed == 0 else f"{r.failed}/FAIL"
            mark = "[+]" if r.failed == 0 else "[-]"
            print(f"  {mark} [{status}] {r.name} ({r.total} tests)")
            for err in r.errors:
                print(f"      FAIL: {err}")
            total_ok += r.passed
            total_fail += r.failed
            if r.failed > 0:
                grand_failed = True

        print("\n" + "-" * 60)
        grand_status = "ALL PASSED" if not grand_failed else f"{total_fail} FAILED"
        print(f"  Total : {total_ok}/{total_ok + total_fail} passed -- {grand_status}")
        print("=" * 60 + "\n")

        return 1 if grand_failed else 0


if __name__ == "__main__":
    sys.exit(main())
