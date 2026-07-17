"""Killable process boundary for resource-bounded upload evaluation."""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from sadar.api.evaluation import ApproachUploadEvaluationService, EvaluationError

WorkerTarget = Callable[..., None]


class EvaluationWorkerFailure(RuntimeError):
    """Sanitized failure raised when an evaluation worker cannot return a result."""

    def __init__(self, failure_type: str):
        super().__init__("The isolated evaluation worker failed.")
        self.failure_type = failure_type


def _evaluation_worker(
    connection: Connection,
    release_id: str,
    reference: dict[str, Any],
    contextual: bool,
    data: bytes,
    filename: str,
    media_type: str,
) -> None:
    """Evaluate one upload and return only bounded, serializable outcomes."""
    try:
        service = ApproachUploadEvaluationService(
            release_id=release_id,
            reference=reference,
            contextual=contextual,
        )
        result = service.evaluate(
            data,
            filename=filename,
            media_type=media_type,
        )
        connection.send(("ok", result))
    except EvaluationError as exc:
        connection.send(("evaluation_error", exc.status_code, exc.detail()))
    except BaseException as exc:  # noqa: BLE001
        connection.send(("worker_error", type(exc).__name__))
    finally:
        connection.close()


def _stop_process(process: multiprocessing.Process) -> None:
    process.join(timeout=0.25)
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def run_evaluation_process(
    *,
    release_id: str,
    reference: dict[str, Any],
    contextual: bool,
    data: bytes,
    filename: str,
    media_type: str,
    timeout_seconds: float,
    worker_target: WorkerTarget = _evaluation_worker,
) -> dict[str, Any]:
    """Run one evaluation with a hard deadline and terminate overdue work."""
    deadline = time.monotonic() + timeout_seconds
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(
        target=worker_target,
        args=(writer, release_id, reference, contextual, data, filename, media_type),
        daemon=True,
    )
    process.start()
    writer.close()
    received: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def receive() -> None:
        try:
            received.put(("outcome", reader.recv()))
        except (EOFError, OSError) as exc:
            received.put(("error", exc))

    receiver = threading.Thread(target=receive, daemon=True)
    receiver.start()
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EvaluationError(
                504,
                "evaluation_timeout",
                "The approach evaluation exceeded its execution deadline.",
            )
        try:
            kind, value = received.get(timeout=remaining)
        except queue.Empty as exc:
            raise EvaluationError(
                504,
                "evaluation_timeout",
                "The approach evaluation exceeded its execution deadline.",
            ) from exc
        if kind == "error":
            raise EvaluationWorkerFailure("WorkerExited") from value
        outcome = value
    finally:
        reader.close()
        _stop_process(process)

    if outcome[0] == "ok":
        return outcome[1]
    if outcome[0] == "evaluation_error":
        detail = outcome[2]
        fields = tuple(detail.get("fields", ()))
        raise EvaluationError(outcome[1], detail["code"], detail["message"], fields)
    if outcome[0] == "worker_error":
        raise EvaluationWorkerFailure(str(outcome[1]))
    raise EvaluationWorkerFailure("InvalidWorkerResponse")
