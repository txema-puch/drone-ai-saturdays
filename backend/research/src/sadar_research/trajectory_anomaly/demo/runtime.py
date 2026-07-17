"""Frozen-model lifecycle and shared non-queueing analysis admission.

    not_loaded --prepare--> loading --success--> ready
                              |                 |
                              +--failure--> failed --one retry--> loading

Simulation and uploaded evaluation share the same single analysis slot.  A caller
either owns it immediately or receives a bounded busy response; work is never queued.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import Lock, Thread
from typing import Any, Callable, Iterator


logger = logging.getLogger(__name__)


class AnalysisBusy(RuntimeError):
    """The process-wide analysis slot is already owned."""


class ModelNotReady(RuntimeError):
    """The frozen model has not completed a successful preparation."""


class ModelRuntime:
    MAX_ATTEMPTS = 2

    def __init__(self, loader: Callable[[], Any]) -> None:
        self._loader = loader
        self._state_lock = Lock()
        self._analysis_lock = Lock()
        self._state = "not_loaded"
        self._attempts = 0
        self._loaded: Any | None = None

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def retry_remaining(self) -> int:
        with self._state_lock:
            return self._retry_remaining_unlocked()

    @property
    def loaded(self) -> Any:
        with self._state_lock:
            if self._state != "ready" or self._loaded is None:
                raise ModelNotReady("model is not ready")
            return self._loaded

    def snapshot(self) -> dict[str, int | str]:
        with self._state_lock:
            return {
                "model_state": self._state,
                "model_retry_remaining": self._retry_remaining_unlocked(),
            }

    def prepare(self) -> dict[str, int | str]:
        """Start the initial load or sole retry and return immediately."""
        with self._state_lock:
            if self._state in ("loading", "ready"):
                return self.snapshot_unlocked()
            if self._attempts >= self.MAX_ATTEMPTS:
                return self.snapshot_unlocked()
            self._attempts += 1
            self._state = "loading"
            snapshot = self.snapshot_unlocked()
        Thread(target=self._load, name="sadar-model-prepare", daemon=True).start()
        return snapshot

    def snapshot_unlocked(self) -> dict[str, int | str]:
        return {
            "model_state": self._state,
            "model_retry_remaining": self._retry_remaining_unlocked(),
        }

    def _retry_remaining_unlocked(self) -> int:
        if self._state == "ready":
            return 0
        return max(0, self.MAX_ATTEMPTS - max(1, self._attempts))

    def _load(self) -> None:
        try:
            loaded = self._loader()
        except Exception:
            logger.exception("Frozen model preparation failed")
            with self._state_lock:
                self._loaded = None
                self._state = "failed"
            return
        with self._state_lock:
            self._loaded = loaded
            self._state = "ready"

    @contextmanager
    def analysis(self) -> Iterator[Any]:
        """Own the shared slot for the complete synchronous analysis lifetime."""
        if not self._analysis_lock.acquire(blocking=False):
            raise AnalysisBusy("analysis is busy")
        try:
            yield self.loaded
        finally:
            self._analysis_lock.release()
