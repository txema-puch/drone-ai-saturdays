# ============================================================================
# REFERENCE ARTIFACT — NOT part of the sadar (our) package. Do not import.
# ============================================================================
#
# Source : SADAR ("Smart Anomaly Detection for Aviation Routes"), a parallel
#          course project by a teammate, on the SAME data (OpenSky LEMD,
#          ~18 days 2017-2020, ~20k trajectories) and SAME approach
#          (LSTM / VAE-LSTM autoencoder anomaly scorer).
#          src/sadar/eval/synthetic.py @ huggingface.co/spaces/devrup404/sadar
# License: MIT (per the SADAR repo README front-matter).
# Vendored: 2026-05-31, verbatim, for Phase 7 reference. See
#          backend/docs/ml/07-eval-prep.md > "Reference implementation —
#          SADAR synthetic bench" for the borrow-vs-override analysis.
#
# WHY THIS IS HERE: the *engineering scaffold* below is a clean, ready
# skeleton for our own inject_anomalies(...) — the ramp function, the onset
# masks (which double as ground-truth labels for DETECTION LATENCY), the
# unscale->perturb->rescale dance, and the per-type builder pattern. BORROW
# the scaffold. Do NOT borrow the parameter choices: our calibrated mix
# (07-eval-prep.md §6) diverges deliberately — asymmetric upward altitude
# (not symmetric ±300m), sustained loiter 60-300s (not just micro-hover),
# softened+demoted speed spike (≤10% of mix), zone-violation at ~40%, plus
# two types SADAR lacks (final-approach intercept, multi-drone). SADAR's
# symmetric altitude / aggressive speed are exactly the "too easy / wrong
# shape" failure mode 07-eval-prep.md was written to prevent.
#
# FEATURE-CONTRACT RECONCILIATION (2026-06, post-#22 merge — Phase 3 closed):
# This file uses SADAR's feature names. OUR shipped contract differs
# (backend/core/preprocessing.py):
#   AE_FEATURES     = [lat, lon, baroaltitude, velocity, vertrate,
#                      hdg_sin, hdg_cos, onground]      # 8 features
#   SCALER_FEATURES = [lat, lon, baroaltitude, velocity, vertrate]  # only these scaled
# When adapting into our inject_anomalies(...):
#   - There is NO x_rel/y_rel. Position is RAW lat/lon (degrees). A metres-based
#     lateral shift must convert m->deg (Δlat≈m/111320, Δlon≈m/(111320·cos lat)),
#     OR bind to a Phase-5 runway-relative/zone feature (share geometry with the
#     APW/geofence Layer-3 baseline, D-008).
#   - Heading channels are hdg_sin/hdg_cos (not sin_hdg/cos_hdg).
#   - 'onground' is new (SADAR lacks it): keep it consistent (airborne hover -> 0).
#   - unscale->perturb->rescale applies to the 5 SCALER_FEATURES only;
#     hdg_sin/hdg_cos/onground are perturbed in raw space.
#   - Bind indices via feature_indices(AE_FEATURES, names) (below) — never hard-code;
#     survives Phase 5 adding/reordering features.
#   - T and the fitted scaler are Phase-6 artifacts (to_sequences(df, T, scaler));
#     run injections AFTER the train-only split, never with make_scaler() (unfitted).
# ============================================================================

from __future__ import annotations

import numpy as np

KINDS = ["route_deviation", "altitude", "speed", "holding", "freeze"]


def feature_indices(feature_columns: list[str], names: list[str]) -> list[int]:
    return [feature_columns.index(name) for name in names]


def unscale(windows: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return windows.astype(np.float64) * std + mean


def rescale(windows: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((windows - mean) / std).astype(np.float32)


def onset_index(length: int, onset_fraction: float) -> int:
    return int(np.clip(round(length * onset_fraction), 0, length - 1))


def _ramp(length: int, start: int) -> np.ndarray:
    ramp = np.zeros(length, dtype=np.float64)
    if start >= length - 1:
        ramp[length - 1 :] = 1.0
    else:
        ramp[start:] = np.linspace(0.0, 1.0, length - start)
    return ramp


def _mask_from(length: int, start: int, count: int) -> np.ndarray:
    # NOTE (ours): this boolean mask marks the post-onset steps. SADAR uses it
    # to compute median DETECTION LATENCY = first post-onset step whose per-step
    # score crosses threshold, minus onset. That latency metric is the part of
    # their bench most worth keeping — D-005's metric stack doesn't yet name it.
    mask = np.zeros((count, length), dtype=bool)
    mask[:, start:] = True
    return mask


def route_deviation(
    batch: np.ndarray,
    x_index: int,
    y_index: int,
    magnitude_m: float,
    onset_fraction: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    out = batch.copy()
    n, length, _ = out.shape
    start = onset_index(length, onset_fraction)
    ramp = _ramp(length, start)
    angle = rng.uniform(0.0, 2.0 * np.pi, size=n)
    out[:, :, x_index] += (np.cos(angle) * magnitude_m)[:, None] * ramp[None, :]
    out[:, :, y_index] += (np.sin(angle) * magnitude_m)[:, None] * ramp[None, :]
    return out, _mask_from(length, start, n)


def altitude_anomaly(
    batch: np.ndarray,
    altitude_index: int,
    magnitude_m: float,
    onset_fraction: float,
    rng: np.random.Generator,
    vertrate_index: int | None = None,
    step_seconds: float = 10.0,
) -> tuple[np.ndarray, np.ndarray]:
    # OVERRIDE FOR OURS: signs = rng.choice([-1, 1]) makes this SYMMETRIC.
    # 07-eval-prep.md §6 calls for asymmetric upward (+200..+1500m @ 70%,
    # -100m @ 30%). Replace the `signs` line accordingly when we adapt this.
    out = batch.copy()
    n, length, _ = out.shape
    start = onset_index(length, onset_fraction)
    ramp = _ramp(length, start)
    signs = rng.choice([-1.0, 1.0], size=n)
    offset = signs[:, None] * magnitude_m * ramp[None, :]
    out[:, :, altitude_index] += offset
    if vertrate_index is not None:
        change = np.zeros_like(offset)
        change[:, 1:] = np.diff(offset, axis=1) / step_seconds
        out[:, :, vertrate_index] += change
    return out, _mask_from(length, start, n)


def speed_anomaly(
    batch: np.ndarray,
    velocity_index: int,
    factor: float,
    onset_fraction: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    out = batch.copy()
    n, length, _ = out.shape
    start = onset_index(length, onset_fraction)
    out[:, start:, velocity_index] = np.clip(out[:, start:, velocity_index] * factor, 0.0, None)
    return out, _mask_from(length, start, n)


def sensor_freeze(
    batch: np.ndarray,
    onset_fraction: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    # Transponder/sensor freeze: hold every feature constant from onset.
    out = batch.copy()
    n, length, _ = out.shape
    start = onset_index(length, onset_fraction)
    out[:, start:, :] = out[:, start : start + 1, :]
    return out, _mask_from(length, start, n)


def holding_pattern(
    batch: np.ndarray,
    x_index: int,
    y_index: int,
    sin_index: int,
    cos_index: int,
    velocity_index: int,
    onset_fraction: float,
    turn_period_seconds: float,
    rng: np.random.Generator,
    vertrate_index: int | None = None,
    step_seconds: float = 10.0,
) -> tuple[np.ndarray, np.ndarray]:
    # Geometrically-consistent 360deg loiter: integrates a constant-omega
    # heading into x/y displacement, keeps sin/cos heading consistent. This is
    # the cleanest part of the bench and the closest match to our "sustained
    # loiter" type — but SADAR parameterises by turn-period only; we also want
    # a low-speed station-keeping variant (speed<2 m/s, position sigma<30m).
    out = batch.copy()
    n, length, _ = out.shape
    start = onset_index(length, onset_fraction)
    span = length - start

    speed = np.clip(out[:, start, velocity_index], 0.0, None)
    heading0 = np.arctan2(out[:, start, sin_index], out[:, start, cos_index])
    omega = 2.0 * np.pi / turn_period_seconds
    elapsed = np.arange(span) * step_seconds
    heading = heading0[:, None] + omega * elapsed[None, :]

    east_step = speed[:, None] * step_seconds * np.sin(heading)
    north_step = speed[:, None] * step_seconds * np.cos(heading)
    zero = np.zeros((n, 1))
    east = np.concatenate([zero, np.cumsum(east_step[:, :-1], axis=1)], axis=1)
    north = np.concatenate([zero, np.cumsum(north_step[:, :-1], axis=1)], axis=1)

    out[:, start:, x_index] = out[:, start, x_index][:, None] + east
    out[:, start:, y_index] = out[:, start, y_index][:, None] + north
    out[:, start:, sin_index] = np.sin(heading)
    out[:, start:, cos_index] = np.cos(heading)
    if vertrate_index is not None:
        out[:, start:, vertrate_index] = 0.0
    return out, _mask_from(length, start, n)


def build_cases(
    normal_unscaled: np.ndarray,
    indices: dict,
    onset_fraction: float,
    step_seconds: float,
    rng: np.random.Generator,
    synthetic_cfg: dict,
) -> list[tuple]:
    # The driver: builds (kind, label, windows, mask) tuples per intensity.
    # Our adaptation keeps this shape but reweights the mix per 07-eval-prep §6
    # (zone ~40%, speed <=10%) and adds final-approach-intercept + multi-drone.
    cases = []
    for magnitude in synthetic_cfg["route_deviation"]["magnitudes_m"]:
        windows, mask = route_deviation(
            normal_unscaled, indices["x_rel"], indices["y_rel"], magnitude, onset_fraction, rng
        )
        cases.append(("route_deviation", f"{magnitude:g} m", windows, mask))
    for magnitude in synthetic_cfg["altitude"]["magnitudes_m"]:
        windows, mask = altitude_anomaly(
            normal_unscaled, indices["baroaltitude"], magnitude, onset_fraction, rng,
            indices.get("vertrate"), step_seconds,
        )
        cases.append(("altitude", f"{magnitude:g} m", windows, mask))
    for factor in synthetic_cfg["speed"]["factors"]:
        windows, mask = speed_anomaly(
            normal_unscaled, indices["velocity"], factor, onset_fraction, rng
        )
        cases.append(("speed", f"x{factor:g}", windows, mask))
    for period in synthetic_cfg["holding"]["turn_periods_s"]:
        windows, mask = holding_pattern(
            normal_unscaled, indices["x_rel"], indices["y_rel"], indices["sin_hdg"],
            indices["cos_hdg"], indices["velocity"], onset_fraction, period, rng,
            indices.get("vertrate"), step_seconds,
        )
        cases.append(("holding", f"{period:g} s/turn", windows, mask))
    if synthetic_cfg["freeze"]["enabled"]:
        windows, mask = sensor_freeze(normal_unscaled, onset_fraction, rng)
        cases.append(("freeze", "stuck", windows, mask))
    return cases
