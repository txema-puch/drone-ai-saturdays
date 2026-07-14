import math

import numpy as np
import pandas as pd

from backend.core.approach import assess_approach, canonical_observations, infer_runway
from backend.core.approach_geometry import EARTH_RADIUS_M, load_lemd_geometry


def _fixture(runway_name="18L", *, cross_m=0.0, descent_rate=-3.0, track_offset=0.0):
    runway = load_lemd_geometry().thresholds[runway_name]
    along = np.linspace(12_000, 100, 80)
    bearing = math.radians(runway.true_bearing_deg)
    east = -along * math.sin(bearing) + cross_m * math.cos(bearing)
    north = -along * math.cos(bearing) - cross_m * math.sin(bearing)
    lat = runway.lat + np.degrees(north / EARTH_RADIUS_M)
    lon = runway.lon + np.degrees(east / (EARTH_RADIUS_M * np.cos(np.radians(runway.lat))))
    height = np.tan(np.radians(3.0)) * along
    return pd.DataFrame({
        "time": 1_700_000_000 + np.arange(80) * 10,
        "lat": lat,
        "lon": lon,
        "baroaltitude": runway.elevation_m + height,
        "velocity": np.linspace(90, 65, 80),
        "vertrate": descent_rate,
        "heading": (runway.true_bearing_deg + track_offset) % 360,
        "onground": False,
    })


def test_canonical_observations_excludes_interpolated_position_rows():
    frame = _fixture().iloc[:4].copy()
    frame["lat_missing"] = [False, True, False, False]
    frame["lon_missing"] = [False, True, False, False]
    assert canonical_observations(frame)["time"].tolist() == [
        frame.iloc[0]["time"], frame.iloc[2]["time"], frame.iloc[3]["time"]
    ]


def test_inference_resolves_a_straight_in_runway():
    result = infer_runway(_fixture("18L"))
    assert result["direction"] == "18"
    assert result["geometry_runway"] == "18L"
    assert result["specificity"] in {"exact", "direction"}


def test_stable_fixture_is_partial_until_reference_is_fitted():
    result = assess_approach(_fixture())
    assert result["status"] == "partial_observation"
    assert result["failed_criteria"] == []
    assert result["runway_inference"]["direction"] == "18"


def test_persistent_lateral_deviation_recommends_review():
    result = assess_approach(_fixture(cross_m=900.0))
    assert result["status"] == "review_required"
    assert "lateral_path_proxy" in result["failed_criteria"]


def test_coverage_gap_abstains_instead_of_interpolating():
    frame = _fixture()
    frame.loc[40:, "time"] += 120
    result = assess_approach(frame)
    assert result["status"] == "not_assessable"
    assert "approach_coverage_gap" in result["reasons"]


def test_late_track_correction_uses_ground_track_gate():
    result = assess_approach(_fixture(track_offset=25.0))
    assert "late_track_correction" in result["failed_criteria"]
