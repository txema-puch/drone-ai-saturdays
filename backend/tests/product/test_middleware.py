from __future__ import annotations

import asyncio

import pytest

from sadar.api.middleware import (
    EvaluationBodyLimitMiddleware,
    UploadBodyTimeout,
    UploadBodyTooLarge,
)


def _run(middleware, scope, receive) -> None:
    async def send(_message):
        return None

    asyncio.run(middleware(scope, receive, send))


def test_upload_guard_rejects_cumulative_body_overflow():
    chunks = iter(
        (
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        )
    )

    async def receive():
        return next(chunks)

    async def downstream(_scope, guarded_receive, _send):
        assert await guarded_receive() == {
            "type": "http.request",
            "body": b"123",
            "more_body": True,
        }
        with pytest.raises(UploadBodyTooLarge):
            await guarded_receive()

    middleware = EvaluationBodyLimitMiddleware(
        downstream,
        maximum=5,
        idle_seconds=1,
        total_seconds=2,
    )
    _run(middleware, {"type": "http", "path": "/api/evaluations"}, receive)


def test_upload_guard_enforces_idle_timeout():
    async def receive():
        await asyncio.sleep(0.02)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def downstream(_scope, guarded_receive, _send):
        with pytest.raises(UploadBodyTimeout):
            await guarded_receive()

    middleware = EvaluationBodyLimitMiddleware(
        downstream,
        maximum=100,
        idle_seconds=0.001,
        total_seconds=1,
    )
    _run(middleware, {"type": "http", "path": "/api/evaluations"}, receive)


def test_upload_guard_enforces_total_timeout_between_chunks():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def downstream(_scope, guarded_receive, _send):
        await asyncio.sleep(0.02)
        with pytest.raises(UploadBodyTimeout):
            await guarded_receive()

    middleware = EvaluationBodyLimitMiddleware(
        downstream,
        maximum=100,
        idle_seconds=1,
        total_seconds=0.001,
    )
    _run(middleware, {"type": "http", "path": "/api/evaluations"}, receive)


@pytest.mark.parametrize(
    "scope",
    (
        {"type": "lifespan"},
        {"type": "http", "path": "/api/health"},
    ),
)
def test_upload_guard_passes_non_evaluation_scopes_through(scope):
    observed = []

    async def receive():
        return {"type": "http.request", "body": b"ok", "more_body": False}

    async def downstream(received_scope, downstream_receive, _send):
        observed.append((received_scope, await downstream_receive()))

    middleware = EvaluationBodyLimitMiddleware(
        downstream,
        maximum=1,
        idle_seconds=1,
        total_seconds=1,
    )
    _run(middleware, scope, receive)
    assert observed == [
        (scope, {"type": "http.request", "body": b"ok", "more_body": False})
    ]
