"""Temporary module alias; removed before the restructure PR merges."""
import sys
from sadar_research.trajectory_anomaly.demo import runtime as _implementation
sys.modules[__name__] = _implementation
