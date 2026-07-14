"""SADAR-merge (Direction C) — serve-time data precompute.

Mirrors the role of SADAR's `data/processed/test.npy`, but produces the artifacts a
POST-HOC analyst-triage UI needs (design doc §4.5), not a live monitor's window array:

  - a RANKED QUEUE  — every scored segment, ordered most→least anomalous, with its label
                      (normal / go_around / emergency) and AE window score.
  - per-segment CASE FILES — for a curated subset: the raw lat/lon/alt path, the model's
                      reconstructed path, the per-step reconstruction-error timeline
                      (the honest "watch the deviation emerge" signal), and per-feature
                      RE attribution (which channel drove the score — diagnostic only).

It reuses the FROZEN Phase-6/7 artifacts and the exact scoring contract from
`backend/scripts/phase7_burn.py` (T=260, loss-masked `reconstruction_error(agg="mean")`,
val-chosen threshold 0.222) — NO re-tuning, NO model change. The cohort = the sealed 2020
TEST fold (post-hoc audit population) ∪ the held-aside real-anomaly cases (go-around ∪
emergency) so the queue has genuine anomalies to surface.

Run:  cd backend && uv run python -m serve.precompute
Out:  backend/models/sadar_demo/{queue.json, cases.json, manifest.json}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core import lstm_ae as ae  # noqa: E402
from backend.core.preprocessing import (  # noqa: E402
    AE_FEATURES,
    SCALER_FEATURES,
    to_sequences,
    to_sequences_loss_mask,
)
from backend.serve.scoring import (  # noqa: E402
    forward_batched,
    per_feature_re,
    per_step_re,
    unscale_block,
)
from backend.serve.operations import (  # noqa: E402
    annotate_segment_refs,
    build_operation_summaries,
    operation_ref,
    severity_band,
)
from backend.serve.quality import assess_segment  # noqa: E402

# per-step channels baked alongside each case so the case-file temporal panel can trace
# any one over time (the attribution panel shows their aggregate contribution; this shows
# WHEN each diverged). Physical units, straight from clean_df (already unscaled).
CHANNELS = ["baroaltitude", "velocity", "vertrate", "dist_to_runway_m"]

M = REPO / "backend/models/phase6"
BURN = M / "phase7_burn_results.json"
OUT = REPO / "backend/models/sadar_demo"
T = 260
AE_THR = 0.222  # val-chosen operating point — frozen, never retuned here
SEED = 42

# Real-anomaly ROC/PR are the Phase-7 burn's printed head-to-head (held-aside cohort vs
# 2020-test-normal); the saved burn JSON keeps only the synthetic headline + per-type, so the
# real numbers are recorded here with provenance (07-eval.md) and baked into the bundle.
REAL_RESULTS = {
    "AE": (0.667, 0.088),
    "kNN": (0.595, 0.067),
    "IF": (0.495, None),
    "SADAR-VAE-LSTM": (0.659, 0.299),  # his native rep, reproduced
}

# how many case files to bake (heavy: paths + timelines). The queue lists EVERY segment;
# case files cover all real anomalies + the most-anomalous normals + a typical sample.
N_TOP_NORMAL = 40
N_TYPICAL = 20


def select_case_indices(
    seg_ids: np.ndarray,
    scores: np.ndarray,
    anomaly_ids: set[str],
    *,
    n_top_normal: int = N_TOP_NORMAL,
    n_typical: int = N_TYPICAL,
) -> set[int]:
    """Select every held-aside anomaly plus the requested NORMAL case samples."""
    normal = np.array([sid not in anomaly_ids for sid in seg_ids], dtype=bool)
    normal_indices = np.flatnonzero(normal)
    top_normal = normal_indices[np.argsort(-scores[normal_indices])[:n_top_normal]]
    median = float(np.median(scores))
    typical_normal = normal_indices[
        np.argsort(np.abs(scores[normal_indices] - median))[:n_typical]
    ]
    anomaly_indices = np.flatnonzero(~normal)
    return set(np.concatenate([anomaly_indices, top_normal, typical_normal]).tolist())


def valid_normal_step_scores(
    step_scores: np.ndarray,
    loss_mask: np.ndarray,
    seg_ids: np.ndarray,
    anomaly_ids: set[str],
) -> np.ndarray:
    """Observed per-step reconstruction errors from normal segments only."""
    samples = [
        step_scores[i][loss_mask[i].astype(bool)]
        for i, sid in enumerate(seg_ids)
        if sid not in anomaly_ids
    ]
    return np.concatenate(samples) if samples else np.array([], dtype=float)


def main() -> None:
    # build-time only: load .env so report generation sees ANTHROPIC_API_KEY (the SERVE
    # never loads .env — reports are baked here and served static).
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    clean = pd.read_parquet(M / "clean_df.parquet")
    meta = pd.read_parquet(M / "meta.parquet")
    ids = json.load(open(M / "split_ids.json"))
    scaler = joblib.load(M / "scaler.joblib")
    model = ae.load_checkpoint(str(M / "lstm_ae_best.pt"))

    # real-anomaly cases held aside from training (go-around ∪ emergency), per the burn
    g = meta.groupby("segment_id").agg(is_ga=("is_go_around", "max"),
                                       is_em=("is_emergency", "max"))
    held = set(ids["held_aside"])
    anomaly_ids = {s for s in g.index if s in held and (g.loc[s, "is_ga"] or g.loc[s, "is_em"])}

    # cohort = sealed 2020 TEST fold (audit population) ∪ real anomalies
    cohort_ids = list(dict.fromkeys(list(ids["test"]) + sorted(anomaly_ids)))
    cdf = clean[clean.segment_id.isin(set(cohort_ids))]

    # build sequences in the FROZEN contract; `info.segment_id[i]` aligns to row i of X
    X, _, info = to_sequences(cdf, T, scaler)
    loss_mask = to_sequences_loss_mask(cdf, T)
    seg_ids = info.segment_id.tolist()

    # total (pre-truncation) length per segment. to_sequences keeps only the FIRST T rows
    # (preprocessing.to_sequences: feats[:T]); segments longer than T have their tail —
    # for a long arrival, the terminal approach — dropped before scoring. We flag these so
    # the queue can hide them and the case file can disclose the cut (D-014). NOT a model
    # change: the score is unchanged; we only annotate it.
    seg_len = cdf.groupby("segment_id").size().to_dict()

    # trajectory key = segment_id without the "#k" suffix. ADS-B gaps split one flight into
    # sibling segments (#2, #3, …), each scored independently; for the case-file map we show
    # the WHOLE trajectory as faint context behind the scored segment, so a near-runway
    # fragment reads as the tail of a full approach rather than a lonely diagonal.
    clean["_traj"] = clean.segment_id.str.rsplit("#", n=1).str[0]

    # "genuine LEMD terminal operation" flag: within the SCORED window (first T rows) is there
    # a step that is both LOW and CLOSE to a LEMD runway (on final / on ground / low departure)?
    # A single conjunctive test that unifies the gate-artifact classes the AE flags but that are
    # NOT anomalous LEMD behaviour (D-014): truncated long arrivals (approach cut from the
    # window), neighbour-field traffic (low+close to LECU/LEGT/LETO, not LEMD), and high-altitude
    # overflights (close horizontally but never low — dist_to_runway is altitude-blind). The
    # queue defaults to hiding non-terminal segments. NOT a model change — annotation only.
    TERM_DIST_M, TERM_ALT_M = 5000.0, 1500.0

    def _is_terminal(g: pd.DataFrame) -> bool:
        g = g.sort_values("time").head(T)
        d = g["dist_to_runway_m"].to_numpy()
        a = g["baroaltitude"].to_numpy()
        return bool(((d < TERM_DIST_M) & (a < TERM_ALT_M)).any())

    # Keep this compatible with the project's pandas >=2.1 floor. The
    # include_groups argument was only added in pandas 2.2.
    terminal_map = {
        sid: _is_terminal(group)
        for sid, group in cdf.groupby("segment_id", sort=False)
    }

    segment_frames = {
        sid: group.sort_values("time").head(T)
        for sid, group in cdf.groupby("segment_id", sort=False)
    }
    trajectory_frames = {
        trajectory_id: group.sort_values("time")
        for trajectory_id, group in clean.groupby("_traj", sort=False)
    }
    assessment_map = {
        sid: assess_segment(
            segment_frames[sid],
            valid_steps=int(loss_mask[i].sum()),
            n_steps=int(seg_len.get(sid, len(segment_frames[sid]))),
            truncated=bool(seg_len.get(sid, 0) > T),
            terminal_op=bool(terminal_map.get(sid, True)),
        )
        for i, sid in enumerate(seg_ids)
    }

    # score (loss-masked mean RE — the shipped contract)
    scores = ae.reconstruction_error(model, X, loss_mask, agg="mean")
    recon = forward_batched(model, X, loss_mask)
    step = per_step_re(recon, X, loss_mask)
    feat = per_feature_re(recon, X, loss_mask)

    # percentile rank of each score among the whole cohort — turns a bare "1.94" into
    # "98th pctile" so an analyst can read severity at a glance (design-review fix #3)
    order_asc = np.argsort(scores)
    ranks = np.empty(len(scores), dtype="float64")
    ranks[order_asc] = np.arange(len(scores))
    pct = ranks / max(len(scores) - 1, 1) * 100.0

    def label_of(sid: str) -> str:
        if sid in anomaly_ids:
            return "emergency" if g.loc[sid, "is_em"] else "go_around"
        return "normal"

    # ── ranked queue (every segment) ──────────────────────────────────────────────────────
    order = np.argsort(-scores)
    queue = annotate_segment_refs([
        {
            "id": int(i),
            "segment_id": seg_ids[i],
            "score": round(float(scores[i]), 6),
            "pct": round(float(pct[i]), 1),
            "band": severity_band(float(pct[i])),
            "anomalous": bool(scores[i] >= AE_THR),
            "label": label_of(seg_ids[i]),
            "n_steps": int(seg_len.get(seg_ids[i], 0)),
            "truncated": bool(seg_len.get(seg_ids[i], 0) > T),
            "terminal_op": bool(terminal_map.get(seg_ids[i], True)),
            **assessment_map[seg_ids[i]],
        }
        for i in order
    ])
    operations = build_operation_summaries(queue)

    # ── curated case files (heavy) ────────────────────────────────────────────────────────
    median = float(np.median(scores))
    pick = select_case_indices(seg_ids, scores, anomaly_ids)
    sc_idx = [AE_FEATURES.index(c) for c in SCALER_FEATURES]

    cases = {}
    for i in sorted(pick):
        sid = seg_ids[i]
        seg = segment_frames[sid]
        valid = int(loss_mask[i].sum())
        nrows = min(len(seg), T)
        # real path straight from the unscaled grid (we store lat/lon natively — no inverse-proj)
        t0 = int(seg["time"].iloc[0])
        path = [
            {"lat": float(la), "lon": float(lo), "alt": float(al), "t": int(tt - t0)}
            for la, lo, al, tt in zip(seg["lat"].head(nrows), seg["lon"].head(nrows),
                                      seg["baroaltitude"].head(nrows), seg["time"].head(nrows))
        ]
        # reconstructed path: inverse-transform the scaled 6-block of the recon
        recon_phys = unscale_block(recon[i, :nrows][:, sc_idx], scaler)
        li, oi, ai = (SCALER_FEATURES.index("lat"), SCALER_FEATURES.index("lon"),
                      SCALER_FEATURES.index("baroaltitude"))
        recon_path = [
            {"lat": float(r[li]), "lon": float(r[oi]), "alt": float(r[ai])}
            for r in recon_phys
        ]
        # per-step measured channels (physical units, straight from clean_df) so the
        # temporal panel can trace any one over time, not just altitude
        channels = {
            c: [round(float(v), 4) for v in seg[c].head(nrows)]
            for c in CHANNELS
        }
        # full-trajectory context (all sibling segments, time-ordered, downsampled) for the
        # map. lat/lon only — it's faint background, doesn't need per-step resolution.
        traj = trajectory_frames[sid.rsplit("#", 1)[0]]
        stride = max(1, len(traj) // 150)
        context_path = [
            {"lat": round(float(la), 5), "lon": round(float(lo), 5)}
            for la, lo in zip(traj["lat"].iloc[::stride], traj["lon"].iloc[::stride])
        ]
        n_siblings = traj["segment_id"].nunique()
        cases[str(i)] = {
            "id": int(i),
            "case_ref": f"CASE-{int(i):04d}",
            "operation_ref": operation_ref(sid),
            "segment_id": sid,
            "label": label_of(sid),
            "score": round(float(scores[i]), 6),
            "pct": round(float(pct[i]), 1),
            "band": severity_band(float(pct[i])),
            "threshold": AE_THR,
            "anomalous": bool(scores[i] >= AE_THR),
            "valid_steps": valid,
            "n_steps": int(seg_len.get(sid, nrows)),
            "truncated": bool(seg_len.get(sid, nrows) > T),
            "terminal_op": bool(terminal_map.get(sid, True)),
            **assessment_map[sid],
            "path": path,
            "reconstructed": recon_path,
            "context_path": context_path,
            "n_siblings": int(n_siblings),
            "step_scores": [round(float(s), 6) for s in step[i, :nrows]],
            "channels": channels,
            "feature_attribution": {f: round(float(v), 6) for f, v in zip(AE_FEATURES, feat[i])},
        }

    # per-step threshold from NORMAL cases (99th pctile of valid per-step RE) — the
    # "this step is surprising" line for the case-file timeline; from normal behaviour only
    normal_steps = valid_normal_step_scores(step, loss_mask, seg_ids, anomaly_ids)
    step_thr = float(np.percentile(normal_steps, 99)) if normal_steps.size else AE_THR

    # ── metrics panel (Phase-7 results, MetricRow[] shape) — bundle-self-contained ────────
    burn = json.loads(BURN.read_text()) if BURN.exists() else {}
    head, per_type = burn.get("headline_auroc", {}), burn.get("per_type", {})
    metrics = {
        "selected_model": "AE",
        "results": [
            {
                "model": m,
                "real_roc_auc": REAL_RESULTS[m][0],
                "real_pr_auc": REAL_RESULTS[m][1],
                "synthetic_mean_roc_auc": head.get(m),     # None for SADAR (own bench)
                "synthetic_per_type": per_type.get(m, {}),
            }
            for m in ("AE", "kNN", "IF", "SADAR-VAE-LSTM")
        ],
        "notes": {
            "real_cohort": "held-aside go-around ∪ emergency vs sealed 2020-test-normal",
            "synthetic_mix": "D-012 (4 dynamic types; zone re-weighted out)",
            "ae_target_unmet": "synthetic 0.731 < 0.85 target — reported honestly",
        },
    }

    manifest = {
        "n_segments": len(seg_ids),
        "n_operations": len(operations),
        "n_test": len(ids["test"]),
        "n_real_anomalies": len(anomaly_ids),
        "n_anomalous_at_thr": int((scores >= AE_THR).sum()),
        "n_truncated": int(sum(1 for s in seg_ids if seg_len.get(s, 0) > T)),
        "n_nonterminal": int(sum(1 for s in seg_ids if not terminal_map.get(s, True))),
        "n_reviewable": int(sum(
            assessment_map[s]["assessment_state"] == "reviewable" for s in seg_ids
        )),
        "n_data_quality_conflicts": int(sum(
            assessment_map[s]["assessment_state"] == "data_quality_conflict" for s in seg_ids
        )),
        "n_insufficient_data": int(sum(
            assessment_map[s]["assessment_state"] == "insufficient_data" for s in seg_ids
        )),
        "n_coverage_limited": int(sum(
            assessment_map[s]["assessment_state"] == "coverage_limited" for s in seg_ids
        )),
        "n_cases_baked": len(cases),
        "threshold": AE_THR,
        "step_threshold": round(step_thr, 6),
        "T": T,
        "median_score": round(median, 6),
        "center": {"lat": 40.4936, "lon": -3.5668},
        "step_seconds": 10,
    }
    # ── LLM analysis reports — BAKE FROM CACHE (served static; no key / no API / no cost) ────
    # Generation is done OUT-OF-BAND by Claude Code subagents (free on the CC plan) via the
    # gen-reports Workflow, which writes reports_cache.json keyed by (segment_id, prompt fp).
    # precompute just bakes whatever's cached for the current prompt fingerprint; missing → null.
    from backend.serve import report as rpt  # noqa: E402

    fp = rpt.prompt_fingerprint(rpt.SUBAGENT_LABEL)
    cache_path = OUT / "reports_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    baked = 0
    for case in cases.values():
        report = cache.get(f"{case['segment_id']}|{fp}")
        guarded = rpt.guard_cached_report(report, case, AE_THR)
        case["report"] = guarded
        case["report_model"] = (
            "deterministic-assessment-guardrail"
            if case["behavioral_verdict"] != "reviewable"
            else rpt.SUBAGENT_LABEL if guarded else None
        )
        baked += guarded is not None
    print(f"reports: {baked}/{len(cases)} baked from cache (fp {fp}); "
          f"{len(cases) - baked} missing — run the gen-reports workflow to fill")

    (OUT / "queue.json").write_text(json.dumps(queue))
    (OUT / "operations.json").write_text(json.dumps(operations))
    (OUT / "cases.json").write_text(json.dumps(cases))
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # raw clean rows for the baked cases ONLY — the /api/simulate what-if re-injects + re-
    # scores these at serve time. Tiny (~2.5 MB for 250 segments) vs the 128 MB clean_df, so
    # the Docker image / HF Space stays lean (the full clean_df is never shipped).
    baked_sids = {c["segment_id"] for c in cases.values()}
    clean[clean.segment_id.isin(baked_sids)].to_parquet(OUT / "cases_raw.parquet")

    # ── verification (does the foundation reproduce Phase-7's signal?) ────────────────────
    an = np.array([scores[i] for i in range(len(seg_ids)) if seg_ids[i] in anomaly_ids])
    no = np.array([scores[i] for i in range(len(seg_ids)) if seg_ids[i] not in anomaly_ids])
    top_n = [seg_ids[i] for i in order[:50]]
    an_in_top = sum(1 for s in top_n if s in anomaly_ids)
    print("=" * 64)
    print("SADAR-merge precompute — foundation verification")
    print("=" * 64)
    print(f"cohort segments     : {len(seg_ids)}  (test {len(ids['test'])} + anomalies {len(anomaly_ids)})")
    print(f"anomalous @ thr {AE_THR}: {manifest['n_anomalous_at_thr']}")
    print(f"median score        : {median:.4f}")
    print(f"real-anomaly score  : mean {an.mean():.4f}  median {np.median(an):.4f}")
    print(f"normal score        : mean {no.mean():.4f}  median {np.median(no):.4f}")
    print(f"anomalies in top-50 : {an_in_top}/{len(anomaly_ids)} real anomalies")
    print(f"case files baked    : {len(cases)}")
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
