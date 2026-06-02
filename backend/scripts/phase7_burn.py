"""Phase-7 TEST BURN — the one-shot sealed-fold evaluation (issue #29).

Scores the SEALED 2020 test fold (firewall: fold='test', burned once here). Runs all
three models per the user-amended Layer-6 protocol (report all, drop none):
  - our LSTM-AE (small/mean, threshold 0.222)   — backend/models/phase6/lstm_ae_best.pt
  - our frozen kNN-on-summary (k=5)             — knn_train_summary.npy + scaler.joblib
  - IsolationForest baseline (D-006)            — refit on TRAIN-normal

SADAR's VAE-LSTM runs on its NATIVE rep (external/sadar) — reported alongside, not
on our fold (cross-feature translation forbidden by the pre-registration).

Synthetic uses the D-012 re-weighted mix (zone OUT of headline, kept as diagnostic).
Real-anomaly uses the held-aside cohort vs 2020-test-normal (SADAR-comparable, post-burn).

Deterministic: seed 42, frozen artifacts, fixed Monday->fold map.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core import lstm_ae as ae  # noqa: E402
from backend.core.baseline import (  # noqa: E402
    IsolationForestBaseline,
    KNNSummaryBaseline,
)
from backend.core.inject import DEFAULT_MIX, INJECTION_KINDS, make_eval_set  # noqa: E402
from backend.core.preprocessing import (  # noqa: E402
    SCALER_FEATURES,
    make_scaler,
    to_sequences,
    to_sequences_loss_mask,
)

M = REPO / "backend/models/phase6"
SEED = 42
T = 260
AE_THR = 0.222  # val-chosen operating point (NO re-tuning on test)
DYN = ["altitude_high", "sustained_loiter", "final_approach_intercept", "speed_spike"]


def f2(y, pred):
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return (5 * p * r / (4 * p + r)) if (4 * p + r) else 0.0


def fpr(y, pred):
    fp = int(((pred == 1) & (y == 0)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    return fp / (fp + tn) if fp + tn else 0.0


def main():
    clean = pd.read_parquet(M / "clean_df.parquet")
    meta = pd.read_parquet(M / "meta.parquet")
    ids = json.load(open(M / "split_ids.json"))
    scaler = joblib.load(M / "scaler.joblib")

    model = ae.load_checkpoint(str(M / "lstm_ae_best.pt"))
    knn = KNNSummaryBaseline.from_reference(np.load(M / "knn_train_summary.npy"), k=5)

    train_df = clean[clean.segment_id.isin(set(ids["train"]))]
    X_tr, _, _ = to_sequences(train_df, T, scaler)
    m_tr = to_sequences_loss_mask(train_df, T)
    iforest = IsolationForestBaseline.fit(X_tr, m_tr, seed=SEED)

    def score_all(X, mask):
        return {
            "AE": ae.reconstruction_error(model, X, mask, agg="mean"),
            "kNN": knn.anomaly_score(X, mask),
            "IF": iforest.anomaly_score(X, mask),
        }

    rng = np.random.default_rng(SEED)
    print("=" * 70)
    print("PHASE-7 TEST BURN — sealed 2020 fold (firewall opens here, once)")
    print(f"test segments: {len(ids['test'])} | T={T} | D-012 mix (zone OUT): {DEFAULT_MIX}")
    print("=" * 70)

    # ---- 1. headline: D-012 mixed synthetic on TEST ----
    mixed = make_eval_set(clean, ids["test"], scaler, T, seed=SEED, fold="test",
                          inject_rate=0.5, mix=DEFAULT_MIX)
    sc = score_all(mixed.X, mixed.loss_mask)
    print("\n[1] HEADLINE — D-012 mixed synthetic (4 dynamic types), TEST fold")
    print(f"    {'model':6}{'AUROC':>8}{'PR-AUC':>8}")
    head = {}
    for k in ("AE", "kNN", "IF"):
        au = roc_auc_score(mixed.y, sc[k]); pr = average_precision_score(mixed.y, sc[k])
        head[k] = au
        print(f"    {k:6}{au:8.3f}{pr:8.3f}")

    # bootstrap CI on AE headline AUROC
    boot = []
    n = len(mixed.y)
    for _ in range(1000):
        idx = rng.integers(0, n, n)
        if len(np.unique(mixed.y[idx])) < 2:
            continue
        boot.append(roc_auc_score(mixed.y[idx], sc["AE"][idx]))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"    AE headline AUROC 95% CI: [{lo:.3f}, {hi:.3f}]  (target > 0.85)")

    # ---- 2. AE operating point at val threshold 0.222 ----
    pred = (sc["AE"] >= AE_THR).astype(int)
    print(f"\n[2] AE OPERATING POINT (thr {AE_THR}, val-chosen, no retune)")
    print(f"    F2 {f2(mixed.y, pred):.3f} | FPR {fpr(mixed.y, pred):.3f} (guardrail <=0.15) "
          f"| recall {((pred==1)&(mixed.y==1)).sum()/max(mixed.y.sum(),1):.3f}")

    # ---- 3. per-type (incl zone = out-of-remit diagnostic) ----
    print("\n[3] PER-TYPE AUROC, TEST (zone = out-of-remit diagnostic, not in headline)")
    print(f"    {'type':26}{'AE':>7}{'kNN':>7}{'IF':>7}")
    pertype = {k: {} for k in ("AE", "kNN", "IF")}
    for kind in INJECTION_KINDS:
        s1 = make_eval_set(clean, ids["test"], scaler, T, seed=SEED, fold="test",
                           inject_rate=0.5, mix={kind: 1.0})
        ss = score_all(s1.X, s1.loss_mask)
        row = f"    {kind:26}"
        for k in ("AE", "kNN", "IF"):
            a = roc_auc_score(s1.y, ss[k]); pertype[k][kind] = a
            row += f"{a:7.3f}"
        print(row + ("   <- out-of-remit" if kind == "zone_violation" else ""))

    # ---- 4. real-anomaly on TEST-normal (SADAR-comparable) ----
    g = meta.groupby("segment_id").agg(is_ga=("is_go_around", "max"), is_em=("is_emergency", "max"))
    held = set(ids["held_aside"])
    cohort_ids = sorted([s for s in g.index if s in held and (g.loc[s, "is_ga"] or g.loc[s, "is_em"])])
    test_df = clean[clean.segment_id.isin(set(ids["test"]))]
    Xt, _, _ = to_sequences(test_df, T, scaler); mt = to_sequences_loss_mask(test_df, T)
    cdf = clean[clean.segment_id.isin(set(cohort_ids))]
    Xc, _, _ = to_sequences(cdf, T, scaler); mc = to_sequences_loss_mask(cdf, T)
    st = score_all(Xt, mt); scoh = score_all(Xc, mc)
    print("\n[4] REAL-ANOMALY — held-aside cohort vs 2020-TEST-normal (SADAR-comparable)")
    print(f"    cohort {len(cohort_ids)} vs test-normal {len(ids['test'])} "
          f"| prevalence {len(cohort_ids)/(len(cohort_ids)+len(ids['test'])):.3f}")
    print(f"    {'model':6}{'ROC':>8}{'PR':>8}")
    for k in ("AE", "kNN", "IF"):
        y = np.r_[np.zeros(len(st[k])), np.ones(len(scoh[k]))]
        s = np.r_[st[k], scoh[k]]
        print(f"    {k:6}{roc_auc_score(y,s):8.3f}{average_precision_score(y,s):8.3f}")
    print("    SADAR  VAE-LSTM (native, his 2020-normal): ROC 0.659 PR 0.299 (reproduced)")

    out = {
        "headline_auroc": head, "headline_ae_ci": [float(lo), float(hi)],
        "per_type": pertype, "n_test": len(ids["test"]), "cohort_n": len(cohort_ids),
    }
    (M / "phase7_burn_results.json").write_text(json.dumps(out, indent=2))
    print(f"\nsaved -> {M/'phase7_burn_results.json'}")


if __name__ == "__main__":
    main()
