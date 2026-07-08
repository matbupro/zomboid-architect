#!/usr/bin/env python3 -u
"""
run_full_tests -- Execute ALL test suites + full log to file.

KEY DESIGN: subprocess output is written to temp files (not PIPE buffers),
so there's NO deadlock when pytest produces lots of output.
Everything appears in the log immediately, survives console crash.

USAGE:
    python scripts/run_full_tests.py                     # tout tester
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess as sp
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


# ── Setup ────────────────────────────────────────────────────────
REPO_ROOT  = str(Path(__file__).resolve().parent.parent)
LOG_DIR    = os.path.join(REPO_ROOT, ".test_output")
os.makedirs(LOG_DIR, exist_ok=True)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(LOG_DIR, "full_test_" + ts + ".log")

fh = open(log_file, "w", encoding="utf-8")


def W(text):
    """Write to BOTH console AND log — ALWAYS flushed."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except Exception:
        pass
    try:
        fh.write(text + "\n")
        fh.flush()
    except Exception:
        pass


# ── Header (always visible immediately) ──────────────────────────
W("=" * 60)
W("  Zomboid_Architect -- Full Test Suite")
W("=" * 60)
W("\n[LOG] " + log_file)
W("\n--- Diagnostics ---")
W("Python:      " + sys.executable)
W("CWD:         " + os.getcwd())
W("Repo root:   " + REPO_ROOT)
W("Log file:    " + log_file)

# Check pytest importable in THIS python
r = sp.run(
    [sys.executable, "-c", "import pytest; print('pytest', pytest.__version__)"],
    cwd=REPO_ROOT, stdout=sp.PIPE, stderr=sp.PIPE, timeout=10,
)
stdout_text = (r.stdout or b"").decode("utf-8", errors="replace")
stderr_text = (r.stderr or b"").decode("utf-8", errors="replace")
W("pytest:      " + (stdout_text.strip() or stderr_text.strip()))

tests_dir = os.path.join(REPO_ROOT, "tests")
if os.path.isdir(tests_dir):
    W("tests/:      {} files".format(len(os.listdir(tests_dir))))
else:
    W("tests/:      MISSING at " + tests_dir)

for cfg_name in ("pytest.ini", "pyproject.toml"):
    cfg_path = os.path.join(REPO_ROOT, cfg_name)
    if os.path.isfile(cfg_path):
        W("{}:         {} bytes".format(cfg_name, os.path.getsize(cfg_path)))

W("--- Diagnostics complete ---\n")


def run_step(label, cmd_str, timeout=300):
    """Run a step. Output written to temp files (not PIPE) — no buffer deadlock."""
    global total_exit

    W("\n" + "=" * 60)
    W("STEP: " + label)
    W("CMD:  " + cmd_str)
    W("=" * 60)
    sys.stdout.flush()

    start = time.time()

    # Create temp files in LOG_DIR so they survive even if CWD is wrong
    with tempfile.TemporaryDirectory(prefix="ztest_", dir=LOG_DIR) as tmpdir:
        out_file = os.path.join(tmpdir, "out.txt")
        err_file = os.path.join(tmpdir, "err.txt")

        # Open files for binary write — no encoding issues
        stdout_fh  = open(out_file, "wb")
        stderr_fh  = open(err_file, "wb")

        try:
            proc = sp.Popen(
                cmd_str,
                shell=True,
                cwd=REPO_ROOT,
                stdin=sp.DEVNULL,
                stdout=stdout_fh,   # ← direct file write — no PIPE buffer!
                stderr=stderr_fh,
            )

            # Wait with timeout — poll every 200ms
            while proc.poll() is None:
                elapsed = time.time() - start
                if elapsed > timeout:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                time.sleep(0.2)

        finally:
            stdout_fh.close()
            stderr_fh.close()

        elapsed = time.time() - start

        # Now read both files (already on disk — complete, safe)
        try:
            out_content  = open(out_file).read()
        except Exception:
            out_content = ""
        try:
            err_content  = open(err_file).read()
        except Exception:
            err_content = ""

        # Write to console AND log file
        W(out_content)
        if err_content:
            W(err_content)

        nbytes = len(out_content) + len(err_content)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        W("\n[{}] {} — exit={}, {:.1f}s, {} bytes\n".format(
            status, label, proc.returncode, elapsed, nbytes))
        sys.stdout.flush()

        total_exit |= proc.returncode or 0


# ── Main ─────────────────────────────────────────────────────────
total_exit = 0

parser = argparse.ArgumentParser()
parser.add_argument("pytest_filter", nargs="?", default="", help="Extra pytest filter")
parser.add_argument("--dry", action="store_true")
args = parser.parse_args()

if args.dry:
    W("[DRY RUN — no tests executed]\n")
else:
    # Step 1: pytest
    pf = shlex.split(args.pytest_filter) if args.pytest_filter else []
    cmd1 = '{} -m pytest {} --tb=long -v'.format(sys.executable, " ".join(pf))
    run_step("pytest (unit + integration)", cmd1, timeout=600)

    # Step 2: run_tests.py
    cmd2 = '"{}" tests/run_tests.py all'.format(sys.executable)
    run_step("run_tests_py", cmd2, timeout=120)

    # Step 3: golden set
    cmd3 = '"{}" tests/test_golden_set.py -v'.format(sys.executable)
    run_step("golden_set", cmd3, timeout=120)

    # Step 4: regression
    cmd4 = '"{}" -m pytest tests/test_regression.py -v --tb=short'.format(sys.executable)
    run_step("regression", cmd4, timeout=120)

    # Step 5: modgen integration
    cmd5 = '"{}" -m pytest tests/test_modgen_integration.py -v --tb=short'.format(sys.executable)
    run_step("modgen_integration", cmd5, timeout=120)

# ── Summary ──────────────────────────────────────────────────────
W("\n" + "=" * 60)
if total_exit == 0:
    W("   ALL TESTS PASSED   ")
else:
    W("   EXIT CODE: {}   ".format(total_exit))
W("=" * 60)
W("Log file: " + log_file)

fh.flush()
fh.close()
sys.stdout.flush()
