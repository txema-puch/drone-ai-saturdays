"""Temporary module alias; removed before the restructure PR merges."""
import sys
from sadar_research.trajectory_anomaly.data import opensky as _implementation
sys.modules[__name__] = _implementation
