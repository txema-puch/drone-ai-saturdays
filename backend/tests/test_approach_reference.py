import math

import numpy as np
import pandas as pd
import pytest

from backend.core.approach import assess_approach
from backend.core.approach_geometry import EARTH_RADIUS_M, load_lemd_geometry
from backend.core.approach_reference import (
    dumps_reference,
    fit_reference,
    load_approach_reference,
    lookup_reference,
    reference_digest,
    validate_reference,
)


def _attempt(number: int, *, velocity: float = 70.0):
    runway = load_lemd_geometry().thresholds["18L"]
    along = np.linspace(12_000, 100, 80)
    bearing = math.radians(runway.true_bearing_deg)
    east = -along * math.sin(bearing)
    north = -along * math.cos(bearing)
    frame = pd.DataFrame({
        "time": 1_514_764_800 + number * 10_000 + np.arange(80) * 10,
        "lat": runway.lat + np.degrees(north / EARTH_RADIUS_M),
        "lon": runway.lon + np.degrees(east / (EARTH_RADIUS_M * np.cos(np.radians(runway.lat)))),
        "baroaltitude": runway.elevation_m + np.tan(np.radians(3.0)) * along,
        "velocity": velocity,
        "vertrate": -3.0,
        "heading": runway.true_bearing_deg,
        "onground": False,
    })
    return {
        "attempt_id": f"a-{number}",
        "frame": frame,
        "direction": "18",
        "geometry_runway": "18L",
        "speed_class": "unknown",
    }


def _reference():
    return fit_reference(
        [_attempt(index) for index in range(25)],
        fit_fold="train",
        cohort={"fixture": True},
    )


def test_reference_fit_rejects_non_train_folds():
    with pytest.raises(ValueError, match="train fold"):
        fit_reference([], fit_fold="val", cohort={})


def test_reference_fit_accepts_read_only_missingness_masks():
    item = _attempt(1)
    mask = np.zeros(len(item["frame"]), dtype=bool)
    mask.setflags(write=False)
    item["frame"]["velocity_missing"] = mask
    item["frame"]["vertrate_missing"] = mask
    reference = fit_reference(
        [item], fit_fold="train", cohort={"fixture": True},
        minimum_attempts=1, minimum_samples=1,
    )
    assert reference["accepted_attempts"] == 1


def test_reference_serialization_and_digest_are_stable():
    first = _reference()
    second = _reference()
    assert dumps_reference(first) == dumps_reference(second)
    assert first["artifact_sha256"] == reference_digest(first) == second["artifact_sha256"]
    validate_reference(first)


def test_published_reference_loads_and_is_train_only():
    reference = load_approach_reference()
    assert reference["fit_fold"] == "train"
    assert reference["stratification"]["calendar_year"]["status"] == "pass"


def test_unknown_speed_class_is_an_explicit_fallback():
    reference = _reference()
    match = lookup_reference(reference, direction="18", speed_class="jet", along_track_m=2_000)
    assert match is not None
    assert match["fallback"] == "unknown_speed_class"


def test_empirical_reference_flags_a_persistent_speed_exceedance():
    reference = _reference()
    result = assess_approach(_attempt(99, velocity=120.0)["frame"], reference=reference)
    assert "observed_ground_speed_envelope" in result["failed_criteria"]
    assert result["reference"]["artifact_sha256"] == reference["artifact_sha256"]


def test_empirical_reference_not_fixed_limit_drives_descent_verdict():
    reference = _reference()
    attempt = _attempt(99)["frame"]
    attempt["vertrate"] = -5.0

    result = assess_approach(attempt, reference=reference)

    assert "observed_descent_rate" in result["failed_criteria"]
    criterion = next(
        item for item in result["criteria"] if item["name"] == "observed_descent_rate"
    )
    assert criterion["reference_source"] == "empirical_train_envelope"
    assert criterion["evidence"][0]["limit"] == -3.0
