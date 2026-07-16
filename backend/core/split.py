"""Temporary module alias; removed before the restructure PR merges."""
import sys
from sadar_research.trajectory_anomaly.pipeline import split as _implementation
sys.modules[__name__] = _implementation
