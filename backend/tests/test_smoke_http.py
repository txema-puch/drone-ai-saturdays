from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke-http.py"
SPEC = importlib.util.spec_from_file_location("sadar_smoke_http", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_boundary_fixture_is_bounded_and_exercises_25_segments_and_50k_rows():
    data = smoke.synthetic_csv(rows=50_000, segments=25)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))

    assert len(rows) == 50_000
    assert len({row["icao24"] for row in rows}) == 25
    assert len({(row["icao24"], row["time"]) for row in rows}) == 25 * 31
    assert len(data) < 10 * 1024 * 1024


def test_smoke_percentile_uses_nearest_rank_p95():
    assert smoke.p95([float(value) for value in range(1, 21)]) == 19.0
