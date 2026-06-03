"""SADAR-merge (Direction C) — serve-time data precompute.

Mirrors the role of SADAR's `data/processed/test.npy`, but produces the artifacts a
POST-HOC analyst-triage UI needs (design doc §4.5), not a live monitor's window array:

  - a RANKED QUEUE  — every scored segment, ordered most→least anomalous, with its label
                      (normal / go_around / emergency) and AE window score.
  - per-flight CASE FILES — for a curated subset: the raw lat/lon/alt path, the model's
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
import torch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core import lstm_ae as ae  # noqa: E402
from backend.core.preprocessing import (  # noqa: E402
    AE_FEATURES,
    SCALER_FEATURES,
    to_sequences,
    to_sequences_loss_mask,
)

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


# ── scoring helpers (mirror lstm_ae.reconstruction_error internals, add per-step + recon) ──

@torch.no_grad()
def forward_batched(model: ae.LSTMAutoencoder, X: np.ndarray, mask: np.ndarray,
                    batch_size: int = 256) -> np.ndarray:
    """Model reconstruction for every window, in scaled feature space `(N, T, 9)`."""
    model.eval()
    Xt = torch.from_numpy(np.ascontiguousarray(X)).float()
    Mt = torch.from_numpy(np.ascontiguousarray(mask)).float()
    out = []
    for i in range(0, len(Xt), batch_size):
        out.append(model(Xt[i:i + batch_size], Mt[i:i + batch_size]).cpu().numpy())
    return np.concatenate(out) if out else np.empty_like(X)


def per_step_re(recon: np.ndarray, X: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-timestep masked mean-SE `(N, T)` — the case-file score timeline. Equal-weighted
    across the 9 features (same as the loss), masked positions zeroed."""
    se = ((recon - X) ** 2).mean(axis=2)            # (N,T)
    return se * mask


def per_feature_re(recon: np.ndarray, X: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-feature masked mean-SE `(N, 9)` — attribution (which channel drove the score).
    DIAGNOSTIC ONLY (never a tuning knob, per the feature contract note)."""
    se = (recon - X) ** 2                            # (N,T,9)
    m = mask[:, :, None]
    denom = m.sum(axis=1).clip(min=1.0)              # (N,1)
    return (se * m).sum(axis=1) / denom              # (N,9)


# ── path reconstruction (scaled 6-vector → real lat/lon/alt) ──────────────────────────────

def unscale_block(scaled_6: np.ndarray, scaler) -> np.ndarray:
    """Inverse-transform the SCALER_FEATURES block `(*, 6)` back to physical units."""
    flat = scaled_6.reshape(-1, len(SCALER_FEATURES))
    return scaler.inverse_transform(flat).reshape(scaled_6.shape)


def main() -> None:
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

    # score (loss-masked mean RE — the shipped contract)
    scores = ae.reconstruction_error(model, X, loss_mask, agg="mean")
    recon = forward_batched(model, X, loss_mask)
    step = per_step_re(recon, X, loss_mask)
    feat = per_feature_re(recon, X, loss_mask)

    def label_of(sid: str) -> str:
        if sid in anomaly_ids:
            return "emergency" if g.loc[sid, "is_em"] else "go_around"
        return "normal"

    # ── ranked queue (every segment) ──────────────────────────────────────────────────────
    order = np.argsort(-scores)
    queue = [
        {
            "id": int(i),
            "segment_id": seg_ids[i],
            "score": round(float(scores[i]), 6),
            "anomalous": bool(scores[i] >= AE_THR),
            "label": label_of(seg_ids[i]),
        }
        for i in order
    ]

    # ── curated case files (heavy) ────────────────────────────────────────────────────────
    median = float(np.median(scores))
    typical_rank = np.argsort(np.abs(scores - median))
    pick = set(np.where(np.isin(seg_ids, list(anomaly_ids)))[0].tolist())   # all real anomalies
    pick |= set(order[:N_TOP_NORMAL].tolist())                              # most-anomalous
    pick |= set(typical_rank[:N_TYPICAL].tolist())                         # typical sample
    sc_idx = [AE_FEATURES.index(c) for c in SCALER_FEATURES]

    cases = {}
    for i in sorted(pick):
        sid = seg_ids[i]
        seg = clean[clean.segment_id == sid].sort_values("time").head(T)
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
        cases[str(i)] = {
            "id": int(i),
            "segment_id": sid,
            "label": label_of(sid),
            "score": round(float(scores[i]), 6),
            "threshold": AE_THR,
            "anomalous": bool(scores[i] >= AE_THR),
            "valid_steps": valid,
            "path": path,
            "reconstructed": recon_path,
            "step_scores": [round(float(s), 6) for s in step[i, :nrows]],
            "feature_attribution": {f: round(float(v), 6) for f, v in zip(AE_FEATURES, feat[i])},
        }

    # per-step threshold from NORMAL cases (99th pctile of valid per-step RE) — the
    # "this step is surprising" line for the case-file timeline; from normal behaviour only
    normal_steps = np.array(
        [step[i, t] for i in range(len(seg_ids)) if seg_ids[i] not in anomaly_ids
         for t in range(int(loss_mask[i].sum()))]
    )
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
        "n_test": len(ids["test"]),
        "n_real_anomalies": len(anomaly_ids),
        "n_anomalous_at_thr": int((scores >= AE_THR).sum()),
        "n_cases_baked": len(cases),
        "threshold": AE_THR,
        "step_threshold": round(step_thr, 6),
        "T": T,
        "median_score": round(median, 6),
        "center": {"lat": 40.4936, "lon": -3.5668},
        "step_seconds": 10,
    }
    (OUT / "queue.json").write_text(json.dumps(queue))
    (OUT / "cases.json").write_text(json.dumps(cases))
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

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
