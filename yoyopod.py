#!/usr/bin/env python3
"""Top-level launcher and import shim for the src-based YoyoPod package."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "yoyopod"
PACKAGE_INIT = PACKAGE_ROOT / "__init__.py"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

if __name__ == "__main__":
    from yoyopod.main import main

    raise SystemExit(main())

# When the repo root is on sys.path, this file shadows the src package name.
# Execute the real package __init__ into this module so imports keep working.
__file__ = str(PACKAGE_INIT)
__path__ = [str(PACKAGE_ROOT)]

with PACKAGE_INIT.open("rb") as handle:
    exec(compile(handle.read(), __file__, "exec"), globals(), globals())
