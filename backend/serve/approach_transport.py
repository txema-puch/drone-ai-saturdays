"""Temporary module alias; removed before the restructure PR merges."""

import sys

from sadar.releases import archive as _implementation

sys.modules[__name__] = _implementation
