"""Runner for pytest — patches wcwidth before import, then runs pytest."""

import sys
from pathlib import Path

# Patch wcwidth BEFORE any pytest module imports it.
try:
    from _pytest._io import wcwidth as _wcmod
    _orig = _wcmod.wcswidth
    def _safe(s):
        try:
            return _orig(s)
        except (ValueError, TypeError, UnicodeError):
            return len(s)
    _wcmod.wcswidth = _safe
except Exception:
    pass

# Now import and run pytest.
from _pytest.config import main as _pytest_main

sys.exit(_pytest_main(sys.argv[1:]))
