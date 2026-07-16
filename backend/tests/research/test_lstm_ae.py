"""Tests for the LSTM Autoencoder (`backend/research/src/sadar_research/trajectory_anomaly/models/lstm_ae.py`).

  ★★★ CRITICAL  masked recon loss excludes padding AND imputed rows (zero gradient there).
  ★★            forward/recon shape = (N,T,9); reconstruction_error length = N.
  ★★            equal-weighted across features (no per-feature down-weight).
  ★★            deterministic with a fixed seed; training restores best-val weights.
"""

from __future__ import annotations

import numpy as np
import torch

from sadar_research.trajectory_anomaly.models import lstm_ae as ae
from sadar_research.trajectory_anomaly.pipeline.preprocessing import AE_FEATURES

F = len(AE_FEATURES)


# ── ★★★ CRITICAL — masked loss = zero gradient at padded/imputed timesteps ───

def test_critical_masked_loss_zero_gradient_at_masked_timesteps():
    torch.manual_seed(0)
    x = torch.randn(2, 6, F)
    recon = torch.randn(2, 6, F, requires_grad=True)
    mask = torch.ones(2, 6)
    mask[0, 4:] = 0.0          # timesteps 4,5 of sample 0 are padding/imputed
    mask[1, 5:] = 0.0
    loss = ae.masked_mse(recon, x, mask)
    loss.backward()
    assert torch.all(recon.grad[0, 4:] == 0), "masked timesteps must get zero gradient"
    assert torch.all(recon.grad[1, 5:] == 0)
    assert torch.any(recon.grad[0, :4] != 0), "valid timesteps must get gradient"


def test_critical_masked_loss_invariant_to_masked_values():
    torch.manual_seed(1)
    x = torch.randn(3, 8, F)
    recon = torch.randn(3, 8, F)
    mask = torch.ones(3, 8)
    mask[:, 5:] = 0.0
    base = ae.masked_mse(recon, x, mask).item()
    recon2 = recon.clone()
    recon2[:, 5:] = 999.0     # garbage in the masked region
    assert abs(ae.masked_mse(recon2, x, mask).item() - base) < 1e-6


def test_loss_is_equal_weighted_across_features():
    # error concentrated in one feature should equal the same total error in another.
    x = torch.zeros(1, 4, F)
    mask = torch.ones(1, 4)
    r1 = torch.zeros(1, 4, F); r1[0, :, 0] = 2.0     # all error in feature 0
    r2 = torch.zeros(1, 4, F); r2[0, :, 5] = 2.0     # same error in feature 5
    assert abs(ae.masked_mse(r1, x, mask).item() - ae.masked_mse(r2, x, mask).item()) < 1e-9


# ── shapes ────────────────────────────────────────────────────────────────────

def test_critical_encoder_latent_ignores_padding_with_mask():
    # codex finding #2: with a mask, the bottleneck must come from the last VALID timestep,
    # so changing the padded input rows must not change the reconstruction.
    ae.set_seed(0)
    model = ae.LSTMAutoencoder(hidden=16, latent=8)
    x = torch.randn(2, 12, F)
    mask = torch.ones(2, 12); mask[:, 7:] = 0.0          # rows 7..11 are padding
    with torch.no_grad():
        out1 = model(x, mask)
        x2 = x.clone(); x2[:, 7:] = 99.0                 # garbage in the padded rows
        out2 = model(x2, mask)
    assert torch.allclose(out1, out2, atol=1e-6), "encoder latent must ignore padded input rows"


def test_forward_shape():
    ae.set_seed(0)
    model = ae.LSTMAutoencoder(hidden=16, latent=8)
    x = torch.randn(5, 12, F)
    assert model(x).shape == (5, 12, F)


def test_reconstruction_error_length_and_polarity():
    ae.set_seed(0)
    X = np.random.default_rng(0).normal(size=(200, 20, F)).astype("float32")
    mask = np.ones((200, 20), dtype="float32")
    model, _ = ae.train_autoencoder(X, mask, max_epochs=3, hidden=16, latent=8, seed=0)
    re = ae.reconstruction_error(model, X, mask)
    assert re.shape == (200,)
    # an off-manifold window should score higher than the trained-on normals
    outlier = np.full((1, 20, F), 9.0, dtype="float32")
    omask = np.ones((1, 20), dtype="float32")
    assert ae.reconstruction_error(model, outlier, omask)[0] > np.median(re)


# ── determinism + training behaviour ──────────────────────────────────────────

def test_training_is_deterministic_in_seed():
    X = np.random.default_rng(1).normal(size=(120, 15, F)).astype("float32")
    mask = np.ones((120, 15), dtype="float32")
    m1, h1 = ae.train_autoencoder(X, mask, max_epochs=4, seed=123, hidden=16, latent=8)
    m2, h2 = ae.train_autoencoder(X, mask, max_epochs=4, seed=123, hidden=16, latent=8)
    assert np.allclose(h1.train_loss, h2.train_loss)
    assert np.allclose(ae.reconstruction_error(m1, X, mask),
                       ae.reconstruction_error(m2, X, mask))


def test_training_logs_curves_and_keeps_best_val():
    X = np.random.default_rng(2).normal(size=(160, 18, F)).astype("float32")
    Xv = np.random.default_rng(3).normal(size=(40, 18, F)).astype("float32")
    mask = np.ones((160, 18), dtype="float32")
    vmask = np.ones((40, 18), dtype="float32")
    model, hist = ae.train_autoencoder(X, mask, Xv, vmask, max_epochs=10, patience=3, seed=0,
                                       hidden=16, latent=8)
    assert len(hist.train_loss) == len(hist.val_loss) >= 1   # curves logged
    assert hist.best_epoch >= 0
    assert hist.best_val == min(hist.val_loss)               # best-val tracked


def test_save_and_load_roundtrip(tmp_path):
    ae.set_seed(0)
    X = np.random.default_rng(4).normal(size=(60, 14, F)).astype("float32")
    mask = np.ones((60, 14), dtype="float32")
    model, _ = ae.train_autoencoder(X, mask, max_epochs=2, seed=0, hidden=16, latent=8)
    before = ae.reconstruction_error(model, X, mask)
    p = tmp_path / "ae.pt"
    ae.save_checkpoint(model, str(p), val_score=0.5, threshold=1.2)
    reloaded = ae.load_checkpoint(str(p))
    after = ae.reconstruction_error(reloaded, X, mask)
    assert np.allclose(before, after, atol=1e-6)   # no artifact drift
