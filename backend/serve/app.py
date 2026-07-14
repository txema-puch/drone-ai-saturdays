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
  GET  /api/flights/{id}      a segment case file with neighboring operation segments
  GET  /api/metrics           our Phase-7 results (real + synthetic), MetricRow[] shape
  POST /api/simulate          serialized analyst what-if against the frozen model

Run:  cd backend && uv run uvicorn serve.app:app --reload
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from backend.serve.operations import (  # noqa: E402
    annotate_segment_refs,
    build_operation_summaries,
    operation_ref,
)
BUNDLE = REPO / "backend/models/sadar_demo"
MODELS = REPO / "backend/models/phase6"


def _load_bundle():
    queue = json.loads((BUNDLE / "queue.json").read_text())
    if queue and "case_ref" not in queue[0]:
        queue = annotate_segment_refs(queue)
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
    operations_path = BUNDLE / "operations.json"
    operations = (
        json.loads(operations_path.read_text())
        if operations_path.exists()
        else build_operation_summaries(queue)
    )
    if operations and "behavioral_worst_score" not in operations[0]:
        operations = build_operation_summaries(queue)
    return queue, operations, json.loads((BUNDLE / "cases.json").read_text()), json.loads(
        (BUNDLE / "metrics.json").read_text()
    ), json.loads((BUNDLE / "manifest.json").read_text())


QUEUE, OPERATIONS, CASES, METRICS, MANIFEST = _load_bundle()
THRESHOLD = float(MANIFEST["threshold"])
STEP_THRESHOLD = float(MANIFEST["step_threshold"])
CENTER = MANIFEST["center"]
STEP_SECONDS = MANIFEST["step_seconds"]
T = int(MANIFEST["T"])
COHORT_SCORES = np.array([q["score"] for q in QUEUE], dtype="float64")
SIMULATION_LOCK = Lock()


@lru_cache(maxsize=1)
def _sim_artifacts():
    """Lazy-load the torch model + scaler + raw cohort for the what-if. Kept out of cold
    start (read endpoints are bundle-only) — paid once, on the first /api/simulate call."""
    import joblib
    import pandas as pd

    from backend.core import lstm_ae as ae

    clean = pd.read_parquet(BUNDLE / "cases_raw.parquet")
    scaler = joblib.load(MODELS / "scaler.joblib")
    model = ae.load_checkpoint(str(MODELS / "lstm_ae_best.pt"))
    return clean, scaler, model


# ── app ───────────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="LEMD Conformance Audit — post-hoc trajectory anomaly triage")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class SimulationRequest(BaseModel):
    id: int
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
    "case_ref",
    "segment_id",
    "score",
    "pct",
    "label",
    "anomalous",
    "review_lane",
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": "post-hoc-audit",
        "segments": MANIFEST["n_segments"],
        "operations": MANIFEST.get("n_operations", len(OPERATIONS)),
        "real_anomalies": MANIFEST["n_real_anomalies"],
        "anomalous_at_threshold": MANIFEST["n_anomalous_at_thr"],
        "reviewable": MANIFEST.get("n_reviewable", MANIFEST["n_segments"]),
        "data_quality_conflicts": MANIFEST.get("n_data_quality_conflicts", 0),
        "insufficient_data": MANIFEST.get("n_insufficient_data", 0),
        "coverage_limited": MANIFEST.get("n_coverage_limited", 0),
        "threshold": THRESHOLD,
        "step_threshold": STEP_THRESHOLD,
        "cases_available": len(CASES),
    }


@app.get("/api/flights")
def flights(limit: QueueLimit = 50, order: QueueOrder = "anomalous") -> list[dict]:
    """The ranked triage queue. `order`: anomalous (default, most→least) | normal (least→most)
    | typical (closest to the median normal). Every entry carries our `label`
    (normal / go_around / emergency) and whether a case file is available to open."""
    if order == "normal":
        ranked = QUEUE[::-1]
    elif order == "typical":
        med = MANIFEST["median_score"]
        ranked = sorted(QUEUE, key=lambda q: abs(q["score"] - med))
    else:
        ranked = QUEUE  # already most→least anomalous
    out = []
    for q in ranked[:limit]:
        out.append({**q, "has_case": str(q["id"]) in CASES})
    return out


@app.get("/api/operations")
def operations(limit: QueueLimit = 50, order: QueueOrder = "anomalous") -> list[dict]:
    """Operations ranked by the worst segment only; segment scores are never summed."""
    if order == "normal":
        ranked = OPERATIONS[::-1]
    elif order == "typical":
        med = MANIFEST["median_score"]
        ranked = sorted(
            OPERATIONS,
            key=lambda op: abs((op["behavioral_worst_score"] or op["worst_score"]) - med),
        )
    else:
        ranked = OPERATIONS
    return [
        {
            **operation,
            "worst_has_case": str(operation["worst_segment_id_num"]) in CASES,
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
        "worst_has_case": str(match["worst_segment_id_num"]) in CASES,
        "segments": [
            {**segment, "has_case": str(segment["id"]) in CASES}
            for segment in match["segments"]
        ],
    }


@app.get("/api/flights/{flight_id}")
def flight(flight_id: int) -> dict:
    """A case file. Mapped to SADAR's `FlightDetail` shape (`scores`, `window_score`) plus our
    `label` + `feature_attribution`, so his frontend renders it unchanged."""
    case = CASES.get(str(flight_id))
    if case is None:
        raise HTTPException(
            status_code=404,
            detail="no case file baked for this segment (open a queued, ranked, or typical one)",
        )
    return {
        "id": case["id"],
        "case_ref": case.get("case_ref", f"CASE-{int(case['id']):04d}"),
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
                {**segment, "has_case": str(segment["id"]) in CASES}
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

    case = CASES.get(str(request.id))
    if case is None:
        raise HTTPException(status_code=404, detail="no case file for this segment")

    if not SIMULATION_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="simulation already in progress")
    try:
        clean, scaler, model = _sim_artifacts()
        seg = clean[clean.segment_id == case["segment_id"]]
        if seg.empty:
            raise HTTPException(status_code=404, detail="raw segment not in the baked cohort")

        try:
            result = simulate_segment(
                seg, request.kind, request.intensity, request.onset,
                scaler=scaler, model=model, T=T,
                threshold=THRESHOLD, step_threshold=STEP_THRESHOLD,
                cohort_scores=COHORT_SCORES,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        SIMULATION_LOCK.release()

    result["id"] = request.id
    result["segment_id"] = case["segment_id"]
    result["center"] = CENTER
    result["step_seconds"] = STEP_SECONDS
    result["original_score"] = case["score"]
    return result
