"""FastAPI surface for the rules-first SADAR approach-screening release.

This entrypoint is intentionally independent from :mod:`backend.serve.app`: it does
not load the historical LSTM bundle or expose model-scoring routes. Read requests are
served from the immutable schema-v3 JSON release; uploads use the same published
geometry, configuration, and train-only empirical reference.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile
from starlette.middleware.gzip import GZipMiddleware

from backend.core.approach_geometry import load_lemd_geometry, runway_relative
from backend.serve.approach_evaluation import (
    MAX_INPUT_BYTES,
    ApproachUploadEvaluationService,
    EvaluationError,
)
from backend.serve.approach_release import load_release_directory


REPO = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO / "frontend/dist"
DEFAULT_RELEASE_DIR = REPO / "backend/models/sadar_approach_v3"
RELEASE_DIR = Path(
    os.getenv("SADAR_APPROACH_RELEASE_DIR")
    or os.getenv("SADAR_RELEASE_DIR")
    or DEFAULT_RELEASE_DIR
)
EVALUATION_ENABLED = os.getenv("SADAR_ENABLE_EVALUATION", "").strip().lower() in {
    "1", "true",
}
EVALUATION_RATE_WINDOW_S = 60
EVALUATION_GLOBAL_LIMIT = int(os.getenv("SADAR_EVALUATION_GLOBAL_LIMIT", "10"))
EVALUATION_CLIENT_LIMIT = int(os.getenv("SADAR_EVALUATION_CLIENT_LIMIT", "5"))
MAX_MULTIPART_BYTES = MAX_INPUT_BYTES + 64 * 1024

RELEASE = load_release_directory(RELEASE_DIR)
MANIFEST = RELEASE["manifest"]
ATTEMPTS = RELEASE["attempts"]
CASES_BY_ID = {item["case_id"]: item for item in RELEASE["cases"]}
OPERATIONS_BY_ID = {item["operation_id"]: item for item in RELEASE["operations"]}
METRICS = RELEASE["metrics"]
REFERENCE = RELEASE["reference"]
RESEARCH = RELEASE["research"]
RELEASE_ID = MANIFEST["release_id"]
SCHEMA_VERSION = MANIFEST["schema_version"]
CONTEXTUAL_RELEASE = MANIFEST.get("contracts", {}).get("engine_version") == "approach_context_v1"
STATUS_PRIORITY = {
    "review_required": 0,
    "partial_observation": 1,
    "criteria_observed": 2,
    "not_assessable": 3,
}
ATTEMPTS_BY_ID = {item["attempt_id"]: item for item in ATTEMPTS}
RANKED_ATTEMPTS = sorted(
    ATTEMPTS,
    key=lambda item: (
        STATUS_PRIORITY.get(item["status"], 99),
        -int(item.get("start_time") or 0),
        item["attempt_id"],
    ),
)


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
                    receive(), timeout=min(self.idle_seconds, remaining)
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


app = FastAPI(
    title="SADAR Analyst Console",
    description=(
        "Retrospective, rules-first screening of ADS-B-observable LEMD approach attempts."
    ),
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    EvaluationBodyLimitMiddleware,
    maximum=MAX_MULTIPART_BYTES,
    idle_seconds=5.0,
    total_seconds=60.0,
)
EVALUATION_LOCK = asyncio.Lock()
EVALUATION_LIMITER = EvaluationAdmissionLimiter(
    window_seconds=EVALUATION_RATE_WINDOW_S,
    global_limit=EVALUATION_GLOBAL_LIMIT,
    client_limit=EVALUATION_CLIENT_LIMIT,
)


ApproachLimit = Annotated[int, Query(ge=0, le=5000)]
ApproachStatus = Literal[
    "review_required", "partial_observation", "criteria_observed", "not_assessable"
]


def _api_error(
    status: int,
    code: str,
    message: str,
    *,
    retry_after: int | None = None,
) -> None:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": message},
        headers=headers,
    )


def _quality_flags(assessment: dict) -> list[str]:
    quality = assessment.get("quality") or {}
    flags = list(quality.get("fatal_reasons") or [])
    for advisories in (quality.get("channel_advisories") or {}).values():
        flags.extend(advisories)
    return sorted(set(str(flag) for flag in flags))


def _summary(record: dict) -> dict:
    assessment = record["assessment"]
    attempt = assessment.get("attempt") or {}
    quality = assessment.get("quality") or {}
    inference = assessment.get("runway_inference") or {}
    return {
        "attempt_id": record["attempt_id"],
        "operation_ref": record["operation_id"],
        "status": record["status"],
        "direction": record.get("runway_direction"),
        "runway": record.get("runway"),
        "geometry_runway": inference.get("geometry_runway"),
        "runway_specificity": inference.get("specificity"),
        "runway_confidence": inference.get("confidence"),
        "runway_score_margin": inference.get("score_margin"),
        "failed_criteria": list(record.get("failed_criteria") or []),
        "outcome": record.get("outcome"),
        "observed_samples": attempt.get("observed_samples"),
        "coverage": {
            "observed_samples": attempt.get("observed_samples"),
            "maximum_gap_s": quality.get("maximum_gap_s"),
        },
        "start_time": record.get("start_time"),
        "end_time": record.get("end_time"),
        "reasons": list(assessment.get("reasons") or []),
        "quality_flags": _quality_flags(assessment),
    }


def _case_path(record: dict, case: dict) -> list[dict]:
    observations = case.get("observations") or []
    if not observations:
        return []
    assessment = record["assessment"]
    runway_name = assessment.get("runway_inference", {}).get("geometry_runway")
    relative = None
    if runway_name:
        geometry = load_lemd_geometry()
        runway = geometry.thresholds.get(runway_name)
        valid = all(item.get("lat") is not None and item.get("lon") is not None for item in observations)
        if runway is not None and valid:
            frame = pd.DataFrame(observations)
            relative = runway_relative(frame["lat"], frame["lon"], runway)
    path = []
    for index, item in enumerate(observations):
        point = {
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "alt": item.get("baroaltitude"),
            "time": item.get("time"),
            "t": item.get("time"),
            "observed": True,
        }
        if relative is not None:
            point["along_track_m"] = round(float(relative.along_track_m[index]), 1)
            point["cross_track_m"] = round(float(relative.cross_track_m[index]), 1)
        path.append(point)
    return path


def _detail(record: dict) -> dict:
    assessment = record["assessment"]
    case = CASES_BY_ID[record["case_id"]]
    return {
        **_summary(record),
        "path": _case_path(record, case),
        "criteria": assessment.get("criteria") or [],
        "quality": assessment.get("quality"),
        "altitude_reference": assessment.get("altitude_reference"),
        "maneuvers": assessment.get("maneuvers") or [],
        "provenance": assessment.get("provenance"),
        "geometry": assessment.get("geometry"),
        "reference": assessment.get("reference"),
        "context": assessment.get("context"),
        "schema_version": assessment.get("schema_version"),
        "engine_version": assessment.get("engine_version"),
        "observations_downsampled": case.get("observations_downsampled", False),
        "research_benchmark": RESEARCH,
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": "approach-screening",
        "release_id": RELEASE_ID,
        "schema_version": SCHEMA_VERSION,
        "attempts": len(ATTEMPTS),
        "operations": len(OPERATIONS_BY_ID),
        "status_counts": METRICS.get("status_counts", {}),
        "cases_available": len(CASES_BY_ID),
        "reference": {
            "status": "loaded",
            "id": REFERENCE.get("schema_version"),
            "artifact_sha256": REFERENCE.get("artifact_sha256"),
        },
        "evaluation_enabled": EVALUATION_ENABLED,
        "context_enabled": CONTEXTUAL_RELEASE,
        "qualification": METRICS.get("qualification"),
        "allowed_role": METRICS.get("allowed_role"),
        "blocked_uses": METRICS.get("blocked_uses", []),
    }


@app.get("/api/approaches")
def approaches(
    limit: ApproachLimit = 500,
    status: ApproachStatus | None = None,
    direction: str | None = Query(default=None, max_length=8),
    criterion: str | None = Query(default=None, max_length=80),
    outcome: str | None = Query(default=None, max_length=80),
) -> list[dict]:
    selected = RANKED_ATTEMPTS
    if status:
        selected = [item for item in selected if item["status"] == status]
    if direction:
        selected = [item for item in selected if item.get("runway_direction") == direction]
    if criterion:
        selected = [item for item in selected if criterion in item.get("failed_criteria", [])]
    if outcome:
        selected = [item for item in selected if item.get("outcome") == outcome]
    return [_summary(item) for item in selected[:limit]]


@app.get("/api/approaches/{attempt_id}")
def approach(attempt_id: str) -> dict:
    record = ATTEMPTS_BY_ID.get(attempt_id)
    if record is None:
        _api_error(404, "attempt_not_found", "The approach attempt is not in this release.")
    return _detail(record)


@app.get("/api/approach-operations/{operation_ref}")
def approach_operation(operation_ref: str) -> dict:
    operation = OPERATIONS_BY_ID.get(operation_ref)
    if operation is None:
        _api_error(404, "operation_not_found", "The operation is not in this release.")
    return {
        "operation_ref": operation_ref,
        "attempts": [
            _summary(ATTEMPTS_BY_ID[attempt_id])
            for attempt_id in operation.get("attempt_ids", [])
        ],
    }


@app.get("/api/metrics")
def metrics() -> dict:
    return METRICS


@app.get("/api/research")
def research() -> dict:
    if RESEARCH is None:
        _api_error(404, "research_not_published", "This release has no research benchmark.")
    return RESEARCH


@app.post("/api/evaluations")
async def evaluate_upload(request: Request) -> dict:
    if not EVALUATION_ENABLED:
        _api_error(404, "evaluation_disabled", "Evaluation is not enabled on this deployment.")
    if EVALUATION_LOCK.locked():
        _api_error(429, "analysis_busy", "Another approach evaluation is in progress.", retry_after=1)
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
        except ValueError:
            _api_error(400, "invalid_content_length", "Content-Length must be an integer.")
        if declared_bytes < 0:
            _api_error(400, "invalid_content_length", "Content-Length cannot be negative.")
        if declared_bytes > MAX_MULTIPART_BYTES:
            _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
    client_id = request.client.host if request.client is not None else "unknown"
    retry_after = EVALUATION_LIMITER.admit(client_id)
    if retry_after is not None:
        _api_error(
            429,
            "evaluation_rate_limited",
            "The public evaluation budget is temporarily exhausted.",
            retry_after=retry_after,
        )

    try:
        async with request.form(max_files=1, max_fields=0, max_part_size=MAX_INPUT_BYTES + 1) as form:
            files = form.getlist("file")
            if len(files) != 1 or not isinstance(files[0], UploadFile):
                _api_error(
                    422,
                    "invalid_multipart",
                    "Provide exactly one multipart file field named 'file'.",
                )
            upload = files[0]
            data = await upload.read(MAX_INPUT_BYTES + 1)
            filename = upload.filename or ""
            media_type = upload.content_type or ""
    except UploadBodyTooLarge:
        _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
    except UploadBodyTimeout:
        _api_error(408, "upload_timeout", "The upload body timed out.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_multipart", "message": "The multipart upload is malformed."},
        ) from exc
    if len(data) > MAX_INPUT_BYTES:
        _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
    if EVALUATION_LOCK.locked():
        _api_error(429, "analysis_busy", "Another approach evaluation is in progress.", retry_after=1)
    service = ApproachUploadEvaluationService(
        release_id=RELEASE_ID,
        reference=REFERENCE,
        contextual=CONTEXTUAL_RELEASE,
    )
    try:
        async with EVALUATION_LOCK:
            return await run_in_threadpool(
                service.evaluate,
                data,
                filename=filename,
                media_type=media_type,
            )
    except EvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "evaluation_failed",
                "message": "The approach evaluation could not be completed.",
            },
        ) from exc


@app.api_route(
    "/api/{api_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
def unknown_api(api_path: str) -> None:
    _api_error(404, "api_route_not_found", "The API route does not exist.")


@app.get("/{spa_path:path}", include_in_schema=False)
def frontend(spa_path: str):
    """Serve same-origin assets and use the SPA shell for non-API deep links."""
    if spa_path == "api" or spa_path.startswith("api/"):
        _api_error(404, "api_route_not_found", "The API route does not exist.")
    try:
        root = FRONTEND_DIST.resolve(strict=True)
        requested = (root / spa_path).resolve(strict=False)
        requested.relative_to(root)
    except (OSError, ValueError):
        _api_error(404, "application_unavailable", "The application shell is unavailable.")
    if requested.is_file():
        return FileResponse(requested)
    index = root / "index.html"
    if not index.is_file():
        _api_error(404, "application_unavailable", "The application shell is unavailable.")
    return FileResponse(index)
