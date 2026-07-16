"""Bounded upload transport and anonymous evaluation admission."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque


class UploadBodyTooLarge(Exception):
    pass


class UploadBodyTimeout(Exception):
    pass


class EvaluationBodyLimitMiddleware:
    """Bound upload bytes and idle/total receive time before multipart parsing."""

    def __init__(self, app, *, maximum: int, idle_seconds: float, total_seconds: float):
        self.app = app
        self.maximum = maximum
        self.idle_seconds = idle_seconds
        self.total_seconds = total_seconds

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/api/evaluations":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        received = 0

        async def bounded_receive():
            nonlocal received
            remaining = self.total_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise UploadBodyTimeout
            try:
                message = await asyncio.wait_for(
                    receive(),
                    timeout=min(self.idle_seconds, remaining),
                )
            except asyncio.TimeoutError as exc:
                raise UploadBodyTimeout from exc
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.maximum:
                    raise UploadBodyTooLarge
            return message

        await self.app(scope, bounded_receive, send)


class EvaluationAdmissionLimiter:
    """Bound anonymous evaluation starts without retaining uploaded data."""

    def __init__(self, *, window_seconds: int, global_limit: int, client_limit: int):
        if min(window_seconds, global_limit, client_limit) <= 0:
            raise ValueError("evaluation admission limits must be positive")
        self.window_seconds = window_seconds
        self.global_limit = global_limit
        self.client_limit = client_limit
        self._global: deque[float] = deque()
        self._clients: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def admit(self, client_id: str, *, now: float | None = None) -> int | None:
        observed = time.monotonic() if now is None else now
        cutoff = observed - self.window_seconds
        with self._lock:
            while self._global and self._global[0] <= cutoff:
                self._global.popleft()
            for existing_id, existing in list(self._clients.items()):
                while existing and existing[0] <= cutoff:
                    existing.popleft()
                if not existing:
                    del self._clients[existing_id]
            client = self._clients.setdefault(client_id, deque())
            while client and client[0] <= cutoff:
                client.popleft()
            global_full = len(self._global) >= self.global_limit
            client_full = len(client) >= self.client_limit
            if global_full or client_full:
                oldest = max(
                    self._global[0] if global_full else cutoff,
                    client[0] if client_full else cutoff,
                )
                if not client:
                    del self._clients[client_id]
                return max(1, int(self.window_seconds - (observed - oldest)) + 1)
            self._global.append(observed)
            client.append(observed)
            return None
