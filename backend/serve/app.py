"""SADAR-merge (Direction C) — FastAPI serve layer for the post-hoc analyst-triage tool.

Serves the precompute bundle (`serve/precompute.py` → `models/sadar_demo/`) over the SAME
route shapes + response interfaces as SADAR's `serve/app.py` + `frontend/src/api.ts`, so
the vendored React frontend works against it unchanged. Difference from his serve: this is a
RETROSPECTIVE AUDIT surface (ranked queue → case file), not a live monitor (design doc §4.5).
Read endpoints are bundle-backed — no torch at boot, fast cold start for an HF Space.

  GET  /api/health            liveness + bundle summary
  GET  /api/flights           the ranked segment queue (FlightSummary[] + our `label`)
  GET  /api/operations        operation summaries, ranked by their single worst segment
  GET  /api/operations/{ref}  one operation with all scored segment evidence
  GET  /api/flights/{case_id} a segment case file with neighboring operation segments
  GET  /api/metrics           our Phase-7 results (real + synthetic), MetricRow[] shape
  POST /api/simulate          serialized analyst what-if against the frozen model

Run:  cd backend && uv run uvicorn serve.app:app --reload
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from starlette.middleware.gzip import GZipMiddleware

REPO = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO / "frontend/dist"
sys.path.insert(0, str(REPO))
from backend.serve.operations import (  # noqa: E402
    build_operation_summaries,
    operation_ref,
)
BUNDLE = REPO / "backend/models/sadar_demo"
MODELS = REPO / "backend/models/phase6"
CONFIGURED_RELEASE_DIR = os.getenv("SADAR_RELEASE_DIR")
RELEASE_DIR = Path(CONFIGURED_RELEASE_DIR) if CONFIGURED_RELEASE_DIR else BUNDLE
EVALUATION_ENABLED = os.getenv("SADAR_ENABLE_EVALUATION", "").strip().lower() in {"1", "true"}


def _load_bundle():
    if CONFIGURED_RELEASE_DIR:
        from backend.serve.release import SERVING_FILE_BYTE_LIMITS, read_json_file, validate_release_directory

        manifest = validate_release_directory(RELEASE_DIR)
        bundle_manifest = manifest
        expected_online = {
            "input_schema_version": "opensky_raw_v1",
            "derivation_contract_version": "derivations_v1",
            "preprocessing_contract_version": "preprocessing_v1",
        }
        online = manifest.get("online_input_contract", {})
        for key, expected in expected_online.items():
            if online.get(key) != expected:
                raise RuntimeError(
                    f"release {key} mismatch: expected {expected!r}, observed {online.get(key)!r}"
                )
        read_release_json = lambda name: read_json_file(  # noqa: E731
            RELEASE_DIR / name, max_bytes=SERVING_FILE_BYTE_LIMITS[name]
        )
    else:
        bundle_manifest = json.loads((BUNDLE / "manifest.json").read_text())
        if bundle_manifest.get("schema_version") != 2:
            raise RuntimeError("serve bundle must use schema_version 2 stable case identities")
        manifest = bundle_manifest
        read_release_json = lambda name: json.loads((RELEASE_DIR / name).read_text())  # noqa: E731
    queue = read_release_json("queue.json")
    if queue and "assessment_state" not in queue[0]:
        queue = [
            {
                **row,
                "assessment_state": "reviewable",
                "behavioral_verdict": "reviewable",
                "review_lane": "behavioral",
                "data_quality_flags": [],
            }
            for row in queue
        ]
    operations_path = RELEASE_DIR / "operations.json"
    operations = (
        read_release_json("operations.json")
        if operations_path.exists()
        else build_operation_summaries(queue)
    )
    if operations and "behavioral_worst_score" not in operations[0]:
        operations = build_operation_summaries(queue)
    return queue, operations, read_release_json("cases.json"), read_release_json(
        "metrics.json"
    ), manifest, bundle_manifest


QUEUE, OPERATIONS, CASES, METRICS, RELEASE_MANIFEST, MANIFEST = _load_bundle()
SCORING_CONTRACT = (
    RELEASE_MANIFEST["scoring_contract"] if CONFIGURED_RELEASE_DIR else MANIFEST
)
THRESHOLD = float(SCORING_CONTRACT["threshold"])
STEP_THRESHOLD = float(SCORING_CONTRACT["step_threshold"])
CENTER = MANIFEST.get("center", {"lat": 40.4936, "lon": -3.5668})
STEP_SECONDS = int(MANIFEST.get("step_seconds", 10))
T = int(SCORING_CONTRACT["T"])
COHORT_SCORES = np.array([q["score"] for q in QUEUE], dtype="float64")
MEDIAN_SCORE = float(np.median(COHORT_SCORES))
RELEASE_ID = str(RELEASE_MANIFEST.get("release_id", "local-schema-v2"))
SCHEMA_VERSION = int(RELEASE_MANIFEST.get("schema_version", MANIFEST.get("schema_version", 2)))
_MODEL_RECORD = next(
    (record for record in RELEASE_MANIFEST.get("files", []) if record.get("path") == "model/model-contract.json"),
    None,
)
MODEL_ID = (
    str(_MODEL_RECORD["sha256"])[:20]
    if _MODEL_RECORD is not None
    else hashlib.sha256(f"{RELEASE_ID}|lstm-ae".encode()).hexdigest()[:20]
)


@lru_cache(maxsize=1)
def _sim_artifacts():
    """Lazy-load the torch model + scaler + raw cohort for the what-if. Kept out of cold
    start (read endpoints are bundle-only) — paid once, on the first /api/simulate call."""
    import joblib
    import pandas as pd

    from backend.core import lstm_ae as ae

    clean = pd.read_parquet(RELEASE_DIR / "cases_raw.parquet")
    scaler = joblib.load(MODELS / "scaler.joblib")
    model = ae.load_checkpoint(str(MODELS / "lstm_ae_best.pt"))
    return clean, scaler, model


def _load_runtime_artifacts():
    if CONFIGURED_RELEASE_DIR:
        from backend.serve.model_artifacts import load_model_artifacts
        from backend.serve.evaluation import (
            DERIVATION_CONTRACT_VERSION,
            INPUT_SCHEMA_VERSION,
            PREPROCESSING_CONTRACT_VERSION,
        )

        return load_model_artifacts(
            RELEASE_DIR,
            RELEASE_MANIFEST,
            input_schema_version=INPUT_SCHEMA_VERSION,
            derivation_contract_version=DERIVATION_CONTRACT_VERSION,
            preprocessing_contract_version=PREPROCESSING_CONTRACT_VERSION,
        )
    _clean, scaler, model = _sim_artifacts()
    return SimpleNamespace(
        model=model,
        scaler=scaler,
        cohort_reference=tuple(sorted(float(value) for value in COHORT_SCORES)),
        model_contract={"scoring_contract": {
            "T": T,
            "threshold": THRESHOLD,
            "step_threshold": STEP_THRESHOLD,
        }},
    )


from backend.serve.model_runtime import AnalysisBusy, ModelNotReady, ModelRuntime  # noqa: E402

MODEL_RUNTIME = ModelRuntime(_load_runtime_artifacts)


# ── app ───────────────────────────────────────────────────────────────────────────────────

class UploadBodyTooLarge(Exception):
    pass


class UploadBodyTimeout(Exception):
    pass


class EvaluationBodyLimitMiddleware:
    """Count multipart bytes and bound idle/total reads before form parsing."""

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


app = FastAPI(title="LEMD Conformance Audit — post-hoc trajectory anomaly triage")
app.add_middleware(GZipMiddleware, minimum_size=1000)
from backend.serve.evaluation import MAX_MULTIPART_BYTES  # noqa: E402
app.add_middleware(
    EvaluationBodyLimitMiddleware,
    maximum=MAX_MULTIPART_BYTES,
    idle_seconds=5.0,
    total_seconds=60.0,
)


class SimulationRequest(BaseModel):
    case_id: str
    kind: Literal[
        "zone_violation",
        "altitude_high",
        "sustained_loiter",
        "final_approach_intercept",
        "speed_spike",
    ]
    intensity: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)
    onset: float = Field(default=0.5, ge=0.0, le=1.0, allow_inf_nan=False)


QueueOrder = Literal["anomalous", "normal", "typical"]
QueueLimit = Annotated[int, Query(ge=0, le=5000)]

OPERATION_QUEUE_SEGMENT_FIELDS = (
    "case_id",
    "case_ref",
    "segment_id",
    "score",
    "pct",
    "label",
    "anomalous",
    "review_lane",
)


def _api_error(status: int, code: str, message: str, *, retry_after: int | None = None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": message},
        headers=headers,
    )


@app.get("/api/health")
def health() -> dict:
    runtime = MODEL_RUNTIME.snapshot()
    return {
        "status": "ok",
        "mode": "post-hoc-audit",
        "segments": MANIFEST.get("n_segments", len(QUEUE)),
        "operations": MANIFEST.get("n_operations", len(OPERATIONS)),
        "real_anomalies": MANIFEST.get("n_real_anomalies", sum(q.get("label") != "normal" for q in QUEUE)),
        "anomalous_at_threshold": MANIFEST.get("n_anomalous_at_thr", sum(q.get("anomalous", False) for q in QUEUE)),
        "reviewable": MANIFEST.get("n_reviewable", sum(q.get("assessment_state", "reviewable") == "reviewable" for q in QUEUE)),
        "data_quality_conflicts": MANIFEST.get("n_data_quality_conflicts", sum(q.get("assessment_state") == "data_quality_conflict" for q in QUEUE)),
        "insufficient_data": MANIFEST.get("n_insufficient_data", sum(q.get("assessment_state") == "insufficient_data" for q in QUEUE)),
        "coverage_limited": MANIFEST.get("n_coverage_limited", sum(q.get("assessment_state") == "coverage_limited" for q in QUEUE)),
        "threshold": THRESHOLD,
        "step_threshold": STEP_THRESHOLD,
        "cases_available": len(CASES),
        "evaluation_enabled": EVALUATION_ENABLED,
        **runtime,
        "release_id": RELEASE_ID,
        "model_id": MODEL_ID,
        "schema_version": SCHEMA_VERSION,
    }


@app.post("/api/model/prepare")
def prepare_model() -> dict:
    if not EVALUATION_ENABLED:
        _api_error(404, "evaluation_disabled", "Evaluation is not enabled on this deployment.")
    return MODEL_RUNTIME.prepare()


@app.post("/api/evaluations")
async def evaluate_upload(request: Request) -> dict:
    if not EVALUATION_ENABLED:
        _api_error(404, "evaluation_disabled", "Evaluation is not enabled on this deployment.")
    if MODEL_RUNTIME.state != "ready":
        _api_error(503, "model_not_ready", "Prepare the frozen model before evaluating data.", retry_after=1)
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
            if declared_bytes < 0:
                _api_error(400, "invalid_content_length", "Content-Length cannot be negative.")
            if declared_bytes > MAX_MULTIPART_BYTES:
                _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
        except ValueError:
            _api_error(400, "invalid_content_length", "Content-Length must be an integer.")

    from backend.serve.evaluation import EvaluationError, UploadEvaluationService

    try:
        async with request.form(
            max_files=1,
            max_fields=0,
            max_part_size=MAX_MULTIPART_BYTES,
        ) as form:
            files = form.getlist("file")
            if len(files) != 1 or not isinstance(files[0], UploadFile):
                _api_error(422, "invalid_multipart", "Provide exactly one multipart file field named 'file'.")
            upload = files[0]
            data = await upload.read(MAX_MULTIPART_BYTES + 1)
            if len(data) > MAX_MULTIPART_BYTES:
                _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
            filename = upload.filename or ""
            media_type = upload.content_type or ""
    except UploadBodyTooLarge:
        _api_error(413, "request_too_large", "The upload exceeds the 10 MiB limit.")
    except UploadBodyTimeout:
        _api_error(408, "upload_timeout", "The upload body timed out.")
    except HTTPException:
        raise
    except Exception as exc:
        # Multipart parser details may echo boundary/body content; keep the response bounded.
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_multipart", "message": "The multipart upload is malformed."},
        ) from exc

    try:
        with MODEL_RUNTIME.analysis() as loaded:
            service = UploadEvaluationService(release_id=RELEASE_ID, model_id=MODEL_ID)
            try:
                return await run_in_threadpool(
                    service.evaluate,
                    data,
                    filename=filename,
                    media_type=media_type,
                    loaded=loaded,
                )
            except EvaluationError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "evaluation_failed",
                        "message": "The frozen-model evaluation could not be completed.",
                    },
                ) from exc
    except AnalysisBusy:
        _api_error(429, "analysis_busy", "Another model analysis is in progress.", retry_after=1)
    except ModelNotReady:
        _api_error(503, "model_not_ready", "Prepare the frozen model before evaluating data.", retry_after=1)


@app.get("/api/flights")
def flights(limit: QueueLimit = 50, order: QueueOrder = "anomalous") -> list[dict]:
    """The ranked triage queue. `order`: anomalous (default, most→least) | normal (least→most)
    | typical (closest to the median normal). Every entry carries our `label`
    (normal / go_around / emergency) and whether a case file is available to open."""
    if order == "normal":
        ranked = QUEUE[::-1]
    elif order == "typical":
        med = MEDIAN_SCORE
        ranked = sorted(QUEUE, key=lambda q: abs(q["score"] - med))
    else:
        ranked = QUEUE  # already most→least anomalous
    out = []
    for q in ranked[:limit]:
        out.append({**q, "has_case": q["case_id"] in CASES})
    return out


@app.get("/api/operations")
def operations(limit: QueueLimit = 50, order: QueueOrder = "anomalous") -> list[dict]:
    """Operations ranked by the worst segment only; segment scores are never summed."""
    if order == "normal":
        ranked = OPERATIONS[::-1]
    elif order == "typical":
        med = MEDIAN_SCORE
        ranked = sorted(
            OPERATIONS,
            key=lambda op: abs((op["behavioral_worst_score"] or op["worst_score"]) - med),
        )
    else:
        ranked = OPERATIONS
    return [
        {
            **operation,
            "worst_has_case": operation["worst_case_id"] in CASES,
            "segments": [
                {field: segment[field] for field in OPERATION_QUEUE_SEGMENT_FIELDS}
                for segment in operation["segments"]
            ],
        }
        for operation in ranked[:limit]
    ]


@app.get("/api/operations/{operation_ref_value}")
def operation(operation_ref_value: str) -> dict:
    """An operation dossier. Detailed case availability is annotated per segment."""
    match = next(
        (item for item in OPERATIONS if item["operation_ref"] == operation_ref_value.upper()),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="operation not found")
    return {
        **match,
        "worst_has_case": match["worst_case_id"] in CASES,
        "segments": [
            {**segment, "has_case": segment["case_id"] in CASES}
            for segment in match["segments"]
        ],
    }


@app.get("/api/flights/{case_id}")
def flight(case_id: str) -> dict:
    """A case file. Mapped to SADAR's `FlightDetail` shape (`scores`, `window_score`) plus our
    `label` + `feature_attribution`, so his frontend renders it unchanged."""
    case = CASES.get(case_id)
    if case is None:
        raise HTTPException(
            status_code=404,
            detail="no case file baked for this segment (open a queued, ranked, or typical one)",
        )
    return {
        "case_id": case["case_id"],
        "case_ref": case["case_ref"],
        "operation_ref": case.get("operation_ref", operation_ref(case["segment_id"])),
        "segment_id": case["segment_id"],
        "label": case["label"],
        "path": case["path"],
        "reconstructed": case["reconstructed"],
        "context_path": case.get("context_path", []),
        "n_siblings": case.get("n_siblings", 1),
        "scores": case["step_scores"],          # SADAR `scores` = per-step timeline
        "window_score": case["score"],          # SADAR `window_score` = the segment score
        "pct": case["pct"],                     # percentile rank among the cohort
        "band": case["band"],                   # plain-language severity band
        "anomalous": case["anomalous"],
        "threshold": THRESHOLD,
        "step_threshold": STEP_THRESHOLD,
        "valid_steps": case["valid_steps"],
        "n_steps": case.get("n_steps", case["valid_steps"]),
        "truncated": case.get("truncated", False),
        "terminal_op": case.get("terminal_op", True),
        "assessment_state": case.get("assessment_state", "reviewable"),
        "behavioral_verdict": case.get("behavioral_verdict", "reviewable"),
        "review_lane": case.get("review_lane", "behavioral"),
        "data_quality_flags": case.get("data_quality_flags", []),
        "observed_fraction": case.get("observed_fraction", 1.0),
        "max_altitude_jump_m": case.get("max_altitude_jump_m", 0.0),
        "max_implied_vertical_rate_mps": case.get("max_implied_vertical_rate_mps", 0.0),
        "max_implied_ground_speed_mps": case.get("max_implied_ground_speed_mps", 0.0),
        "feature_attribution": case["feature_attribution"],
        "channels": case.get("channels", {}),
        "report": case.get("report"),              # pre-generated LLM analysis (or null)
        "report_model": case.get("report_model"),
        "center": CENTER,
        "step_seconds": STEP_SECONDS,
        "operation_segments": sorted(
            [
                {**segment, "has_case": segment["case_id"] in CASES}
                for segment in QUEUE
                if segment["operation_ref"]
                == case.get("operation_ref", operation_ref(case["segment_id"]))
            ],
            key=lambda segment: int(segment["segment_id"].rsplit("#", 1)[1])
            if "#" in segment["segment_id"] else 0,
        ),
    }


@app.get("/api/metrics")
def metrics() -> dict:
    return METRICS


@app.post("/api/simulate")
def simulate(request: SimulationRequest) -> dict:
    """Analyst what-if: inject one §6 anomaly into the real segment via the FROZEN
    generator, interpolate it by `intensity`, re-derive, re-score against the same model.
    Deterministic per (segment, kind). Returns the perturbed path + per-step channels +
    per-step RE + score/percentile/band + onset step, so the frontend overlays it on the
    original case charts. A sandbox — the stored case is never mutated."""
    from backend.serve.scoring import simulate_segment

    case = CASES.get(request.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="no case file for this segment")

    try:
        with MODEL_RUNTIME.analysis() as loaded:
            import pandas as pd

            clean = pd.read_parquet(
                RELEASE_DIR / "cases_raw.parquet",
                filters=[("segment_id", "==", case["segment_id"])],
            )
            seg = clean[clean.segment_id == case["segment_id"]]
            if seg.empty:
                raise HTTPException(status_code=404, detail="raw segment not in the baked cohort")
            try:
                result = simulate_segment(
                    seg, request.kind, request.intensity, request.onset,
                    scaler=loaded.scaler, model=loaded.model, T=T,
                    threshold=THRESHOLD, step_threshold=STEP_THRESHOLD,
                    cohort_scores=loaded.cohort_reference,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
    except AnalysisBusy:
        _api_error(429, "analysis_busy", "Another model analysis is in progress.", retry_after=1)
    except ModelNotReady:
        MODEL_RUNTIME.prepare()
        _api_error(503, "model_not_ready", "The frozen model is preparing. Retry shortly.", retry_after=1)

    result["case_id"] = request.case_id
    result["segment_id"] = case["segment_id"]
    result["center"] = CENTER
    result["step_seconds"] = STEP_SECONDS
    result["original_score"] = case["score"]
    result["release_id"] = RELEASE_ID
    return result


@app.get("/{spa_path:path}", include_in_schema=False)
def frontend(spa_path: str):
    """Serve built same-origin assets and fall back to the SPA for deep links."""
    if spa_path == "api" or spa_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    try:
        root = FRONTEND_DIST.resolve(strict=True)
        requested = (root / spa_path).resolve(strict=False)
        requested.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="application shell not available") from None
    if requested.is_file():
        return FileResponse(requested)
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="application shell not available")
    return FileResponse(index)
