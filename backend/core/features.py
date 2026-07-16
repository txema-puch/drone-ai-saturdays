"""Temporary module alias; removed before the restructure PR merges."""
import sys
from sadar_research.trajectory_anomaly.pipeline import features as _implementation
sys.modules[__name__] = _implementation
