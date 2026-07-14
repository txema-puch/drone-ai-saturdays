#!/usr/bin/env python3
"""HTTP assertions for the final same-origin SADAR container."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = os.environ.get("SADAR_SMOKE_BASE_URL", "http://127.0.0.1:17860").rstrip("/")
STARTUP_TIMEOUT = float(os.environ.get("SADAR_SMOKE_STARTUP_TIMEOUT", "30"))
MODEL_TIMEOUT = float(os.environ.get("SADAR_SMOKE_MODEL_TIMEOUT", "240"))
ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
WARM_EVALUATION_SECONDS = 10.0
MAX_EVALUATION_SECONDS = 30.0
HEALTH_DURING_EVALUATION_SECONDS = 0.5


def request(
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers=None,
    timeout: float = 10,
):
    req = urllib.request.Request(BASE + path, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def json_request(path: str, **kwargs):
    status, headers, body = request(path, **kwargs)
    content_type = headers.get_content_type()
    if content_type != "application/json":
        raise AssertionError(f"{path}: expected JSON, got {content_type} ({status})")
    return status, json.loads(body)


def wait_for_health() -> dict:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            status, health = json_request("/api/health")
            if status == 200:
                return health
            last_error = f"HTTP {status}"
        except Exception as exc:  # service may still be binding its socket
            last_error = str(exc)
        time.sleep(0.5)
    raise AssertionError(f"health did not become ready: {last_error}")


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def prepare_model() -> dict:
    status, _ = json_request("/api/model/prepare", method="POST", body=b"")
    if status not in (200, 202, 429):
        raise AssertionError(f"model prepare returned {status}")
    deadline = time.monotonic() + MODEL_TIMEOUT
    while time.monotonic() < deadline:
        status, health = json_request("/api/health")
        if status == 200 and health.get("model_state") == "ready":
            return health
        if health.get("model_state") == "failed" and not health.get("model_retry_remaining"):
            raise AssertionError("model preparation reached terminal failure")
        time.sleep(1)
    raise AssertionError("model preparation timed out")


def synthetic_csv(*, rows: int, segments: int) -> bytes:
    """Expand the tracked trajectory into bounded exact-duplicate stress fixtures."""
    source = list(
        csv.DictReader(
            (ROOT / "frontend/public/evaluation-synthetic-sample.csv").read_text(
                encoding="utf-8"
            ).splitlines()
        )
    )
    if not source or rows < 1 or segments < 1:
        raise AssertionError("synthetic stress fixture parameters are invalid")
    unique = []
    for segment in range(segments):
        for source_row in source:
            row = dict(source_row)
            row["icao24"] = f"{0xA10000 + segment:06x}"
            row["time"] = str(int(row["time"]) + segment * 3600)
            unique.append(row)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(source[0]))
    writer.writeheader()
    for index in range(rows):
        writer.writerow(unique[index % len(unique)])
    return output.getvalue().encode("utf-8")


def upload_csv(data: bytes, *, timeout: float = 40) -> tuple[dict, int, float]:
    boundary = "sadar-smoke-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="synthetic.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    started = time.perf_counter()
    status, headers, response_body = request(
        "/api/evaluations",
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    if headers.get_content_type() != "application/json":
        raise AssertionError("evaluation response was not JSON")
    evaluation = json.loads(response_body)
    if status != 200:
        raise AssertionError(f"sample evaluation returned {status}")
    if len(response_body) > MAX_RESPONSE_BYTES:
        raise AssertionError("evaluation exceeded the 8 MiB response gate")
    return evaluation, len(response_body), elapsed


def sample_upload() -> dict:
    sample = (ROOT / "frontend/public/evaluation-synthetic-sample.csv").read_bytes()
    evaluation, _, _ = upload_csv(sample)
    if evaluation.get("accepted_segments", 0) < 1 or not evaluation.get("results"):
        raise AssertionError("sample evaluation produced no accepted evidence")
    forbidden = {"label", "case_id", "case_ref", "operation_ref", "report"}
    if forbidden.intersection(evaluation["results"][0]):
        raise AssertionError("uploaded evidence leaked case or ground-truth fields")
    return evaluation


def assert_evaluation_shape(evaluation: dict, *, rows: int, segments: int) -> None:
    if evaluation.get("raw_rows") != rows:
        raise AssertionError(
            f"evaluation raw row mismatch: expected {rows}, observed {evaluation.get('raw_rows')}"
        )
    if evaluation.get("accepted_segments") != segments:
        raise AssertionError(
            "evaluation accepted segment mismatch: "
            f"expected {segments}, observed {evaluation.get('accepted_segments')}"
        )
    if len(evaluation.get("results", [])) != segments:
        raise AssertionError("evaluation result count did not match accepted segments")


def evaluation_performance() -> dict[str, float | int]:
    warm_data = synthetic_csv(rows=5_000, segments=10)
    warm_samples = []
    largest_response = 0
    for _ in range(10):
        evaluation, response_bytes, elapsed = upload_csv(warm_data)
        assert_evaluation_shape(evaluation, rows=5_000, segments=10)
        warm_samples.append(elapsed)
        largest_response = max(largest_response, response_bytes)
    warm_p95 = p95(warm_samples)
    if warm_p95 > WARM_EVALUATION_SECONDS:
        raise AssertionError(f"5,000-row evaluation p95 exceeded 10s gate: {warm_p95:.3f}s")

    maximum_data = synthetic_csv(rows=50_000, segments=25)
    outcome: dict[str, object] = {}

    def evaluate_maximum() -> None:
        try:
            outcome["value"] = upload_csv(maximum_data)
        except BaseException as exc:  # relay the worker failure to the smoke-test thread
            outcome["error"] = exc

    worker = threading.Thread(target=evaluate_maximum, name="maximum-evaluation-smoke")
    worker.start()
    health_samples = []
    while worker.is_alive():
        started = time.perf_counter()
        status, _ = json_request("/api/health")
        health_samples.append(time.perf_counter() - started)
        if status != 200:
            raise AssertionError("health failed during maximum evaluation")
        time.sleep(0.05)
    worker.join()
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    first_evaluation, response_bytes, first_elapsed = outcome["value"]  # type: ignore[misc]
    assert_evaluation_shape(first_evaluation, rows=50_000, segments=25)
    largest_response = max(largest_response, response_bytes)
    maximum_samples = [first_elapsed]
    for _ in range(2):
        evaluation, response_bytes, elapsed = upload_csv(maximum_data)
        assert_evaluation_shape(evaluation, rows=50_000, segments=25)
        largest_response = max(largest_response, response_bytes)
        maximum_samples.append(elapsed)
    if any(sample > MAX_EVALUATION_SECONDS for sample in maximum_samples):
        raise AssertionError(
            f"50,000-row evaluation exceeded 30s gate: {max(maximum_samples):.3f}s"
        )
    health_p95 = p95(health_samples or [0.0])
    if health_p95 > HEALTH_DURING_EVALUATION_SECONDS:
        raise AssertionError(
            f"health p95 during evaluation exceeded 500ms gate: {health_p95:.3f}s"
        )
    return {
        "warm_evaluation_p95_seconds": warm_p95,
        "maximum_evaluation_seconds": max(maximum_samples),
        "health_during_evaluation_p95_seconds": health_p95,
        "largest_evaluation_response_bytes": largest_response,
    }


def main() -> None:
    health = wait_for_health()
    base_only = os.environ.get("SADAR_SMOKE_BASE_ONLY") == "1"
    model_only = os.environ.get("SADAR_SMOKE_MODEL_ONLY") == "1"
    if base_only and model_only:
        raise AssertionError("base-only and model-only smoke modes are mutually exclusive")
    startup_seconds = None
    for key in ("release_id", "schema_version", "model_state", "evaluation_enabled"):
        if key not in health:
            raise AssertionError(f"health is missing {key}")
    if health["schema_version"] != 2:
        raise AssertionError(f"unexpected release schema: {health['schema_version']}")

    status, queue = json_request("/api/flights?limit=1&order=anomalous")
    if status != 200 or not isinstance(queue, list) or not queue:
        raise AssertionError("queue did not expose a smoke-test case")
    case_id = queue[0].get("case_id")
    if not isinstance(case_id, str) or not case_id.startswith("c_"):
        raise AssertionError("queue case_id does not satisfy schema v2")
    case = None
    read_p95 = None
    if not model_only:
        started_at = float(os.environ.get("SADAR_SMOKE_STARTED_AT", str(time.time())))
        startup_seconds = time.time() - started_at
        if startup_seconds > 10:
            raise AssertionError(f"startup exceeded 10s gate: {startup_seconds:.3f}s")
        status, case = json_request(f"/api/flights/{case_id}")
        if status != 200 or case.get("case_id") != case_id:
            raise AssertionError("case response is not bound to the requested identity")
        read_samples = []
        for _ in range(100):
            started = time.perf_counter()
            status, repeated = json_request(f"/api/flights/{case_id}")
            read_samples.append(time.perf_counter() - started)
            if status != 200 or repeated.get("case_id") != case_id:
                raise AssertionError("repeated case read failed")
        read_p95 = p95(read_samples)
        if read_p95 > 0.250:
            raise AssertionError(f"read p95 exceeded 250ms gate: {read_p95:.3f}s")

        status, headers, body = request(f"/case/{case_id}")
        if status != 200 or headers.get_content_type() != "text/html" or b"<div id=\"root\"></div>" not in body:
            raise AssertionError("deep SPA route did not return the built application shell")

        status, headers, _ = request("/api/not-a-real-route")
        if status != 404 or headers.get_content_type() != "application/json":
            raise AssertionError("unknown API route must remain a JSON 404")

    performance = {}
    if not base_only:
        if case is None:
            status, case = json_request(f"/api/flights/{case_id}")
            if status != 200:
                raise AssertionError("model smoke could not load its case")
        health = prepare_model()
        payload = json.dumps(
            {"case_id": case_id, "kind": "zone_violation", "intensity": 0.0, "onset": 0.5}
        ).encode()
        simulation_samples = []
        for _ in range(20):
            started = time.perf_counter()
            status, simulation = json_request(
                "/api/simulate",
                method="POST",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            simulation_samples.append(time.perf_counter() - started)
            if status != 200 or simulation.get("case_id") != case_id:
                raise AssertionError("zero-intensity simulation failed")
            if simulation.get("release_id") not in (None, health["release_id"]):
                raise AssertionError("simulation release provenance drifted")
            if abs(float(simulation["window_score"]) - float(case["window_score"])) > 1e-12:
                raise AssertionError("zero-intensity simulation score drifted from baked evidence")
        simulation_p95 = p95(simulation_samples)
        if simulation_p95 > 2:
            raise AssertionError(f"simulation p95 exceeded 2s gate: {simulation_p95:.3f}s")
        evaluation = sample_upload()
        if evaluation.get("release_id") != health["release_id"]:
            raise AssertionError("evaluation release provenance drifted")
        performance = evaluation_performance()
    else:
        simulation_p95 = None

    print(
        "container smoke: ok "
        + json.dumps(
            {
                "release_id": health["release_id"],
                "case_id": case_id,
                "startup_seconds": (
                    round(startup_seconds, 4) if startup_seconds is not None else None
                ),
                "read_p95_seconds": round(read_p95, 4) if read_p95 is not None else None,
                "simulation_p95_seconds": (
                    round(simulation_p95, 4) if simulation_p95 is not None else None
                ),
                **{
                    key: round(value, 4) if isinstance(value, float) else value
                    for key, value in performance.items()
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"container smoke: {exc}", file=sys.stderr)
        raise SystemExit(1)
