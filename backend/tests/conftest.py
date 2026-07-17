"""Explicit local fixtures for product and historical-research tests."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests/ -> backend/ -> repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The historical demonstration deliberately has no repository-relative runtime
# defaults. Tests opt into the checked-in fixtures explicitly.
os.environ.setdefault(
    "SADAR_RESEARCH_BUNDLE_DIR",
    str(REPO_ROOT / ".artifacts/trajectory-demo"),
)
os.environ.setdefault(
    "SADAR_RESEARCH_MODELS_DIR",
    str(REPO_ROOT / ".artifacts/trajectory-training"),
)
os.environ.setdefault("SADAR_FRONTEND_DIR", str(REPO_ROOT / "frontend/dist"))
