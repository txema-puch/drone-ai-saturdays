"""Pytest bootstrap for the backend test-suite.

Puts the repo root on `sys.path` so `import backend.core.preprocessing` resolves
via the namespace package (there are no `__init__.py` files, by project
convention). Importing `backend.core.*` must not require `.env` — that is exactly
why the geo/derivation helpers were extracted out of `crud.opensky` (refactor A1).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests/ -> backend/ -> repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
