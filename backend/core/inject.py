"""Phase 6 — Generator A: §6-calibrated synthetic anomaly injection (Layer 2 of D-008).

Generator A is a Phase-6 PREREQUISITE, not Phase-7 prep: D-006 model selection
(`AE val AUROC ≥ IF val AUROC + 0.03`) and the threshold both score against INJECTED
anomalies — there are no real labels in cycle 3 (D-008 OQ#1). So the bench must exist and
run on VAL inside Phase 6. It is FROZEN after Phase 6 (seed + §6 params + the TRAIN-fit
scaler + T + this module's version) so the Phase-7 TEST run is byte-identical.

CONTRACT (the structural recompute-not-perturb guarantee — see SADAR scaffold header +
`features.apply_segment_derivations`):

    perturb MEASURED primitives on the per-segment frame  (raw space — no unscale needed)
        └─► features.apply_segment_derivations(seg)        (replay hdg_sin/cos + dist)
              └─► set injected timesteps' *_missing = 0     (synthetic-but-present)
                    └─► to_sequences(seg, T, TRAIN scaler)  (window + scale, caller side)

Perturbing a DERIVED channel (`dist_to_runway_m`, `hdg_sin/cos`) directly is silently
reverted by the replay — only the measured handles (`lat`/`lon` for position/zone,
`heading` for turns, `baroaltitude`/`velocity`/`vertrate` for kinematics) are touched.

INJECT ON VAL/TEST ONLY — never train (the AE trains on TRAIN-normal). `assert_injectable`
enforces this AND that the scaler is TRAIN-fitted (never `make_scaler()` unfitted).

§6 CALIBRATION (07-eval-prep.md §6 — drone-incident-derived, deliberately diverges from
SADAR's symmetric-altitude / aggressive-speed defaults):

    zone_violation            0.40   reroute through the airport exclusion zone (lat/lon)
                                     [Phase-7 D-012: re-weighted OUT of DEFAULT_MIX — APW owns
                                      zone under the D-010 reframe; kept as a diagnostic kind]
    altitude_high             0.20   asymmetric: +200..+1500 m @70%, −50..−100 m @30%
    sustained_loiter          0.20   60-300 s station-keeping: speed<2 m/s, σ<30 m
    final_approach_intercept  0.10   cross the arrival corridor at 50-300 m AGL near a rwy
    speed_spike               0.10   softened+demoted: ×1.5-2.0 for one grid step
    (the 0.40/0.20/0.20/0.10/0.10 weights are the Phase-6 MIX_V1_WITH_ZONE; Phase-7 DEFAULT_MIX
     drops zone and renormalizes the 4 dynamic types — see MIX_V1_WITH_ZONE / DEFAULT_MIX below)
    (multi_drone)               —    DEFERRED: a multi-TRACK phenomenon; a per-segment AE
                                     scores one trajectory at a time, so it cannot be a
                                     single labeled window. Belongs to a co-occurrence
                                     detector / Phase-7 qualitative review, not Generator A.

Leaf imports (numpy/pandas + the feature contract + geo + the derivation replay). No torch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.core.features import apply_segment_derivations
from backend.core.geo import LEMD_RUNWAYS, distance_to_closest_runway
from backend.core.preprocessing import (
    AE_FEATURES,
    MASKED_FEATURES,
    SCALER_FEATURES,
    to_sequences,
    to_sequences_loss_mask,
)

# ── §6 calibrated mix (the 5 single-trajectory types) ─────────────────────────
# `zone_violation` stays a first-class injectable kind (requestable explicitly for the
# per-type diagnostic on val/test), but it is OUT of the default mix as of D-012 — see below.
INJECTION_KINDS: tuple[str, ...] = (
    "zone_violation", "altitude_high", "sustained_loiter",
    "final_approach_intercept", "speed_spike",
)

# The ORIGINAL §6 pre-reframe mix (zone @ 40%), preserved verbatim so the Phase-6 val
# bake-off (07-train.md §4) stays exactly reproducible. Do NOT delete — it is the
# pre-registered Phase-6 record. Phase 7 uses DEFAULT_MIX (zone re-weighted out) instead.
MIX_V1_WITH_ZONE: dict[str, float] = {
    "zone_violation": 0.40,
    "altitude_high": 0.20,
    "sustained_loiter": 0.20,
    "final_approach_intercept": 0.10,
    "speed_spike": 0.10,
}

# Phase-7 mix (D-012, signed-off bench deviation). `zone_violation` is re-weighted OUT of the
# headline mix: under the D-010 manned-conformance reframe the deployed APW safety net — not the
# reconstruction AE — owns zone/position violations (07-train.md §4b; 07-eval-prep.md §"Post-reframe
# reconciliation"). zone was a §6 *drone-era* category and, at 40%, the main drag on the synthetic
# mean for a model not responsible for it. The 4 remaining DYNAMIC types (the AE's actual remit)
# are renormalized proportionally: {alt 0.20, loiter 0.20, intercept 0.10, speed 0.10} / 0.60.
# zone is STILL scored as a standalone out-of-remit diagnostic in Phase 7 (reported, not in mix).
DEFAULT_MIX: dict[str, float] = {
    "altitude_high": 1.0 / 3.0,
    "sustained_loiter": 1.0 / 3.0,
    "final_approach_intercept": 1.0 / 6.0,
    "speed_spike": 1.0 / 6.0,
}

GRID_S = 10.0                 # the 10 s feed cadence (Phase 3 resample grid)
DEFAULT_ONSET_FRACTION = 0.5  # anomaly begins mid-segment (leaves a normal prefix)
_M_PER_DEG_LAT = 111_320.0    # metres per degree latitude (lon scaled by cos(lat))


# ── firewall guard ────────────────────────────────────────────────────────────

def assert_injectable(scaler, fold: str) -> None:
    """The CRITICAL inject-bench firewall guard. Injection runs on VAL/TEST only, with the
    TRAIN-fit scaler — never on train, never with an unfitted `make_scaler()`.
    """
    assert fold in ("val", "test"), (
        f"inject is VAL/TEST only; got fold={fold!r}. TRAIN must stay clean — the AE "
        "trains on TRAIN-normal and would otherwise learn the injection distribution."
    )
    assert getattr(scaler, "mean_", None) is not None, (
        "inject needs a TRAIN-FIT StandardScaler (the same one to_sequences uses); got an "
        "unfitted scaler. Fit on TRAIN first, then inject on val/test."
    )


# ── onset ramp (borrowed from the SADAR scaffold) ─────────────────────────────

def onset_index(n: int, fraction: float = DEFAULT_ONSET_FRACTION) -> int:
    return int(np.clip(round(n * fraction), 0, max(n - 1, 0)))


def _ramp(n: int, start: int) -> np.ndarray:
    """0 before `start`, then linear 0→1 to the end (a gradual, realistic onset)."""
    ramp = np.zeros(n, dtype="float64")
    if start >= n - 1:
        ramp[n - 1:] = 1.0
    else:
        ramp[start:] = np.linspace(0.0, 1.0, n - start)
    return ramp


# ── the 5 single-trajectory perturbations (raw space, measured columns only) ──

def _zone_violation(seg: pd.DataFrame, onset: int, rng: np.random.Generator) -> None:
    """Lateral reroute (1-3 km) in a random bearing, ramped from onset — pushes the track
    off its corridor and into/through the exclusion zone. `dist_to_runway_m` follows via the
    replay (the shared zone geometry the APW/geofence Layer-3 baseline also binds to)."""
    n = len(seg)
    mag = rng.uniform(1_000.0, 3_000.0)
    bearing = rng.uniform(0.0, 2.0 * np.pi)
    ramp = _ramp(n, onset)
    lat = seg["lat"].to_numpy()
    dn = np.cos(bearing) * mag * ramp           # metres north
    de = np.sin(bearing) * mag * ramp           # metres east
    seg["lat"] = lat + dn / _M_PER_DEG_LAT
    seg["lon"] = seg["lon"].to_numpy() + de / (_M_PER_DEG_LAT * np.cos(np.radians(lat)))


def _altitude_high(seg: pd.DataFrame, onset: int, rng: np.random.Generator) -> None:
    """Asymmetric altitude excursion (§6): up +200..+1500 m @70%, down −50..−100 m @30%.
    Vertrate adjusted by d(offset)/dt so the climb/descent is kinematically consistent."""
    n = len(seg)
    if rng.random() < 0.7:
        mag = rng.uniform(200.0, 1_500.0)
    else:
        mag = -rng.uniform(50.0, 100.0)
    offset = mag * _ramp(n, onset)
    seg["baroaltitude"] = seg["baroaltitude"].to_numpy() + offset
    dvr = np.zeros(n)
    dvr[1:] = np.diff(offset) / GRID_S
    seg["vertrate"] = seg["vertrate"].to_numpy() + dvr
    seg.loc[seg.index[onset:], "onground"] = False  # an airborne excursion


def _sustained_loiter(seg: pd.DataFrame, onset: int, rng: np.random.Generator) -> None:
    """Station-keeping loiter (§6 low-speed variant): from onset, freeze position (σ<30 m
    jitter), speed<2 m/s, vertrate 0, airborne. Duration = the post-onset span (place onset
    earlier for a longer loiter — the caller can bias it)."""
    idx = seg.index[onset:]
    k = len(idx)
    lat0 = float(seg["lat"].iloc[onset])
    lon0 = float(seg["lon"].iloc[onset])
    jit_n = rng.normal(0.0, 30.0, size=k)        # σ<30 m
    jit_e = rng.normal(0.0, 30.0, size=k)
    seg.loc[idx, "lat"] = lat0 + jit_n / _M_PER_DEG_LAT
    seg.loc[idx, "lon"] = lon0 + jit_e / (_M_PER_DEG_LAT * np.cos(np.radians(lat0)))
    seg.loc[idx, "velocity"] = rng.uniform(0.0, 2.0, size=k)
    seg.loc[idx, "vertrate"] = 0.0
    seg.loc[idx, "onground"] = False


def _final_approach_intercept(seg: pd.DataFrame, onset: int, rng: np.random.Generator) -> None:
    """Drone crosses the arrival corridor: from onset, bend the track toward the nearest
    runway threshold and clamp altitude into the 50-300 m AGL band (§6 type 5)."""
    n = len(seg)
    lat = seg["lat"].to_numpy()
    lon = seg["lon"].to_numpy()
    # nearest runway threshold to the segment's onset point
    p_lat, p_lon = lat[onset], lon[onset]
    rwy = min(LEMD_RUNWAYS.values(),
              key=lambda c: (c[0] - p_lat) ** 2 + (c[1] - p_lon) ** 2)
    ramp = _ramp(n, onset)
    seg["lat"] = lat + (rwy[0] - lat) * ramp     # ramp toward the threshold
    seg["lon"] = lon + (rwy[1] - lon) * ramp
    target_alt = rng.uniform(50.0, 300.0)
    alt = seg["baroaltitude"].to_numpy()
    seg["baroaltitude"] = alt + (target_alt - alt) * ramp
    seg.loc[seg.index[onset:], "onground"] = False


def _speed_spike(seg: pd.DataFrame, onset: int, rng: np.random.Generator) -> None:
    """Softened, demoted speed spike (§6): ×1.5-2.0 for one grid step (5-10 s is sub-grid at
    10 s). Kept in the mix at 10 % — the canonical airport-incursion anomaly is slowing, not
    racing, so this is deliberately minor."""
    factor = rng.uniform(1.5, 2.0)
    i = min(onset, len(seg) - 1)
    seg.iloc[i, seg.columns.get_loc("velocity")] = max(
        float(seg["velocity"].iloc[i]) * factor, 0.0
    )


_PERTURB = {
    "zone_violation": _zone_violation,
    "altitude_high": _altitude_high,
    "sustained_loiter": _sustained_loiter,
    "final_approach_intercept": _final_approach_intercept,
    "speed_spike": _speed_spike,
}


# ── per-segment injection ─────────────────────────────────────────────────────

def inject_segment(
    seg: pd.DataFrame,
    kind: str,
    rng: np.random.Generator,
    *,
    onset_fraction: float = DEFAULT_ONSET_FRACTION,
    window_len: int | None = None,
) -> tuple[pd.DataFrame, int]:
    """Inject one anomaly of `kind` into one clean per-segment frame. Returns the perturbed
    copy + the onset row index. Structural pipeline: perturb measured → replay derivations →
    clear `*_missing` on post-onset rows (synthetic-but-present, so the loss counts them).

    `window_len` (= the Phase-6 `T`) caps the onset so it lands INSIDE the window
    `to_sequences` keeps (first `T` rows). Without it, a long segment (`len > 2T`) could place
    the onset past `T`, leaving the kept window unperturbed but labeled anomalous (codex
    finding #1). The perturbation still ramps over the full segment; only the onset position
    is clamped.
    """
    if kind not in _PERTURB:
        raise ValueError(f"unknown injection kind {kind!r}; expected one of {INJECTION_KINDS}")
    seg = seg.sort_values("time").reset_index(drop=True).copy()
    eff_len = len(seg) if window_len is None else min(len(seg), window_len)
    onset = onset_index(eff_len, onset_fraction)

    _PERTURB[kind](seg, onset, rng)
    seg = apply_segment_derivations(seg)         # replay hdg_sin/cos + dist_to_runway_m

    miss_cols = [f + "_missing" for f in MASKED_FEATURES if f + "_missing" in seg.columns]
    if miss_cols:
        seg.loc[seg.index[onset:], miss_cols] = False
    return seg, onset


def assign_kinds(n: int, rng: np.random.Generator, mix: dict[str, float] = DEFAULT_MIX) -> list[str]:
    """`n` injection kinds drawn i.i.d. from the §6 mix (seeded via `rng`)."""
    kinds = list(mix.keys())
    probs = np.array([mix[k] for k in kinds], dtype="float64")
    probs = probs / probs.sum()
    return list(rng.choice(kinds, size=n, p=probs))


# ── the labeled evaluation set (what notebook 09 calls) ───────────────────────

@dataclass(frozen=True)
class InjectedSet:
    """A labeled val/test set for the bake-off. `X` is `(N, T, 9)` scaled with the TRAIN
    scaler; `loss_mask` is `(N, T)` (1 = score this timestep); `y` is 0=normal / 1=anomaly;
    `onset` is the per-window anomaly-onset index (−1 for normals — for detection latency);
    `kind` labels each window; `segment_id` ties back to the source segment.
    """

    X: np.ndarray
    loss_mask: np.ndarray
    y: np.ndarray
    onset: np.ndarray
    kind: list[str]
    segment_id: list[str]


def make_eval_set(
    clean_df: pd.DataFrame,
    fold_ids: list[str],
    scaler,
    T: int,
    *,
    seed: int,
    fold: str,
    inject_rate: float = 0.5,
    mix: dict[str, float] = DEFAULT_MIX,
    onset_fraction: float = DEFAULT_ONSET_FRACTION,
) -> InjectedSet:
    """Build the labeled eval set: keep `(1 − inject_rate)` of the fold's segments NORMAL
    (label 0), perturb the rest with §6-mixed anomalies (label 1). Both classes are windowed
    + scaled with the SAME TRAIN scaler so the bake-off is apples-to-apples (IF and AE later
    score these identical windows). Deterministic in `seed`.

    Firewall: `assert_injectable` blocks fold='train' and an unfitted scaler.
    """
    assert_injectable(scaler, fold)
    rng = np.random.default_rng(seed)

    ids = list(fold_ids)
    rng.shuffle(ids)
    n_inject = int(round(len(ids) * inject_rate))
    inject_ids = set(ids[:n_inject])

    kinds_for = dict(zip(sorted(inject_ids), assign_kinds(len(inject_ids), rng, mix))) \
        if inject_ids else {}

    frames, y, onset, kind_lbl, seg_lbl = [], [], [], [], []
    for sid, seg in clean_df[clean_df["segment_id"].isin(set(ids))].groupby("segment_id", sort=False):
        if sid in inject_ids:
            perturbed, o = inject_segment(seg, kinds_for[sid], rng,
                                          onset_fraction=onset_fraction, window_len=T)
            frames.append(perturbed)
            y.append(1); onset.append(o); kind_lbl.append(kinds_for[sid]); seg_lbl.append(sid)
        else:
            frames.append(seg.sort_values("time").reset_index(drop=True))
            y.append(0); onset.append(-1); kind_lbl.append("normal"); seg_lbl.append(sid)

    if not frames:
        n_feat = len(AE_FEATURES)
        return InjectedSet(np.empty((0, T, n_feat), "float32"), np.empty((0, T), "float32"),
                           np.empty(0, int), np.empty(0, int), [], [])

    # window + scale ALL frames together. Each frame is exactly one segment and
    # to_sequences groups sort=False (first-seen order), so info row i is frame i —
    # X[i] aligns with y[i]/onset[i]/seg_lbl[i] directly. Assert it rather than trust it.
    pool = pd.concat(frames, ignore_index=True)
    X, _pad, info = to_sequences(pool, T, scaler)
    loss_mask = to_sequences_loss_mask(pool, T)
    assert info["segment_id"].tolist() == seg_lbl, "window/label order drifted from to_sequences"

    return InjectedSet(
        X=X, loss_mask=loss_mask,
        y=np.array(y, dtype=int), onset=np.array(onset, dtype=int),
        kind=kind_lbl, segment_id=seg_lbl,
    )
