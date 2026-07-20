"""Phase 6 — the train/val/test split + the test-set firewall (D-009 + eng-review-2).

This is where the firewall becomes REAL. Phase 3/5 protected "no fit, no split, no T";
this module cashes that in by DEFINING the split and SEALING the test fold. Everything
downstream (scaler fit, T, AE training, injection, the bake-off) reads ONLY the segment-id
sets this module produces, and TEST is never scored until Phase 7 (`burned` stays false).

THE SPLIT (locked 2026-06-01) — temporal hold-out by whole Monday:

    TRAIN  9 Mondays 2017-18  ─ fit scaler+T; AE trains on TRAIN-normal only
    VAL    5 Mondays 2019     ─ model selection + threshold + tuning (synthetic AUROC)
    TEST   4 Mondays 2020     ─ SEALED — Phase 7 only

Held-aside (D-009): `is_emergency ∪ is_go_around ∪ (n_imputed_impossible>0)` are pulled
OUT before the split (never trained on, never in a fold) and become the Phase-7
real-anomaly cohorts. The split operates on the clean-normal pool.

FIREWALL SEMANTICS — `icao24` overlap (eng-review-2; see design doc):
Commercial jets recur at LEMD year over year — 413 airframes fly in both TRAIN and TEST,
281 in all three folds. A clean temporal split therefore CANNOT also satisfy the
originally-specified "no `icao24` spans folds". The resolution:

  - Temporal-by-Monday is the LOAD-BEARING firewall (train years < val < test).
  - `icao24`/`flight_id`/`callsign` are NOT in `AE_FEATURES` (they live only in this
    module's split metadata), so the unsupervised AE has no DIRECT identity channel and
    no label to memorise. CRITICAL test #3 is `assert_no_identity_leak` — not the
    impossible zero-overlap check.
  - `icao24` overlap is REPORTED (`Split.icao24_overlap`), not asserted-to-zero.
  - Recurrence-optimism (the AE learning an airframe's kinematic *template* from the
    features, even without the ID) is MEASURED in notebook 09 via the seen-vs-unseen-
    `icao24` VAL AUROC delta — never assumed away. Wording is "no DIRECT identity leak;
    optimism measured", never "harmless".

    ┌──────────────────────────────── firewall ────────────────────────────────┐
    │  all segments (one of 18 Mondays)                                          │
    │        │                                                                   │
    │        ├─ held-aside (emergency ∪ go_around ∪ impossible) ─► Phase-7 cohort│
    │        │                                                                   │
    │        └─ clean-normal pool ─► by Monday ─► TRAIN | VAL | TEST(sealed)     │
    │             group key crossing folds = icao24 only (not a feature) ────────┘

Leaf imports only (numpy/pandas + the feature contract). No `.env`, no model framework.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from sadar_research.trajectory_anomaly.pipeline.preprocessing import AE_FEATURES

# ── Locked fold → Monday map (design doc "The split (LOCKED 2026-06-01)") ─────
# ISO date strings (UTC). Sortable, so temporal comparisons are plain string compares.
TRAIN_MONDAYS: frozenset[str] = frozenset({
    "2017-06-05", "2017-07-31", "2017-10-02", "2017-12-04",
    "2018-01-29", "2018-06-04", "2018-07-30", "2018-10-01", "2018-12-03",
})
VAL_MONDAYS: frozenset[str] = frozenset({
    "2019-01-28", "2019-04-01", "2019-06-03", "2019-07-29", "2019-09-30",
})
TEST_MONDAYS: frozenset[str] = frozenset({
    "2020-01-27", "2020-02-03", "2020-02-24", "2020-03-09",
})
FOLD_MONDAYS: dict[str, frozenset[str]] = {
    "train": TRAIN_MONDAYS, "val": VAL_MONDAYS, "test": TEST_MONDAYS,
}
ALL_MONDAYS: frozenset[str] = TRAIN_MONDAYS | VAL_MONDAYS | TEST_MONDAYS

# Identifier columns that must NEVER reach the model (the no-identity-leak guard).
# `segment_id` is the row key; `callsign` is an operator/flight string — both are as
# leaky as `icao24`/`flight_id` if they ever enter the feature vector.
IDENTIFIER_COLUMNS: tuple[str, ...] = ("icao24", "flight_id", "segment_id", "callsign")

# The held-aside cohort definition (D-009). Per-segment booleans / counters.
HELD_ASIDE_COLUMNS: tuple[str, ...] = ("is_emergency", "is_go_around")


# ── Per-segment reduction ─────────────────────────────────────────────────────

def segment_monday(meta: pd.DataFrame) -> pd.Series:
    """Per-`segment_id` Monday (UTC date string `YYYY-MM-DD`), from the segment's first
    timestamp. Each cycle-3 parquet is a single Monday's 24 h pull, so a segment's date
    is unambiguous; we key off `min(time)` to be robust to a midnight-crossing tail.
    """
    t0 = meta.groupby("segment_id", sort=False)["time"].min()
    return pd.to_datetime(t0, unit="s", utc=True).dt.strftime("%Y-%m-%d").rename("monday")


def per_segment_meta(meta: pd.DataFrame) -> pd.DataFrame:
    """Collapse row-level `meta` to one row per `segment_id` with the columns the split
    needs: `monday`, `icao24`, the held-aside flags, and `n_imputed_impossible`.

    The held-aside attributes are per-segment constants in `meta` (broadcast across the
    segment's rows by Phase 3/5), so `first()` is exact, not lossy. `is_go_around` is the
    Phase-5 addition (`build_features`); if a caller passes a bare Phase-3 `meta` without
    it, we treat it as all-False rather than crash.
    """
    g = meta.groupby("segment_id", sort=False)
    out = pd.DataFrame({"monday": segment_monday(meta)})
    out["icao24"] = g["icao24"].first()
    out["is_emergency"] = g["is_emergency"].first().astype(bool)
    out["is_go_around"] = (
        g["is_go_around"].first().astype(bool) if "is_go_around" in meta.columns
        else pd.Series(False, index=out.index)
    )
    out["n_imputed_impossible"] = g["n_imputed_impossible"].first().fillna(0).astype(int)
    return out


def held_aside_mask(seg: pd.DataFrame) -> pd.Series:
    """Per-segment held-aside boolean: `is_emergency ∪ is_go_around ∪ impossible>0`."""
    return (
        seg["is_emergency"].to_numpy()
        | seg["is_go_around"].to_numpy()
        | (seg["n_imputed_impossible"].to_numpy() > 0)
    )


# ── The split result ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Split:
    """Immutable split result. `*_ids` are `segment_id` lists; the model reads these only.

    `block_counts` are per-fold totals INCLUDING held-aside (the locked-table numbers,
    9,338 / 6,073 / 4,438, sum 19,849 = the Phase-3 segment total); `counts` are the
    clean-fold sizes AFTER held-aside removal (what the model actually fits/scores).
    `icao24_overlap` is reported (eng-review-2), never asserted-to-zero.
    """

    train_ids: list[str]
    val_ids: list[str]
    test_ids: list[str]
    held_aside_ids: list[str]
    counts: dict[str, int]
    block_counts: dict[str, int]
    icao24_overlap: dict[str, int]

    def manifest_test_set(self, holdout_path: str | None = None) -> dict:
        """The `manifest.yml > test_set` block this split implies. The split itself is
        RNG-free (a fixed Monday→fold map), so `split_seed` is `null` — there is no
        random assignment to seed. `burned` stays false; only Phase 7 flips it.
        """
        return {
            "defined_at": None,  # stamped by the caller (notebook) at write time
            "split_seed": None,  # deterministic by construction — no RNG in the split
            "split_strategy": "temporal-by-Monday (train 2017-18 < val 2019 < test 2020) "
                              "+ no-identity-leak guard (icao24/flight_id ∉ AE_FEATURES); "
                              "held-aside emergency∪go_around∪impossible pulled pre-split "
                              "(D-009 + eng-review-2)",
            "holdout_path": holdout_path,
            "count": self.counts["test"],
            "burned": False,
            "burned_at": None,
            "burn_reason": None,
        }


# ── The split ─────────────────────────────────────────────────────────────────

def split_by_monday(meta: pd.DataFrame) -> Split:
    """Partition segments into train/val/test by the locked Monday→fold map, after pulling
    the held-aside cohort. Reports `icao24` cross-fold overlap. Pure function of `meta`.

    Raises if a segment falls on a Monday outside the 18 locked dates — a silent
    mis-assignment would be a firewall hole, so we fail loud instead.
    """
    seg = per_segment_meta(meta)

    unknown = set(seg["monday"].unique()) - ALL_MONDAYS
    if unknown:
        raise ValueError(
            f"segments fall on Monday(s) outside the locked split map: {sorted(unknown)}. "
            "Every cycle-3 segment must map to one of the 18 locked Mondays."
        )

    held = held_aside_mask(seg)
    held_ids = seg.index[held].tolist()
    clean = seg.loc[~held]

    def ids_for(fold: str) -> list[str]:
        return clean.index[clean["monday"].isin(FOLD_MONDAYS[fold])].tolist()

    train_ids, val_ids, test_ids = ids_for("train"), ids_for("val"), ids_for("test")

    counts = {"train": len(train_ids), "val": len(val_ids), "test": len(test_ids),
              "held_aside": len(held_ids)}
    block_counts = {
        fold: int(seg["monday"].isin(mondays).sum())
        for fold, mondays in FOLD_MONDAYS.items()
    }

    ac = {
        "train": set(clean.loc[train_ids, "icao24"]),
        "val": set(clean.loc[val_ids, "icao24"]),
        "test": set(clean.loc[test_ids, "icao24"]),
    }
    icao24_overlap = {
        "train_val": len(ac["train"] & ac["val"]),
        "train_test": len(ac["train"] & ac["test"]),
        "val_test": len(ac["val"] & ac["test"]),
        "all_three": len(ac["train"] & ac["val"] & ac["test"]),
    }

    return Split(
        train_ids=train_ids, val_ids=val_ids, test_ids=test_ids, held_aside_ids=held_ids,
        counts=counts, block_counts=block_counts, icao24_overlap=icao24_overlap,
    )


# ── Firewall assertions (the 3 CRITICAL guards) ───────────────────────────────

def assert_no_identity_leak(ae_features: list[str] = AE_FEATURES) -> None:
    """CRITICAL #3 (no-identity-leak). The property that makes airframe recurrence safe:
    no identifier column is in the AE feature vector, so the unsupervised AE cannot key on
    identity. Replaces the impossible "no icao24 spans folds" (eng-review-2).
    """
    leaked = [c for c in IDENTIFIER_COLUMNS if c in ae_features]
    assert not leaked, (
        f"identity leak: {leaked} present in AE_FEATURES — a group-leakage channel is open. "
        "Identifiers must stay in split metadata only."
    )


def assert_firewall(split: Split, ae_features: list[str] = AE_FEATURES) -> None:
    """Run all three CRITICAL firewall guards. Call before any fit/score uses the split.

      1. no-test-leak — the folds are a disjoint partition; TEST shares no segment with
         TRAIN/VAL, and held-aside shares none with any fold.
      2. no-identity-leak — `assert_no_identity_leak` (see above).
      3. temporal — every TRAIN/VAL Monday is strictly earlier than every TEST Monday.
    """
    s_train, s_val, s_test = set(split.train_ids), set(split.val_ids), set(split.test_ids)
    s_held = set(split.held_aside_ids)

    # 1 — partition disjointness (the real firewall guard).
    assert s_test.isdisjoint(s_train), "TEST segment leaked into TRAIN"
    assert s_test.isdisjoint(s_val), "TEST segment leaked into VAL"
    assert s_train.isdisjoint(s_val), "TRAIN and VAL share a segment"
    assert s_held.isdisjoint(s_train | s_val | s_test), "held-aside segment leaked into a fold"

    # 2 — no identifier reaches the model.
    assert_no_identity_leak(ae_features)

    # 3 — temporal ordering (ISO date strings sort chronologically).
    latest_train_val = max(TRAIN_MONDAYS | VAL_MONDAYS)
    earliest_test = min(TEST_MONDAYS)
    assert latest_train_val < earliest_test, (
        f"temporal firewall broken: latest train/val Monday {latest_train_val} "
        f"is not before earliest test Monday {earliest_test}"
    )


# ── Materialise a fold (helper for the notebook) ──────────────────────────────

def subset(clean_df: pd.DataFrame, ids: list[str]) -> pd.DataFrame:
    """Rows of `clean_df` whose `segment_id` is in `ids`, order preserved. The notebook
    feeds the result to `to_sequences` (which fits the scaler on TRAIN, transforms here).
    """
    return clean_df[clean_df["segment_id"].isin(set(ids))].reset_index(drop=True)
