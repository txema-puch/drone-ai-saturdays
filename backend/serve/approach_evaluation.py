"""Temporary module alias; removed before the restructure PR merges."""

import sys

from sadar.api import evaluation as _implementation

sys.modules[__name__] = _implementation
