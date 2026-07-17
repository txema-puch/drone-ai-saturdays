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
`backend/research/src/sadar_research/trajectory_anomaly/evaluation/report_eval.py` (T=260, loss-masked `reconstruction_error(agg="mean")`,
val-chosen threshold 0.222) — NO re-tuning, NO model change. The cohort = the sealed 2020
TEST fold (post-hoc audit population) ∪ the held-aside real-anomaly cases (go-around ∪
emergency) so the queue has genuine anomalies to surface.

Run:  uv run --project backend/research python -m sadar_research.trajectory_anomaly.pipeline.precompute
Out:  .artifacts/research/trajectory-anomaly/demo/releases/<release_id>/
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from sadar_research.trajectory_anomaly.models import lstm_ae as ae  # noqa: E402
from sadar_research.trajectory_anomaly.pipeline.preprocessing import (  # noqa: E402
    AE_FEATURES,
    SCALER_FEATURES,
    to_sequences,
    to_sequences_loss_mask,
)
from sadar_research.trajectory_anomaly.evaluation.scoring import (  # noqa: E402
    forward_batched,
    per_feature_re,
    per_step_re,
    unscale_block,
)
from sadar_research.trajectory_anomaly.releases.artifacts import (  # noqa: E402
    ONLINE_INPUT_UNITS,
    build_model_contract,
    export_json_scaler,
    export_tensor_state_dict,
    weak_ecdf_percentile,
    write_cohort_score_reference,
    write_model_contract,
)
from sadar_research.trajectory_anomaly.demo.operations import (  # noqa: E402
    annotate_segment_refs,
    build_operation_summaries,
    case_identity,
    operation_ref,
    severity_band,
)
from sadar_research.trajectory_anomaly.evaluation.quality import assess_segment, is_terminal_window  # noqa: E402
from sadar_research.trajectory_anomaly.releases.schema import (  # noqa: E402
    RELEASE_SCHEMA_VERSION,
    ReleaseStore,
    sha256_file,
    write_release_manifest,
)
from sadar_research.trajectory_anomaly.releases.semantics import validate_release_semantics  # noqa: E402

# per-step channels baked alongside each case so the case-file temporal panel can trace
# any one over time (the attribution panel shows their aggregate contribution; this shows
# WHEN each diverged). Physical units, straight from clean_df (already unscaled).
CHANNELS = ["baroaltitude", "velocity", "vertrate", "dist_to_runway_m"]

T = 260
AE_THR = 0.222  # val-chosen operating point — frozen, never retuned here

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

ONLINE_INPUT_CONTRACT = {
    "input_schema_version": "opensky_raw_v1",
    "derivation_contract_version": "derivations_v1",
    "preprocessing_contract_version": "preprocessing_v1",
    "units": ONLINE_INPUT_UNITS,
}


def _git_commit(start: Path) -> str:
    """Return the source commit without introducing a volatile build field."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=start,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _input_record(path: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def _source_provenance(
    model_dir: Path,
    report_cache_path: Path,
    *,
    source_commit: str,
) -> dict[str, Any]:
    inputs = {
        name: _input_record(model_dir / name)
        for name in (
            "clean_df.parquet",
            "meta.parquet",
            "split_ids.json",
            "scaler.joblib",
            "lstm_ae_best.pt",
        )
    }
    burn_path = model_dir / "phase7_burn_results.json"
    if burn_path.exists():
        inputs[burn_path.name] = _input_record(burn_path)
    if report_cache_path.exists():
        inputs["reports_cache.json"] = _input_record(report_cache_path)
    return {"commit": source_commit, "inputs": inputs}


def _producing_versions() -> dict[str, str]:
    packages = ("numpy", "pandas", "scikit-learn", "torch")
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        **{package: importlib.metadata.version(package) for package in packages},
    }


def _report_binding_is_valid(case: Mapping[str, Any], threshold: float) -> bool:
    """Re-run the deterministic report guard over the exact baked evidence."""
    from sadar_research.trajectory_anomaly.evaluation import report as rpt

    report = case.get("report")
    return (
        isinstance(report, str)
        and rpt.guard_cached_report(report, dict(case), threshold) == report
    )


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


def cohort_percentiles(scores: np.ndarray) -> np.ndarray:
    """Apply the frozen inclusive weak-ECDF contract to one full-precision cohort."""
    reference = tuple(sorted(float(score) for score in scores))
    return np.asarray(
        [weak_ecdf_percentile(reference, float(score)) for score in scores],
        dtype="float64",
    )


def build_release_operation_summaries(queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build summaries without reclassifying a rounded display percentile at a band edge."""
    operations = build_operation_summaries(queue)
    for operation in operations:
        by_case_id = {row["case_id"]: row for row in operation["segments"]}
        operation["worst_band"] = by_case_id[operation["worst_case_id"]]["band"]
        behavioral_case_id = operation.get("behavioral_worst_case_id")
        operation["behavioral_worst_band"] = (
            by_case_id[behavioral_case_id]["band"] if behavioral_case_id is not None else None
        )
    return operations


def _export_model_release_artifacts(
    out: Path,
    *,
    model: Any,
    scaler: Any,
    scores: np.ndarray,
    scoring_contract: Mapping[str, Any],
) -> dict[str, Any]:
    model_out = out / "model"
    model_out.mkdir(parents=True)
    tensor_metadata = export_tensor_state_dict(model, model_out / "state_dict.pt")
    export_json_scaler(scaler, SCALER_FEATURES, model_out / "scaler.json")
    cohort_reference = write_cohort_score_reference(
        scores.astype("float64"), model_out / "cohort-score-reference.json"
    )
    model_contract = build_model_contract(
        model_class="LSTMAutoencoder",
        architecture=model.config,
        features=AE_FEATURES,
        scaler_features=SCALER_FEATURES,
        tensors=tensor_metadata,
        scoring_contract=scoring_contract,
        cohort_reference={
            key: cohort_reference[key]
            for key in ("count", "digest", "formula_id", "tie_policy")
        },
        producing_versions=_producing_versions(),
    )
    write_model_contract(model_contract, model_out / "model-contract.json")
    return model_contract


def build_demo_release(
    *,
    model_dir: Path,
    store_root: Path,
    report_cache_path: Path | None = None,
    source_commit: str | None = None,
    keep_failed_staging: bool = False,
) -> Path:
    """Bake, semantically validate, and atomically promote one immutable release."""
    model_dir = Path(model_dir)
    store_root = Path(store_root)
    report_cache_path = Path(report_cache_path or (store_root / "reports_cache.json"))
    source_commit = source_commit or _git_commit(model_dir)
    validation_context: dict[str, Any] = {}

    def write_staging(out: Path) -> None:
        _write_release_staging(
            out,
            model_dir=model_dir,
            report_cache_path=report_cache_path,
            source_commit=source_commit,
            validation_context=validation_context,
        )

    def validate_staging(staging: Path, manifest: Mapping[str, Any]) -> None:
        validate_release_semantics(
            staging,
            manifest,
            expected_online_contract=ONLINE_INPUT_CONTRACT,
            training_scaler=validation_context["training_scaler"],
            scaler_parity_vectors=validation_context["scaler_parity_vectors"],
            recomputed_scores_by_case_id=validation_context["scores_by_case_id"],
            report_validator=lambda case: _report_binding_is_valid(case, AE_THR),
        )

    release_path = ReleaseStore(store_root).build_release(
        write_staging,
        semantic_validator=validate_staging,
        keep_failed_staging=keep_failed_staging,
    )
    print(f"saved -> {release_path}")
    return release_path


def _write_release_staging(
    out: Path,
    *,
    model_dir: Path,
    report_cache_path: Path,
    source_commit: str,
    validation_context: dict[str, Any],
) -> None:
    clean = pd.read_parquet(model_dir / "clean_df.parquet")
    meta = pd.read_parquet(model_dir / "meta.parquet")
    ids = json.loads((model_dir / "split_ids.json").read_text())
    # Pickle-backed artifacts are trusted build inputs only. The promoted release contains
    # a strict JSON scaler and tensor-only state dict, never these Python objects.
    scaler = joblib.load(model_dir / "scaler.joblib")
    model = ae.load_checkpoint(str(model_dir / "lstm_ae_best.pt"))

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

    # Use the same pure terminal-window classifier as upload evaluation.
    terminal_map = {
        sid: is_terminal_window(group, window_length=T)
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

    # One inclusive weak-ECDF formula is shared by bake, What-If, and uploads. Preserve
    # the full unrounded cohort for model artifacts; rounding is display-only below.
    pct = cohort_percentiles(scores)

    def label_of(sid: str) -> str:
        if sid in anomaly_ids:
            return "emergency" if g.loc[sid, "is_em"] else "go_around"
        return "normal"

    # ── ranked queue (every segment) ──────────────────────────────────────────────────────
    order = np.argsort(-scores)
    queue = annotate_segment_refs([
        {
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
    # ── curated case files (heavy) ────────────────────────────────────────────────────────
    median = float(np.median(scores))
    pick = select_case_indices(seg_ids, scores, anomaly_ids)
    sc_idx = [AE_FEATURES.index(c) for c in SCALER_FEATURES]

    cases = {}
    for i in sorted(pick):
        sid = seg_ids[i]
        case_id, case_ref = case_identity(sid)
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
        cases[case_id] = {
            "case_id": case_id,
            "case_ref": case_ref,
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

    selected_case_ids = set(cases)
    for row in queue:
        row["has_case"] = row["case_id"] in selected_case_ids
    operations = build_release_operation_summaries(queue)

    # per-step threshold from NORMAL cases (99th pctile of valid per-step RE) — the
    # "this step is surprising" line for the case-file timeline; from normal behaviour only
    normal_steps = valid_normal_step_scores(step, loss_mask, seg_ids, anomaly_ids)
    step_thr = float(np.percentile(normal_steps, 99)) if normal_steps.size else AE_THR

    # ── metrics panel (Phase-7 results, MetricRow[] shape) — bundle-self-contained ────────
    burn_path = model_dir / "phase7_burn_results.json"
    burn = json.loads(burn_path.read_text()) if burn_path.exists() else {}
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

    summary = {
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
    from sadar_research.trajectory_anomaly.evaluation import report as rpt

    fp = rpt.prompt_fingerprint(rpt.SUBAGENT_LABEL)
    cache = json.loads(report_cache_path.read_text()) if report_cache_path.exists() else {}
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

    (out / "queue.json").write_text(json.dumps(queue, allow_nan=False, separators=(",", ":")))
    (out / "operations.json").write_text(
        json.dumps(operations, allow_nan=False, separators=(",", ":"))
    )
    (out / "cases.json").write_text(json.dumps(cases, allow_nan=False, separators=(",", ":")))
    (out / "metrics.json").write_text(
        json.dumps(metrics, allow_nan=False, separators=(",", ":"), sort_keys=True)
    )

    # raw clean rows for the baked cases ONLY — the /api/simulate what-if re-injects + re-
    # scores these at serve time. Tiny (~2.5 MB for 250 segments) vs the 128 MB clean_df, so
    # the Docker image / HF Space stays lean (the full clean_df is never shipped).
    baked_sids = {c["segment_id"] for c in cases.values()}
    clean[clean.segment_id.isin(baked_sids)].to_parquet(out / "cases_raw.parquet", index=False)

    # Safe serving artifacts: tensor-only weights, JSON scaler/contract, and the exact
    # unrounded score population used by every live percentile calculation.
    scoring_contract = {
        "T": T,
        "threshold": AE_THR,
        "step_threshold": float(step_thr),
        "feature_names": list(AE_FEATURES),
    }
    _export_model_release_artifacts(
        out,
        model=model,
        scaler=scaler,
        scores=scores,
        scoring_contract=scoring_contract,
    )

    manifest_payload = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "source": _source_provenance(
            model_dir, report_cache_path, source_commit=source_commit
        ),
        "prompt_fingerprint": fp,
        "report_coverage_count": baked,
        "scoring_contract": scoring_contract,
        "online_input_contract": ONLINE_INPUT_CONTRACT,
        **summary,
    }
    manifest = write_release_manifest(out, manifest_payload)

    scaler_vectors = cdf.loc[:, SCALER_FEATURES]
    finite_rows = np.isfinite(scaler_vectors.to_numpy(dtype="float64")).all(axis=1)
    scaler_vectors = scaler_vectors.loc[finite_rows]
    if len(scaler_vectors) == 0:
        raise ValueError("cannot validate JSON scaler parity without finite cohort vectors")
    if len(scaler_vectors) > 64:
        scaler_vectors = scaler_vectors.iloc[
            np.linspace(0, len(scaler_vectors) - 1, 64, dtype=int)
        ]
    scores_by_segment = dict(zip(seg_ids, map(float, scores), strict=True))
    validation_context.update(
        training_scaler=scaler,
        scaler_parity_vectors=scaler_vectors,
        scores_by_case_id={
            row["case_id"]: scores_by_segment[row["segment_id"]]
            for row in queue
        },
    )

    # ── verification (does the foundation reproduce Phase-7's signal?) ────────────────────
    an = np.array([scores[i] for i in range(len(seg_ids)) if seg_ids[i] in anomaly_ids])
    no = np.array([scores[i] for i in range(len(seg_ids)) if seg_ids[i] not in anomaly_ids])
    top_n = [seg_ids[i] for i in order[:50]]
    an_in_top = sum(1 for s in top_n if s in anomaly_ids)
    print("=" * 64)
    print("SADAR-merge precompute — foundation verification")
    print("=" * 64)
    print(f"cohort segments     : {len(seg_ids)}  (test {len(ids['test'])} + anomalies {len(anomaly_ids)})")
    print(f"release             : {manifest['release_id']}")
    print(f"anomalous @ thr {AE_THR}: {summary['n_anomalous_at_thr']}")
    print(f"median score        : {median:.4f}")
    print(f"real-anomaly score  : mean {an.mean():.4f}  median {np.median(an):.4f}")
    print(f"normal score        : mean {no.mean():.4f}  median {np.median(no):.4f}")
    print(f"anomalies in top-50 : {an_in_top}/{len(anomaly_ids)} real anomalies")
    print(f"case files baked    : {len(cases)}")
    print(f"staged files        : {out}")


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description="Bake an immutable SADAR demo release")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-cache", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--keep-failed-staging", action="store_true")
    args = parser.parse_args(argv)
    return build_demo_release(
        model_dir=args.model_dir,
        store_root=args.output_root,
        report_cache_path=args.report_cache,
        source_commit=args.source_commit,
        keep_failed_staging=args.keep_failed_staging,
    )


if __name__ == "__main__":
    main()
