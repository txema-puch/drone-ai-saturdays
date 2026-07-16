"""Temporary module alias; removed before the restructure PR merges."""

import sys

from sadar.releases import approach as _implementation

sys.modules[__name__] = _implementation
