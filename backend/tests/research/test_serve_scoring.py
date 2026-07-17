import numpy as np
import pandas as pd

from sadar_research.trajectory_anomaly.pipeline.preprocessing import MASKED_FEATURES
from sadar_research.trajectory_anomaly.evaluation import scoring


def test_zero_intensity_scores_the_untouched_clean_segment(monkeypatch):
    n = 8
    segment = pd.DataFrame({
        "segment_id": ["stable#1"] * n,
        "time": np.arange(n) * 10,
        "lat": np.linspace(40.4, 40.5, n),
        "lon": np.linspace(-3.6, -3.5, n),
        "baroaltitude": np.linspace(800, 100, n),
        "velocity": np.linspace(90, 60, n),
        "vertrate": np.full(n, -4.0),
        "heading": np.full(n, 180.0),
        "hdg_sin": np.zeros(n),
        "hdg_cos": np.full(n, -1.0),
        "onground": [True, True, False, False, False, False, True, True],
        "dist_to_runway_m": np.linspace(5000, 100, n),
    })
    for feature in MASKED_FEATURES:
        segment[f"{feature}_missing"] = feature == "velocity"

    captured = {}

    def fake_score_frame(frame, *_args):
        captured["frame"] = frame.copy()
        return {
            "window_score": 0.25,
            "step_scores": [0.0] * n,
            "path": [],
            "channels": {},
            "valid_steps": 0,
        }

    monkeypatch.setattr(scoring, "score_frame", fake_score_frame)
    result = scoring.simulate_segment(
        segment,
        "altitude_high",
        0.0,
        0.5,
        scaler=None,
        model=None,
        T=n,
        threshold=0.2,
        step_threshold=0.1,
        cohort_scores=np.array([0.1, 0.3]),
    )

    pd.testing.assert_frame_equal(captured["frame"], segment.reset_index(drop=True))
    assert result["window_score"] == 0.25
    assert result["onset_index"] == scoring.onset_index(n, 0.5)
