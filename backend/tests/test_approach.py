import math

import numpy as np
import pandas as pd

from sadar.approach.assessment import (
    assess_approach,
    assess_operation,
    canonical_observations,
    extract_approach_attempts,
    infer_runway,
)
from sadar.approach.geometry import EARTH_RADIUS_M, load_lemd_geometry


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
    assert result["attempt"]["outcome"] == "final_gate_observed"
    assert len(result["provenance"]["config_sha256"]) == 64
    assert len(result["provenance"]["reconstruction_policy_sha256"]) == 64


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


def test_altitude_rate_conflict_abstains_only_barometric_altitude_channel():
    frame = _fixture()
    frame.loc[40, "baroaltitude"] += 1_000
    result = assess_approach(frame)
    assert result["status"] == "partial_observation"
    assert result["reasons"] == []
    assert result["quality"]["channel_advisories"] == {
        "barometric_altitude": ["altitude_rate_conflict"]
    }
    path = next(item for item in result["criteria"] if item["name"] == "barometric_path_proxy")
    assert path["status"] == "not_observed"


def test_late_track_correction_uses_ground_track_gate():
    result = assess_approach(_fixture(track_offset=25.0))
    assert "late_track_correction" in result["failed_criteria"]


def test_observed_touchdown_is_an_outcome_not_a_failed_criterion():
    frame = _fixture()
    frame.loc[frame.index[-3:], "onground"] = True
    result = assess_approach(frame)
    assert result["attempt"]["outcome"] == "landing_observed"
    assert result["maneuvers"][0]["name"] == "landing_observed"


def test_descend_then_climb_is_reported_as_go_around():
    frame = _fixture()
    low = 55
    frame["baroaltitude"] = np.r_[
        np.linspace(800.0, 150.0, low + 1),
        np.linspace(180.0, 650.0, len(frame) - low - 1),
    ]
    result = assess_approach(frame)
    assert result["attempt"]["outcome"] == "go_around"
    assert result["maneuvers"][0]["name"] == "go_around"


def test_post_go_around_turn_does_not_create_failed_criterion_evidence():
    frame = _fixture()
    low = 55
    frame["baroaltitude"] = np.r_[
        np.linspace(800.0, 150.0, low + 1),
        np.linspace(180.0, 650.0, len(frame) - low - 1),
    ]
    frame.loc[low + 1:, "heading"] = (frame.loc[low + 1:, "heading"] + 45) % 360

    result = assess_approach(frame)

    assert result["attempt"]["outcome"] == "go_around"
    assert result["attempt"]["criterion_observed_samples"] == low + 1
    assert "late_track_correction" not in result["failed_criteria"]
    correction = next(
        item for item in result["criteria"] if item["name"] == "late_track_correction"
    )
    assert correction["evidence"] == []


def test_ground_contact_followed_by_observed_climb_is_touch_and_go():
    frame = _fixture()
    contact = 70
    frame.loc[contact, "onground"] = True
    frame.loc[contact + 1:, "baroaltitude"] = np.linspace(
        frame.loc[contact, "baroaltitude"] + 20,
        frame.loc[contact, "baroaltitude"] + 420,
        len(frame) - contact - 1,
    )

    result = assess_approach(frame)

    assert result["attempt"]["outcome"] == "touch_and_go"
    assert result["maneuvers"][0]["name"] == "touch_and_go"
    assert result["attempt"]["criterion_observed_samples"] == contact + 1


def test_later_corridor_reentry_becomes_a_second_attempt():
    first = _fixture().iloc[:65].copy()
    second = _fixture().copy()
    second["time"] += int(first["time"].iloc[-1] - second["time"].iloc[0] + 600)
    operation = pd.concat([first, second], ignore_index=True)
    attempts = extract_approach_attempts(operation)
    result = assess_operation(operation, operation_id="fixture")
    assert len(attempts) == 2
    assert result["attempt_count"] == 2
    assert [item["operation_id"] for item in result["attempts"]] == [
        "fixture:attempt-1", "fixture:attempt-2"
    ]


def test_outcome_extension_does_not_merge_a_prompt_corridor_reentry():
    first = _fixture().iloc[:65].copy()
    exit_rows = first.iloc[-3:].copy()
    exit_rows["time"] = np.arange(1, 4) * 10 + int(first["time"].iloc[-1])
    exit_rows["lat"] = 41.0
    exit_rows["lon"] = -2.5
    second = _fixture().copy()
    second["time"] += int(exit_rows["time"].iloc[-1] - second["time"].iloc[0] + 10)
    operation = pd.concat([first, exit_rows, second], ignore_index=True)

    attempts = extract_approach_attempts(operation)
    result = assess_operation(operation, operation_id="prompt-reentry")

    assert len(attempts) == 2
    assert attempts[0]["time"].max() < attempts[1]["time"].min()
    assert result["attempt_count"] == 2
