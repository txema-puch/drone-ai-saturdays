from __future__ import annotations

import os
import struct
import time

import pytest

from sadar.api.evaluation import EvaluationError
from sadar.api.evaluation_process import run_evaluation_process
from sadar.api.state import EvaluationSlot


def _hanging_worker(connection, *_args) -> None:
    try:
        time.sleep(5)
    finally:
        connection.close()


def _successful_worker(connection, *_args) -> None:
    try:
        connection.send(("ok", {"results": []}))
    finally:
        connection.close()


def _partial_response_worker(connection, *_args) -> None:
    try:
        os.write(connection.fileno(), struct.pack("!i", 100) + b"x")
        time.sleep(5)
    finally:
        connection.close()


def _validation_error_worker(connection, *_args) -> None:
    try:
        connection.send((
            "evaluation_error",
            422,
            {
                "code": "invalid_schema",
                "message": "Invalid fields.",
                "fields": [{"field": "lat", "message": "required"}],
            },
        ))
    finally:
        connection.close()


def _run(worker, timeout_seconds: float):
    return run_evaluation_process(
        release_id="release",
        reference={},
        contextual=False,
        data=b"time\n1\n",
        filename="sample.csv",
        media_type="text/csv",
        timeout_seconds=timeout_seconds,
        worker_target=worker,
    )


def test_evaluation_process_terminates_overdue_worker_and_recovers():
    started = time.monotonic()
    with pytest.raises(EvaluationError) as captured:
        _run(_hanging_worker, timeout_seconds=0.05)
    assert time.monotonic() - started < 2
    assert captured.value.status_code == 504
    assert captured.value.code == "evaluation_timeout"
    assert _run(_successful_worker, timeout_seconds=1) == {"results": []}


def test_evaluation_process_deadline_covers_partial_worker_response():
    started = time.monotonic()
    with pytest.raises(EvaluationError) as captured:
        _run(_partial_response_worker, timeout_seconds=0.05)
    assert time.monotonic() - started < 2
    assert captured.value.code == "evaluation_timeout"


def test_evaluation_process_preserves_structured_field_errors():
    with pytest.raises(EvaluationError) as captured:
        _run(_validation_error_worker, timeout_seconds=1)

    assert captured.value.fields == ({"field": "lat", "message": "required"},)


def test_evaluation_slot_is_non_queuing_and_reusable():
    slot = EvaluationSlot()
    assert slot.try_acquire() is True
    assert slot.try_acquire() is False
    slot.release()
    assert slot.try_acquire() is True
    slot.release()
