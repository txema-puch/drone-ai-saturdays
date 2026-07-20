"""Phase 5 — feature engineering on the Phase-3 clean per-segment frames.

Three jobs, all leak-free by construction (every feature is computed per segment
from a FIXED reference — runway geography — with no fitted statistic; the only fit,
the scaler, is Phase 6 on TRAIN only):

  - `apply_segment_derivations(seg)` — replay the DERIVED AE features
    (`hdg_sin`/`hdg_cos`, `dist_to_runway_m`) from the measured primitives. Idempotent
    on clean data. The synthetic-injection bench perturbs the measured columns, then
    calls this BEFORE windowing+scaling, so derived features stay consistent
    *structurally* — no hand-maintained "recompute" list (D-011 feature-contract note).

  - `detect_go_around(clean_df)` — geometric descend-then-climb-near-runway rule →
    per-segment `is_go_around`. Held-aside real-anomaly validation cohort (D-009
    amendment, D-008 Layer-1 companion). Routed OUT of TRAIN at the Phase-6 split;
    scored in Phase 7 alongside the Olive-7700 emergency set.

  - `build_features(raw_df)` — the Phase-5 orchestrator: `preprocess()` + the
    `is_go_around` meta tag.

The AE feature CONTRACT (`AE_FEATURES`/`SCALER_FEATURES`) lives in
`sadar_research.trajectory_anomaly.pipeline.preprocessing` — the single source of truth the injection bench, the
per-feature RE attribution, and the Layer-3 baseline all bind to by name. Phase 5
promoted `dist_to_runway_m` into it; this module does not redefine the contract.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sadar_research.trajectory_anomaly.pipeline import preprocessing as pp
from sadar_research.trajectory_anomaly.data.geometry import distance_to_closest_runway

# ── Feature taxonomy (for the injection bench) ────────────────────────────────
# DERIVED features are functions of the measured primitives → recompute, never
# perturb directly (perturbing them independently desyncs from lat/lon/heading).
DERIVED_FEATURES = ["dist_to_runway_m", "hdg_sin", "hdg_cos"]
# MEASURED primitives are raw ADS-B → safe to perturb directly. `velocity`/`vertrate`
# are raw groundspeed / vertical-rate (NOT position-derived — `_speed` is a separate
# idle-trim signal dropped before output), so a speed/altitude injection needs no
# position move. `heading` is the measured handle behind hdg_sin/hdg_cos.
MEASURED_PRIMITIVES = ["lat", "lon", "baroaltitude", "velocity", "vertrate", "onground", "heading"]

GO_AROUND_COLUMN = "is_go_around"
META_COLUMNS = pp.META_COLUMNS + [GO_AROUND_COLUMN]  # the Phase-5 meta contract


# ── Shared derivation replay ──────────────────────────────────────────────────

def apply_segment_derivations(seg: pd.DataFrame) -> pd.DataFrame:
    """Recompute the derived AE features from the measured primitives.

    `hdg_sin`/`hdg_cos` from `heading`; `dist_to_runway_m` from `lat`/`lon`. Idempotent
    on clean post-pipeline data (the pipeline renormalises hdg_sin/cos to the unit
    circle and reconstructs `heading` from them, so `sin(radians(heading)) == hdg_sin`).

    This is the structural guarantee for the injection bench: perturb the measured
    columns on the per-segment frame, call this, THEN window + scale — every derived
    feature (and any future one added to `DERIVED_FEATURES`) stays consistent for free.

    ⚠ CONTRACT (footgun): perturb only the MEASURED handles — `heading` (for a heading
    change), `lat`/`lon` (for a route/zone shift). This function RECOMPUTES the derived
    channels from them, so a direct edit to `hdg_sin`/`hdg_cos`/`dist_to_runway_m` is
    **silently overwritten** (a holding injection that writes `hdg_sin` instead of
    `heading` vanishes here). Requires `heading`, `lat`, `lon` to be present.
    """
    seg = seg.copy()
    seg["hdg_sin"] = np.sin(np.radians(seg["heading"]))
    seg["hdg_cos"] = np.cos(np.radians(seg["heading"]))
    seg["dist_to_runway_m"] = distance_to_closest_runway(seg["lat"], seg["lon"]).to_numpy()
    return seg


# ── Go-around detector ────────────────────────────────────────────────────────
# Domain constants (validated against the cycle-3 corpus, tuned for a usable cohort
# size; see notebook 09 Part 1 + 05-features.md). Not data-fit parameters.
GA_RUNWAY_PROX_M = 5_000.0   # "near a runway"
GA_LOW_ALT_M = 500.0         # the airborne low point must descend below this (near-landing)
GA_MIN_DESCENT_M = 300.0     # real descent INTO the low point (excludes departures, which start low)
GA_MIN_CLIMB_M = 300.0       # climb-back FROM the low point while airborne (excludes normal arrivals)
GA_MIN_AIRBORNE_ROWS = 5     # ignore segments with too little airborne signal


def _airborne_runs(onground: np.ndarray) -> list[tuple[int, int]]:
    """Maximal `[start, end)` index ranges of contiguous airborne (onground==False) rows."""
    runs, start = [], None
    for i, og in enumerate(onground):
        if not og and start is None:
            start = i
        elif og and start is not None:
            runs.append((start, i)); start = None
    if start is not None:
        runs.append((start, len(onground)))
    return runs


def _segment_is_go_around(seg: pd.DataFrame) -> bool:
    """True iff the segment shows a descend-to-near-runway then climb-away signature
    WITHIN A SINGLE airborne run.

    A go-around / rejected landing: the aircraft descends toward a runway while
    airborne, reaches a low point near it, then climbs back away — all without
    touching down. Requiring descent + low + climb in **one contiguous airborne run**
    is the discriminator:
      - departures start low (no descent before the low point in the run);
      - normal arrivals descend to a touchdown (no airborne climb after the low point);
      - touch-and-gos DO touch down, which SPLITS the airborne run — the approach
        (descent, no climb) and the takeoff (climb, no descent) land in different runs,
        so neither run carries the full signature. (A global airborne-min search would
        misfire here when the post-touchdown takeoff is the lowest airborne point.)
    """
    seg = seg.sort_values("time")
    onground = seg["onground"].astype(bool).to_numpy()
    alt = seg["baroaltitude"].to_numpy(dtype="float64")
    dist = seg["dist_to_runway_m"].to_numpy(dtype="float64")
    if (~onground).sum() < GA_MIN_AIRBORNE_ROWS:
        return False

    for s, e in _airborne_runs(onground):
        a, d = alt[s:e], dist[s:e]
        near = np.where(d < GA_RUNWAY_PROX_M)[0]
        if near.size == 0:
            continue
        j = int(near[np.argmin(a[near])])     # low point within this run, near a runway
        low = float(a[j])
        if low >= GA_LOW_ALT_M:
            continue
        if j == 0 or (float(a[:j].max()) - low) < GA_MIN_DESCENT_M:
            continue                          # no real descent INTO the low point (departure)
        if j == len(a) - 1 or (float(a[j + 1:].max()) - low) < GA_MIN_CLIMB_M:
            continue                          # no climb-back OUT of it (arrival)
        return True
    return False


def detect_go_around(clean_df: pd.DataFrame) -> pd.Series:
    """Per-segment `is_go_around` Series indexed by `segment_id`."""
    if clean_df.empty:
        return pd.Series(dtype=bool, name=GO_AROUND_COLUMN)
    flags = {sid: _segment_is_go_around(seg)
             for sid, seg in clean_df.groupby("segment_id", sort=False)}
    return pd.Series(flags, name=GO_AROUND_COLUMN)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def build_features(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Phase-5 pipeline: run `preprocess()`, then tag the go-around cohort in `meta`.

    Returns `(clean_df, meta)` where `clean_df` carries the promoted-contract AE
    features (incl. scaled `dist_to_runway_m`) and `meta` adds `is_go_around` to the
    Phase-3 meta columns. Still no split, no fit — Phase 6 owns those.
    """
    clean_df, meta = pp.preprocess(raw_df)
    meta = meta.copy()
    if clean_df.empty:
        meta[GO_AROUND_COLUMN] = pd.Series(dtype=bool)
        return clean_df, meta
    ga = detect_go_around(clean_df)
    meta[GO_AROUND_COLUMN] = meta["segment_id"].map(ga).fillna(False).astype(bool)
    return clean_df, meta
