"""Temporary module alias; removed before the restructure PR merges."""
import os
import sys
from pathlib import Path

_repository = Path(__file__).resolve().parents[2]
os.environ.setdefault(
    "SADAR_RESEARCH_BUNDLE_DIR",
    str(_repository / "backend/models/sadar_demo"),
)
os.environ.setdefault(
    "SADAR_RESEARCH_MODELS_DIR",
    str(_repository / "backend/models/phase6"),
)
os.environ.setdefault("SADAR_FRONTEND_DIR", str(_repository / "frontend/dist"))

from sadar_research.trajectory_anomaly.demo import app as _implementation
sys.modules[__name__] = _implementation
