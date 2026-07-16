import json

import numpy as np

from sadar.approach.geometry import (
    GEOMETRY_PATH,
    circular_difference_deg,
    load_lemd_geometry,
    runway_relative,
)


def test_aip_geometry_is_complete_and_source_bound():
    geometry = load_lemd_geometry()
    assert geometry.schema_version == "lemd_geometry_v1"
    assert geometry.effective_date == "2026-07-09"
    assert geometry.source["publisher"] == "ENAIRE AIS España"
    assert len(geometry.artifact_sha256) == 64
    assert {runway.designator for runway in geometry.landing_thresholds} == {
        "18L", "18R", "32L", "32R"
    }


def test_runway_relative_axes_are_oriented_for_final_approach():
    runway = load_lemd_geometry().thresholds["18L"]
    # North of an 18 runway is before the threshold; east is lateral displacement.
    relative = runway_relative(
        np.array([runway.lat + 0.05, runway.lat + 0.05]),
        np.array([runway.lon, runway.lon + 0.01]),
        runway,
    )
    assert relative.along_track_m[0] > 5_000
    assert abs(relative.cross_track_m[0]) < 50
    assert abs(relative.cross_track_m[1]) > 500


def test_circular_difference_handles_track_wrap():
    values = circular_difference_deg(np.array([359.0, 1.0, 180.0]), 0.0)
    assert values.tolist() == [1.0, 1.0, 180.0]


def test_geometry_artifact_is_strict_json():
    geometry = load_lemd_geometry()
    payload = json.loads(GEOMETRY_PATH.read_text())
    assert payload["source"]["sha256"] == geometry.source["sha256"]
