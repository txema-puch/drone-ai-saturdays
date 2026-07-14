"""SADAR-merge (Direction C) — shared scoring core for the serve layer.

The exact frozen Phase-6/7 contract (T=260, loss-masked mean RE, the val-chosen
operating point), factored out of `precompute.py` so the build-time bundle bake AND
the live `/api/simulate` what-if score segments through one code path — no drift
between "what the queue shows" and "what re-scoring computes".

`precompute.py` imports the array helpers here; `app.py`'s simulate endpoint imports
`simulate_segment`. Torch is imported here, so app.py only touches this module lazily
(first simulate call) — read endpoints keep a torch-free cold start.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import torch

from backend.core import lstm_ae as ae
from backend.core.features import apply_segment_derivations
from backend.core.inject import INJECTION_KINDS, inject_segment, onset_index
from backend.core.preprocessing import (
    AE_FEATURES,
    MASKED_FEATURES,
    SCALER_FEATURES,
    to_sequences,
    to_sequences_loss_mask,
)
from backend.serve.operations import severity_band
from backend.serve.model_artifacts import weak_ecdf_percentile
from backend.serve.quality import assess_segment, is_terminal_window

# measured continuous channels the intensity knob interpolates (heading is a measured
# handle but no §6 kind perturbs it; onground/*_missing are categorical → taken from
# the perturbed frame, not blended).
_BLEND_COLS = ["lat", "lon", "baroaltitude", "velocity", "vertrate"]

# per-step channels exposed for the temporal-panel selector (physical units)
_CHANNEL_COLS = ["baroaltitude", "velocity", "vertrate", "dist_to_runway_m"]


# ── array helpers (mirror lstm_ae.reconstruction_error internals) ──────────────────────────

@torch.no_grad()
def forward_batched(model: ae.LSTMAutoencoder, X: np.ndarray, mask: np.ndarray,
                    batch_size: int = 256) -> np.ndarray:
    """Model reconstruction for every window, scaled feature space `(N, T, 9)`."""
    model.eval()
    Xt = torch.from_numpy(np.ascontiguousarray(X)).float()
    Mt = torch.from_numpy(np.ascontiguousarray(mask)).float()
    out = []
    for i in range(0, len(Xt), batch_size):
        out.append(model(Xt[i:i + batch_size], Mt[i:i + batch_size]).cpu().numpy())
    return np.concatenate(out) if out else np.empty_like(X)


def per_step_re(recon: np.ndarray, X: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-timestep masked mean-SE `(N, T)` — the case-file score timeline."""
    se = ((recon - X) ** 2).mean(axis=2)
    return se * mask


def per_feature_re(recon: np.ndarray, X: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-feature masked mean-SE `(N, 9)` — attribution (diagnostic only)."""
    se = (recon - X) ** 2
    m = mask[:, :, None]
    denom = m.sum(axis=1).clip(min=1.0)
    return (se * m).sum(axis=1) / denom


def unscale_block(scaled_6: np.ndarray, scaler) -> np.ndarray:
    """Inverse-transform the SCALER_FEATURES block `(*, 6)` back to physical units."""
    flat = scaled_6.reshape(-1, len(SCALER_FEATURES))
    return scaler.inverse_transform(flat).reshape(scaled_6.shape)


def score_segments(
    clean_df: pd.DataFrame,
    *,
    T: int,
    scaler,
    model,
    batch_size: int = 256,
) -> dict:
    """Vectorized frozen-model inference for one or more preprocessed segments."""
    X, _, info = to_sequences(clean_df, T, scaler)
    loss_mask = to_sequences_loss_mask(clean_df, T)
    if len(info) == 0:
        return {
            "segment_ids": [],
            "scores": np.empty(0, dtype="float64"),
            "reconstruction": np.empty_like(X),
            "step_scores": np.empty((0, T), dtype="float32"),
            "feature_scores": np.empty((0, len(AE_FEATURES)), dtype="float32"),
            "loss_mask": loss_mask,
        }
    reconstruction = forward_batched(model, X, loss_mask, batch_size=batch_size)
    step_scores = per_step_re(reconstruction, X, loss_mask)
    scores = step_scores.sum(axis=1) / loss_mask.sum(axis=1).clip(min=1.0)
    scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0).astype("float32")
    return {
        "segment_ids": info["segment_id"].astype(str).tolist(),
        "scores": scores,
        "reconstruction": reconstruction,
        "step_scores": step_scores,
        "feature_scores": per_feature_re(reconstruction, X, loss_mask),
        "loss_mask": loss_mask,
    }


def assemble_segment_evidence(
    segment: pd.DataFrame,
    scored: dict,
    index: int,
    *,
    evaluation_ref: str,
    T: int,
    scaler,
    threshold: float,
    step_threshold: float,
    cohort_scores,
    center: dict[str, float],
    step_seconds: int,
) -> dict:
    """Build the upload-only evidence allowlist for one aligned scored segment."""
    ordered = segment.sort_values("time")
    window = ordered.head(T)
    nrows = len(window)
    score = float(scored["scores"][index])
    valid_steps = int(scored["loss_mask"][index].sum())
    truncated = len(ordered) > T
    terminal = is_terminal_window(ordered, window_length=T)
    assessment = assess_segment(
        window,
        valid_steps=valid_steps,
        n_steps=len(ordered),
        truncated=truncated,
        terminal_op=terminal,
    )
    t0 = int(window["time"].iloc[0])
    path = [
        {"lat": float(lat), "lon": float(lon), "alt": float(alt), "t": int(time - t0)}
        for lat, lon, alt, time in zip(
            window["lat"], window["lon"], window["baroaltitude"], window["time"]
        )
    ]
    scaler_indices = [AE_FEATURES.index(name) for name in SCALER_FEATURES]
    physical = unscale_block(
        scored["reconstruction"][index, :nrows][:, scaler_indices], scaler
    )
    lat_index = SCALER_FEATURES.index("lat")
    lon_index = SCALER_FEATURES.index("lon")
    altitude_index = SCALER_FEATURES.index("baroaltitude")
    reconstructed = [
        {
            "lat": float(row[lat_index]),
            "lon": float(row[lon_index]),
            "alt": float(row[altitude_index]),
        }
        for row in physical
    ]
    percentile = weak_ecdf_percentile(cohort_scores, score)
    return {
        "evaluation_ref": evaluation_ref,
        "segment_id": str(window["segment_id"].iloc[0]),
        "model_status": "above_threshold" if score >= threshold else "below_threshold",
        "path": path,
        "reconstructed": reconstructed,
        "scores": [round(float(value), 6) for value in scored["step_scores"][index, :nrows]],
        "window_score": round(score, 6),
        "pct": round(percentile, 1),
        "threshold": float(threshold),
        "step_threshold": float(step_threshold),
        "valid_steps": valid_steps,
        "n_steps": int(len(ordered)),
        **assessment,
        "feature_attribution": {
            name: round(float(value), 6)
            for name, value in zip(AE_FEATURES, scored["feature_scores"][index])
        },
        "channels": {
            name: [round(float(value), 4) for value in window[name]]
            for name in _CHANNEL_COLS
        },
        "center": {"lat": float(center["lat"]), "lon": float(center["lon"])},
        "step_seconds": int(step_seconds),
    }


# ── single-segment scoring (the simulate path) ─────────────────────────────────────────────

def _stable_seed(segment_id: str, kind: str) -> int:
    """Deterministic per (segment, kind) seed so re-clicking the same what-if is stable
    (and undo/redo never shifts the result). Salted only by the inputs, not the process."""
    digest = hashlib.sha256(f"{segment_id}|{kind}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def score_frame(seg: pd.DataFrame, T: int, scaler, model) -> dict:
    """Window + scale + score one per-segment frame through the frozen contract. Returns
    the window score, the per-step RE timeline trimmed to the kept rows, and the raw
    lat/lon/alt path (we store lat/lon natively — no inverse-projection)."""
    X, _, _ = to_sequences(seg, T, scaler)
    mask = to_sequences_loss_mask(seg, T)
    score = float(ae.reconstruction_error(model, X, mask, agg="mean")[0])
    recon = forward_batched(model, X, mask)
    step = per_step_re(recon, X, mask)[0]
    nrows = min(len(seg), T)
    s = seg.sort_values("time").head(nrows)
    t0 = int(s["time"].iloc[0])
    path = [
        {"lat": float(la), "lon": float(lo), "alt": float(al), "t": int(tt - t0)}
        for la, lo, al, tt in zip(s["lat"], s["lon"], s["baroaltitude"], s["time"])
    ]
    channels = {c: [round(float(v), 4) for v in s[c]] for c in _CHANNEL_COLS}
    return {
        "window_score": score,
        "step_scores": [round(float(v), 6) for v in step[:nrows]],
        "path": path,
        "channels": channels,
        "valid_steps": int(mask[0].sum()),
    }


def simulate_segment(
    seg: pd.DataFrame,
    kind: str,
    intensity: float,
    onset: float,
    *,
    scaler,
    model,
    T: int,
    threshold: float,
    step_threshold: float,
    cohort_scores: np.ndarray,
) -> dict:
    """Analyst what-if: inject `kind` into the real segment via the FROZEN §6 generator,
    interpolate the kinematic perturbation by `intensity` (0 = clean … 1 = the full §6
    anomaly), re-derive, then re-score against the same model. Deterministic per
    (segment, kind). Returns the perturbed path + per-step RE + score/percentile/band +
    the onset step, so the frontend overlays it on the original case charts.
    """
    if kind not in INJECTION_KINDS:
        raise ValueError(f"unknown injection kind {kind!r}")
    intensity = float(np.clip(intensity, 0.0, 1.0))
    onset = float(np.clip(onset, 0.0, 1.0))

    base = seg.sort_values("time").reset_index(drop=True).copy()
    sid = str(base["segment_id"].iloc[0])
    if intensity == 0.0:
        perturbed = base
        onset_idx = onset_index(min(len(base), T), onset)
    else:
        rng = np.random.default_rng(_stable_seed(sid, kind))
        perturbed, onset_idx = inject_segment(
            base, kind, rng, onset_fraction=onset, window_len=T,
        )

    if 0.0 < intensity < 1.0:
        for c in _BLEND_COLS:
            b = base[c].to_numpy()
            perturbed[c] = b + intensity * (perturbed[c].to_numpy() - b)
        perturbed = apply_segment_derivations(perturbed)  # re-derive dist from blended lat/lon
        miss = [f + "_missing" for f in MASKED_FEATURES if f + "_missing" in perturbed.columns]
        if miss:
            perturbed.loc[perturbed.index[onset_idx:], miss] = False

    scored = score_frame(perturbed, T, scaler, model)
    score = scored["window_score"]
    pct = weak_ecdf_percentile(tuple(sorted(float(value) for value in cohort_scores)), score)
    return {
        "kind": kind,
        "intensity": round(intensity, 3),
        "onset": round(onset, 3),
        "onset_index": int(onset_idx),
        "path": scored["path"],
        "channels": scored["channels"],
        "scores": scored["step_scores"],
        "window_score": round(score, 6),
        "pct": round(pct, 1),
        "band": severity_band(pct),
        "anomalous": bool(score >= threshold),
        "threshold": threshold,
        "step_threshold": step_threshold,
        "valid_steps": scored["valid_steps"],
    }
