"""Tests for the Phase-6 split + firewall (`backend/core/split.py`).

The three CRITICAL guards are the Phase-6 firewall — the analogues of Phase 3's
interpolation-never-crosses-boundary + make_scaler-UNFITTED. They must hold BEFORE any
training run:

  ★★★ no-test-leak     — TEST shares no segment with TRAIN/VAL; held-aside in no fold.
  ★★★ no-identity-leak — no identifier (icao24/flight_id/segment_id/callsign) in AE_FEATURES.
  ★★★ temporal         — every TRAIN/VAL Monday strictly before every TEST Monday.

Plus held-aside pull-out, determinism, the reported-not-asserted icao24 overlap, and the
loud failure on an out-of-map Monday. Fixtures are synthetic (fast, pipeline-independent);
the real 19,849-segment / locked-table validation lives in notebook 09.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sadar_research.trajectory_anomaly.pipeline import split as sp
from sadar_research.trajectory_anomaly.pipeline.preprocessing import AE_FEATURES


# ── synthetic meta builder ────────────────────────────────────────────────────

def _epoch(monday: str, offset_s: int = 43_200) -> int:
    """Epoch seconds for a Monday date at midday UTC (offset keeps us mid-day so a small
    tail never rolls the UTC date)."""
    return int(pd.Timestamp(monday, tz="UTC").timestamp()) + offset_s


def make_meta(specs: list[dict], rows_per_seg: int = 3) -> pd.DataFrame:
    """Build a row-level `meta` frame from per-segment specs.

    Each spec: {id, monday, icao24, [is_emergency], [is_go_around], [n_imputed_impossible]}.
    Held-aside flags / counters are per-segment constants broadcast across the rows, exactly
    as Phase 3/5 produce them.
    """
    rows = []
    for s in specs:
        t0 = _epoch(s["monday"])
        for k in range(rows_per_seg):
            rows.append({
                "segment_id": s["id"],
                "time": t0 + k * 10,
                "icao24": s["icao24"],
                "flight_id": s["id"].split("#")[0],
                "squawk": 7700 if s.get("is_emergency") else 1000,
                "is_emergency": bool(s.get("is_emergency", False)),
                "is_go_around": bool(s.get("is_go_around", False)),
                "n_imputed_impossible": int(s.get("n_imputed_impossible", 0)),
                "n_imputed_missing": 0,
            })
    return pd.DataFrame(rows)


# A normal-only spec: 2 clean segments on each fold's first Monday.
def _normal_specs() -> list[dict]:
    return [
        {"id": "t1#0", "monday": "2017-06-05", "icao24": "aaa001"},
        {"id": "t2#0", "monday": "2018-01-29", "icao24": "aaa002"},
        {"id": "v1#0", "monday": "2019-01-28", "icao24": "bbb001"},
        {"id": "v2#0", "monday": "2019-04-01", "icao24": "bbb002"},
        {"id": "e1#0", "monday": "2020-01-27", "icao24": "ccc001"},
        {"id": "e2#0", "monday": "2020-02-03", "icao24": "ccc002"},
    ]


# ── segment → Monday ──────────────────────────────────────────────────────────

def test_segment_monday_maps_to_utc_date():
    meta = make_meta(_normal_specs())
    mondays = sp.segment_monday(meta)
    assert mondays["t1#0"] == "2017-06-05"
    assert mondays["e2#0"] == "2020-02-03"


# ── the split assigns by Monday ───────────────────────────────────────────────

def test_split_assigns_each_segment_to_its_fold():
    split = sp.split_by_monday(make_meta(_normal_specs()))
    assert set(split.train_ids) == {"t1#0", "t2#0"}
    assert set(split.val_ids) == {"v1#0", "v2#0"}
    assert set(split.test_ids) == {"e1#0", "e2#0"}
    assert split.counts == {"train": 2, "val": 2, "test": 2, "held_aside": 0}


# ── ★★★ CRITICAL #1 — no-test-leak (partition disjoint) ──────────────────────

def test_critical_no_test_leak():
    split = sp.split_by_monday(make_meta(_normal_specs()))
    sp.assert_firewall(split)  # must not raise
    s_train, s_val, s_test = set(split.train_ids), set(split.val_ids), set(split.test_ids)
    assert s_test.isdisjoint(s_train)
    assert s_test.isdisjoint(s_val)
    assert s_train.isdisjoint(s_val)


# ── ★★★ CRITICAL #2 — no-identity-leak ───────────────────────────────────────

def test_critical_no_identity_leak_passes_on_real_contract():
    # The shipped AE_FEATURES contains no identifier → must pass.
    sp.assert_no_identity_leak(AE_FEATURES)
    for ident in sp.IDENTIFIER_COLUMNS:
        assert ident not in AE_FEATURES


def test_critical_no_identity_leak_raises_if_identifier_in_features():
    leaky = ["lat", "lon", "icao24"]  # someone wired the airframe id into the model
    with pytest.raises(AssertionError, match="identity leak"):
        sp.assert_no_identity_leak(leaky)


# ── ★★★ CRITICAL #3 — temporal ordering ──────────────────────────────────────

def test_critical_temporal_ordering():
    # On the locked constants: every train/val Monday strictly before every test Monday.
    assert max(sp.TRAIN_MONDAYS | sp.VAL_MONDAYS) < min(sp.TEST_MONDAYS)
    # And the produced test segments only ever land on TEST Mondays.
    split = sp.split_by_monday(make_meta(_normal_specs()))
    meta = make_meta(_normal_specs())
    test_mondays = set(sp.segment_monday(meta)[split.test_ids])
    assert test_mondays <= sp.TEST_MONDAYS


# ── held-aside is pulled out of every fold ────────────────────────────────────

def test_held_aside_pulled_from_all_folds():
    specs = _normal_specs() + [
        {"id": "t9#0", "monday": "2017-06-05", "icao24": "aaa009", "is_emergency": True},
        {"id": "v9#0", "monday": "2019-01-28", "icao24": "bbb009", "is_go_around": True},
        {"id": "e9#0", "monday": "2020-01-27", "icao24": "ccc009", "n_imputed_impossible": 4},
    ]
    split = sp.split_by_monday(make_meta(specs))
    held = set(split.held_aside_ids)
    assert held == {"t9#0", "v9#0", "e9#0"}
    all_folds = set(split.train_ids) | set(split.val_ids) | set(split.test_ids)
    assert held.isdisjoint(all_folds)
    sp.assert_firewall(split)  # held-aside-in-no-fold guard inside


def test_block_counts_include_held_aside_but_fold_counts_do_not():
    specs = _normal_specs() + [
        {"id": "t9#0", "monday": "2017-06-05", "icao24": "aaa009", "is_emergency": True},
    ]
    split = sp.split_by_monday(make_meta(specs))
    # 2017-06-05 + 2018-01-29 train block = 3 segments incl. the held-aside one ...
    assert split.block_counts["train"] == 3
    # ... but the clean train fold is only 2.
    assert split.counts["train"] == 2


# ── icao24 overlap: REPORTED, not asserted-to-zero (eng-review-2) ─────────────

def test_icao24_overlap_reported_and_firewall_still_passes():
    # Same airframe flies in TRAIN and TEST — the unavoidable real-world case.
    specs = _normal_specs() + [
        {"id": "t5#0", "monday": "2017-07-31", "icao24": "shared01"},
        {"id": "e5#0", "monday": "2020-02-24", "icao24": "shared01"},
    ]
    split = sp.split_by_monday(make_meta(specs))
    # Overlap is reported ...
    assert split.icao24_overlap["train_test"] >= 1
    # ... and the firewall STILL passes (no-identity-leak is the guard, not zero-overlap).
    sp.assert_firewall(split)
    # The shared airframe's two segments are different segment ids in different folds.
    assert "t5#0" in split.train_ids and "e5#0" in split.test_ids


# ── determinism (no RNG in the split) ─────────────────────────────────────────

def test_split_is_deterministic():
    meta = make_meta(_normal_specs())
    a = sp.split_by_monday(meta)
    b = sp.split_by_monday(meta)
    assert a.train_ids == b.train_ids
    assert a.val_ids == b.val_ids
    assert a.test_ids == b.test_ids
    assert a.manifest_test_set()["split_seed"] is None  # deterministic by construction


# ── loud failure on an out-of-map Monday ──────────────────────────────────────

def test_unknown_monday_raises():
    bad = [{"id": "x1#0", "monday": "2021-05-03", "icao24": "zzz001"}]  # not a locked Monday
    with pytest.raises(ValueError, match="outside the locked split map"):
        sp.split_by_monday(make_meta(bad))


# ── manifest block shape ──────────────────────────────────────────────────────

def test_manifest_test_set_block_keeps_firewall_closed():
    split = sp.split_by_monday(make_meta(_normal_specs()))
    block = split.manifest_test_set(holdout_path="backend/models/phase6/test_ids.json")
    assert block["burned"] is False
    assert block["count"] == split.counts["test"]
    assert "temporal-by-Monday" in block["split_strategy"]
