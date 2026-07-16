"""Temporary module alias; removed before the restructure PR merges."""

import sys

from sadar.approach import reference as _implementation

sys.modules[__name__] = _implementation
