"""Pure FastAPI composition for one validated approach release."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile
from starlette.middleware.gzip import GZipMiddleware

from sadar.api.evaluation import (
    MAX_INPUT_BYTES,
    ApproachUploadEvaluationService,
    EvaluationError,
)
from sadar.api.middleware import (
    EvaluationAdmissionLimiter,
    EvaluationBodyLimitMiddleware,
    UploadBodyTimeout,
    UploadBodyTooLarge,
)
from sadar.api.presenters import detail, summary
from sadar.api.settings import Settings
from sadar.api.state import RuntimeState, build_release_state

ApproachLimit = Annotated[int, Query(ge=0, le=5000)]
ApproachStatus = Literal[
    "review_required",
    "partial_observation",
    "criteria_observed",
    "not_assessable",
]
EvaluationServiceFactory = Callable[..., ApproachUploadEvaluationService]


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


def _safe_frontend_path(root: Path, spa_path: str) -> Path:
    try:
        requested = (root / spa_path).resolve(strict=False)
        requested.relative_to(root)
    except (OSError, ValueError):
        _api_error(404, "application_unavailable", "The application shell is unavailable.")
    return requested


def create_app(
    settings: Settings,
    release: dict,
    *,
    evaluation_service_factory: EvaluationServiceFactory = ApproachUploadEvaluationService,
) -> FastAPI:
    """Build an isolated application from explicit settings and validated release data."""
    state = build_release_state(release)
    runtime = RuntimeState(
        evaluation_lock=asyncio.Lock(),
        evaluation_limiter=EvaluationAdmissionLimiter(
            window_seconds=settings.evaluation_rate_window_s,
            global_limit=settings.evaluation_global_limit,
            client_limit=settings.evaluation_client_limit,
        ),
    )
    frontend_root = settings.validated_frontend_dir()
    app = FastAPI(
        title="SADAR Analyst Console",
        description=(
            "Retrospective, rules-first screening of ADS-B-observable LEMD approach attempts."
        ),
    )
    app.state.release = state
    app.state.runtime = runtime
    app.state.settings = settings
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        EvaluationBodyLimitMiddleware,
        maximum=settings.maximum_multipart_bytes,
        idle_seconds=settings.upload_idle_seconds,
        total_seconds=settings.upload_total_seconds,
    )

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "mode": "approach-screening",
            "release_id": state.release_id,
            "schema_version": state.schema_version,
            "attempts": len(state.attempts),
            "operations": len(state.operations_by_id),
            "status_counts": state.metrics.get("status_counts", {}),
            "cases_available": len(state.cases_by_id),
            "reference": {
                "status": "loaded",
                "id": state.reference.get("schema_version"),
                "artifact_sha256": state.reference.get("artifact_sha256"),
            },
            "evaluation_enabled": settings.evaluation_enabled,
            "context_enabled": state.contextual,
            "qualification": state.metrics.get("qualification"),
            "allowed_role": state.metrics.get("allowed_role"),
            "blocked_uses": state.metrics.get("blocked_uses", []),
        }

    @app.get("/api/approaches")
    def approaches(
        limit: ApproachLimit = 500,
        status: ApproachStatus | None = None,
        direction: str | None = Query(default=None, max_length=8),
        criterion: str | None = Query(default=None, max_length=80),
        outcome: str | None = Query(default=None, max_length=80),
    ) -> list[dict]:
        selected = state.ranked_attempts
        if status:
            selected = tuple(item for item in selected if item["status"] == status)
        if direction:
            selected = tuple(
                item for item in selected if item.get("runway_direction") == direction
            )
        if criterion:
            selected = tuple(
                item
                for item in selected
                if criterion in item.get("failed_criteria", [])
            )
        if outcome:
            selected = tuple(
                item for item in selected if item.get("outcome") == outcome
            )
        return [summary(item) for item in selected[:limit]]

    @app.get("/api/approaches/{attempt_id}")
    def approach(attempt_id: str) -> dict:
        record = state.attempts_by_id.get(attempt_id)
        if record is None:
            _api_error(404, "attempt_not_found", "The approach attempt is not in this release.")
        return detail(record, state)

    @app.get("/api/approach-operations/{operation_ref}")
    def approach_operation(operation_ref: str) -> dict:
        operation = state.operations_by_id.get(operation_ref)
        if operation is None:
            _api_error(404, "operation_not_found", "The operation is not in this release.")
        return {
            "operation_ref": operation_ref,
            "attempts": [
                summary(state.attempts_by_id[attempt_id])
                for attempt_id in operation.get("attempt_ids", [])
            ],
        }

    @app.get("/api/metrics")
    def metrics() -> dict:
        return dict(state.metrics)

    @app.get("/api/research")
    def research() -> dict:
        if state.research is None:
            _api_error(404, "research_not_published", "This release has no research benchmark.")
        return dict(state.research)

    @app.post("/api/evaluations")
    async def evaluate_upload(request: Request) -> dict:
        if not settings.evaluation_enabled:
            _api_error(404, "evaluation_disabled", "Evaluation is not enabled on this deployment.")
        if runtime.evaluation_lock.locked():
            _api_error(429, "analysis_busy", "Another approach evaluation is in progress.", retry_after=1)
        declared = request.headers.get("content-length")
        if declared:
            try:
                declared_bytes = int(declared)
            except ValueError:
                _api_error(400, "invalid_content_length", "Content-Length must be an integer.")
            if declared_bytes < 0:
                _api_error(400, "invalid_content_length", "Content-Length cannot be negative.")
            if declared_bytes > settings.maximum_multipart_bytes:
                _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
        client_id = request.client.host if request.client is not None else "unknown"
        retry_after = runtime.evaluation_limiter.admit(client_id)
        if retry_after is not None:
            _api_error(
                429,
                "evaluation_rate_limited",
                "The public evaluation budget is temporarily exhausted.",
                retry_after=retry_after,
            )
        try:
            async with request.form(
                max_files=1,
                max_fields=0,
                max_part_size=MAX_INPUT_BYTES + 1,
            ) as form:
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
                detail={
                    "code": "invalid_multipart",
                    "message": "The multipart upload is malformed.",
                },
            ) from exc
        if len(data) > MAX_INPUT_BYTES:
            _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
        if runtime.evaluation_lock.locked():
            _api_error(429, "analysis_busy", "Another approach evaluation is in progress.", retry_after=1)
        service = evaluation_service_factory(
            release_id=state.release_id,
            reference=dict(state.reference),
            contextual=state.contextual,
        )
        try:
            async with runtime.evaluation_lock:
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
        if spa_path == "api" or spa_path.startswith("api/"):
            _api_error(404, "api_route_not_found", "The API route does not exist.")
        if frontend_root is None:
            _api_error(404, "application_unavailable", "The application shell is unavailable.")
        requested = _safe_frontend_path(frontend_root, spa_path)
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend_root / "index.html")

    return app
