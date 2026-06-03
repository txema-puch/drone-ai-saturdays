"""SADAR-merge (Direction C) — FastAPI serve layer for the post-hoc analyst-triage tool.

Serves the precompute bundle (`serve/precompute.py` → `models/sadar_demo/`) over the SAME
route shapes + response interfaces as SADAR's `serve/app.py` + `frontend/src/api.ts`, so
the vendored React frontend works against it unchanged. Difference from his serve: this is a
RETROSPECTIVE AUDIT surface (ranked queue → case file), not a live monitor (design doc §4.5).
Read endpoints are bundle-backed — no torch at boot, fast cold start for an HF Space.

  GET  /api/health            liveness + bundle summary
  GET  /api/flights           the ranked triage queue (FlightSummary[] + our `label`)
  GET  /api/flights/{id}      a case file (FlightDetail: path, reconstructed, step scores, …)
  GET  /api/metrics           our Phase-7 results (real + synthetic), MetricRow[] shape
  POST /api/simulate          analyst what-if — wired in the next increment (501 for now)

Run:  cd backend && uv run uvicorn serve.app:app --reload
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "backend/models/sadar_demo"


def _load_bundle():
    return (
        json.loads((BUNDLE / "queue.json").read_text()),
        json.loads((BUNDLE / "cases.json").read_text()),
        json.loads((BUNDLE / "metrics.json").read_text()),
        json.loads((BUNDLE / "manifest.json").read_text()),
    )


QUEUE, CASES, METRICS, MANIFEST = _load_bundle()
THRESHOLD = float(MANIFEST["threshold"])
STEP_THRESHOLD = float(MANIFEST["step_threshold"])
CENTER = MANIFEST["center"]
STEP_SECONDS = MANIFEST["step_seconds"]


# ── app ───────────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="LEMD Conformance Audit — post-hoc trajectory anomaly triage")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class SimulationRequest(BaseModel):
    id: int
    kind: str
    magnitude: float = 0.0
    onset: float = 0.5


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": "post-hoc-audit",
        "segments": MANIFEST["n_segments"],
        "real_anomalies": MANIFEST["n_real_anomalies"],
        "anomalous_at_threshold": MANIFEST["n_anomalous_at_thr"],
        "threshold": THRESHOLD,
        "step_threshold": STEP_THRESHOLD,
        "cases_available": len(CASES),
    }


@app.get("/api/flights")
def flights(limit: int = 50, order: str = "anomalous") -> list[dict]:
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
        "segment_id": case["segment_id"],
        "label": case["label"],
        "path": case["path"],
        "reconstructed": case["reconstructed"],
        "scores": case["step_scores"],          # SADAR `scores` = per-step timeline
        "window_score": case["score"],          # SADAR `window_score` = the segment score
        "anomalous": case["anomalous"],
        "threshold": THRESHOLD,
        "step_threshold": STEP_THRESHOLD,
        "valid_steps": case["valid_steps"],
        "feature_attribution": case["feature_attribution"],
        "center": CENTER,
        "step_seconds": STEP_SECONDS,
    }


@app.get("/api/metrics")
def metrics() -> dict:
    return METRICS


@app.post("/api/simulate")
def simulate(request: SimulationRequest) -> dict:
    # Analyst what-if: perturb a segment's measured channels → derivation replay → re-score.
    # Wired in the next increment (needs the live model + inject pipeline at serve time).
    raise HTTPException(status_code=501, detail="simulate is wired in the next increment")
