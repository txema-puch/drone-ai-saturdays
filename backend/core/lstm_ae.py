"""Phase 6 — the LSTM Autoencoder (D-006 primary model).

Unsupervised sequence reconstructor: train on TRAIN-normal windows only, score anything by
its masked reconstruction error (RE). Higher RE = further from the learned normal manifold =
more anomalous. The bake-off (notebook 09) compares its val AUROC to the IF baseline under
the D-006 rule (ship AE iff `AE_AUROC ≥ IF_AUROC + 0.03`).

    x (N,T,9) ─► Encoder LSTM ─► last hidden ─► Linear ─► z (latent, the BOTTLENECK)
                                                          │
            recon (N,T,9) ◄─ Linear ◄─ Decoder LSTM ◄─ repeat z across T

DESIGN CHOICES (D-006 + eng review):
  - SMALL by default (1 layer, 32 hidden, 16 latent). An anomaly-detection AE wants the
    SMALLEST model that still reconstructs normal well: too large and it reconstructs
    anomalies too (the identity-function trap), collapsing the RE signal. Grow only if the
    train/val curves show underfit (design doc: start train=2017-18, widen on evidence).
  - MASKED reconstruction loss — excludes padding AND imputed rows (zero gradient there): a
    row Phase 3 interpolated carries no ground truth, and padding is not data. The mask is
    `to_sequences_loss_mask` (preprocessing.py), shared with the IF baseline + the scorer.
  - EQUAL-WEIGHTED across features (P5 carry-forward, 07-eval-prep.md §6 reconciliation): no
    per-feature down-weight. Per-feature RE is a diagnostic only, never a tuning knob.

CPU-trainable (small model, ~9k train sequences). Deterministic given a seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn as nn

from backend.core.preprocessing import AE_FEATURES

N_FEATURES = len(AE_FEATURES)  # 9


def set_seed(seed: int) -> None:
    """Pin every RNG the training loop touches (guardrail: reproducible curves)."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


# ── model ─────────────────────────────────────────────────────────────────────

class LSTMAutoencoder(nn.Module):
    """Seq2seq LSTM autoencoder with a linear latent bottleneck."""

    def __init__(self, n_features: int = N_FEATURES, hidden: int = 32,
                 latent: int = 16, num_layers: int = 1):
        super().__init__()
        self.config = {"n_features": n_features, "hidden": hidden,
                       "latent": latent, "num_layers": num_layers}
        self.encoder = nn.LSTM(n_features, hidden, num_layers, batch_first=True)
        self.enc_to_latent = nn.Linear(hidden, latent)
        self.latent_to_dec = nn.Linear(latent, hidden)
        self.decoder = nn.LSTM(hidden, hidden, num_layers, batch_first=True)
        self.output = nn.Linear(hidden, n_features)

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        n, t, _ = x.shape
        enc_out, (h, _) = self.encoder(x)        # enc_out: (N, T, hidden); h: (layers, N, hidden)
        if mask is not None:
            # Bottleneck = encoder state right after the LAST VALID timestep, not after the
            # trailing padding (codex finding #2). enc_out[i, k] is the state having consumed
            # rows 0..k, so gathering at last-valid-index gives the pad-free representation.
            last = (mask > 0).to(torch.long).sum(dim=1).clamp(min=1) - 1          # (N,)
            idx = last.view(n, 1, 1).expand(n, 1, enc_out.shape[-1])
            summary = enc_out.gather(1, idx).squeeze(1)                           # (N, hidden)
        else:
            summary = h[-1]                       # no mask → final timestep (back-compat)
        z = self.enc_to_latent(summary)          # (N, latent) — the bottleneck
        dec_seed = self.latent_to_dec(z)         # (N, hidden)
        dec_in = dec_seed.unsqueeze(1).expand(n, t, dec_seed.shape[-1])
        dec_out, _ = self.decoder(dec_in)        # (N, T, hidden)
        return self.output(dec_out)              # (N, T, 9)


# ── masked, equal-weighted reconstruction loss + score ────────────────────────

def masked_mse(recon: torch.Tensor, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Mean squared error over VALID timesteps only, equal-weighted across the 9 features.
    `mask` (N,T): 1 = real observed timestep, 0 = padding OR imputed. Masked positions get
    zero gradient (they multiply out), so the AE is never trained to reconstruct them.
    """
    se = ((recon - x) ** 2).mean(dim=2)          # (N,T) — equal feature weight
    m = mask.to(se.dtype)
    return (se * m).sum() / m.sum().clamp(min=1.0)


@torch.no_grad()
def reconstruction_error(model: LSTMAutoencoder, X: np.ndarray, mask: np.ndarray,
                         *, batch_size: int = 256, agg: str = "mean",
                         topk_frac: float = 0.1) -> np.ndarray:
    """Per-window anomaly score (higher = more anomalous). Eval mode, no grad. `(N,)` array.

    `agg` controls how the per-timestep masked SE is collapsed to one score:
      - "mean" — masked mean over valid timesteps (the conservative default).
      - "max"  — worst valid timestep. Injected anomalies are LOCALIZED post-onset, so the
                 normal prefix dilutes a mean; the max concentrates on the anomalous span.
      - "topk" — mean of the top `topk_frac·T` valid timesteps (a robust middle ground;
                 less spiky than max, still anomaly-focused).
    Masked (padding/imputed) timesteps never enter any aggregation.
    """
    model.eval()
    if X.shape[0] == 0:
        return np.empty(0, dtype="float32")
    scores = []
    Xt = torch.from_numpy(np.ascontiguousarray(X)).float()
    Mt = torch.from_numpy(np.ascontiguousarray(mask)).float()
    T = Xt.shape[1]
    k = max(1, int(round(topk_frac * T)))
    for i in range(0, len(Xt), batch_size):
        xb, mb = Xt[i:i + batch_size], Mt[i:i + batch_size]
        se = ((model(xb, mb) - xb) ** 2).mean(dim=2)          # (b,T) equal feature weight
        if agg == "mean":
            re = (se * mb).sum(dim=1) / mb.sum(dim=1).clamp(min=1.0)
        elif agg == "max":
            re = se.masked_fill(mb == 0, float("-inf")).max(dim=1).values
        elif agg == "topk":
            vals = se.masked_fill(mb == 0, float("-inf")).topk(k, dim=1).values
            re = torch.nanmean(vals.masked_fill(torch.isinf(vals), float("nan")), dim=1)
        else:
            raise ValueError(f"unknown agg {agg!r}; expected mean|max|topk")
        # A fully-masked window (every row imputed, e.g. a segment with no observed
        # heading) yields -inf (max) or nan (topk). It carries no reconstructable signal →
        # score it least-anomalous (0.0) rather than poison the metric.
        re = torch.nan_to_num(re, nan=0.0, posinf=0.0, neginf=0.0)
        scores.append(re.cpu().numpy())
    return np.concatenate(scores).astype("float32")


# ── training loop (logs train + val every epoch — guardrail #7) ───────────────

@dataclass
class TrainHistory:
    train_loss: list[float] = field(default_factory=list)
    val_loss: list[float] = field(default_factory=list)
    best_epoch: int = -1
    best_val: float = float("inf")


def train_autoencoder(
    X_train: np.ndarray, mask_train: np.ndarray,
    X_val: np.ndarray | None = None, mask_val: np.ndarray | None = None,
    *,
    hidden: int = 32, latent: int = 16, num_layers: int = 1,
    lr: float = 1e-3, max_epochs: int = 50, patience: int = 8,
    batch_size: int = 128, grad_clip: float = 1.0, seed: int = 42,
    verbose: bool = False,
) -> tuple[LSTMAutoencoder, TrainHistory]:
    """Train on TRAIN-normal windows; early-stop on val loss; keep the best-val weights.

    Returns `(model, history)` where `history` carries per-epoch train/val loss for the
    learning-curve plot. If no val set is given, early-stops on train loss instead.
    """
    set_seed(seed)
    n_features = X_train.shape[-1]          # infer from data (9 for the contract; 11 with ENU x/y)
    model = LSTMAutoencoder(n_features, hidden, latent, num_layers)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    gen = torch.Generator().manual_seed(seed)

    Xt = torch.from_numpy(np.ascontiguousarray(X_train)).float()
    Mt = torch.from_numpy(np.ascontiguousarray(mask_train)).float()
    has_val = X_val is not None and len(X_val) > 0
    if has_val:
        Xv = torch.from_numpy(np.ascontiguousarray(X_val)).float()
        Mv = torch.from_numpy(np.ascontiguousarray(mask_val)).float()

    hist = TrainHistory()
    best_state, since_improve = None, 0
    n = len(Xt)

    for epoch in range(max_epochs):
        model.train()
        perm = torch.randperm(n, generator=gen)
        epoch_loss, seen = 0.0, 0
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            xb, mb = Xt[idx], Mt[idx]
            opt.zero_grad()
            loss = masked_mse(model(xb, mb), xb, mb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            opt.step()
            epoch_loss += loss.item() * len(idx); seen += len(idx)
        train_loss = epoch_loss / max(seen, 1)
        hist.train_loss.append(train_loss)

        if has_val:
            model.eval()
            with torch.no_grad():
                val_loss = masked_mse(model(Xv, Mv), Xv, Mv).item()
        else:
            val_loss = train_loss
        hist.val_loss.append(val_loss)

        if verbose:
            print(f"epoch {epoch:3d}  train {train_loss:.5f}  val {val_loss:.5f}")

        if val_loss < hist.best_val - 1e-6:
            hist.best_val, hist.best_epoch = val_loss, epoch
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            since_improve = 0
        else:
            since_improve += 1
            if since_improve >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)        # restore best-val weights
    return model, hist


# ── persistence (reload metadata — guardrail: artifact drift) ─────────────────

def save_checkpoint(model: LSTMAutoencoder, path: str, *, val_score: float | None = None,
                    threshold: float | None = None, extra: dict | None = None) -> None:
    """Save weights + enough metadata to reload and reproduce a score (DL-track guidance)."""
    torch.save({
        "model_state_dict": model.state_dict(),
        "model_class": "LSTMAutoencoder",
        "model_config": model.config,
        "ae_features": AE_FEATURES,
        "val_score": val_score,
        "threshold": threshold,
        "extra": extra or {},
    }, path)


def load_checkpoint(path: str) -> LSTMAutoencoder:
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model = LSTMAutoencoder(**ckpt["model_config"])
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model
