# D-006: Architecture — LSTM Autoencoder primary, Isolation Forest baseline

**Phase:** problem (tentative; confirmed in Phase 6)
**Date:** 2026-05-07
**Status:** decided (tentative — locked in Phase 6)

## Context

Phase 1 picks a tentative `model_track` and architecture, recorded in `manifest.yml`. The track is *confirmed* in Phase 6 once we see whether the chosen architecture meaningfully beats the baseline. This decision documents the reasoning chain that gets us to "LSTM Autoencoder + Isolation Forest baseline" and the alternatives we considered and rejected.

## The reasoning chain

### Step 1 — No labels for anomaly → unsupervised / self-supervised

We have abundant unlabeled data we believe is mostly normal flight near LEMD. We have zero labeled examples of anomalies. This rules out supervised classification and supervised regression entirely. We are looking at:

- **Density estimation** — model `p(trajectory)`; flag low-density inputs
- **Reconstruction-based** — train a model to reproduce normal data; flag inputs it can't reproduce

Reconstruction wins because the score (reconstruction error) is a **continuous, comparable scalar** and the architecture (encoder-decoder) is well-trodden pedagogically — appropriate for a course project.

### Step 2 — Trajectory has temporal structure → sequence model

Two trajectories with the same set of points but in different orders can be one normal and one anomalous. Example: a smooth descent (normal) vs an altitude oscillation that revisits the same heights in scrambled order (anomalous). Their per-point distributions are identical; the difference is sequential.

This rules out **fixed-size feature-vector models** (logistic regression, random forest, vanilla autoencoder, Isolation Forest) for the *primary* model — they can only operate on aggregated features and lose the temporal pattern.

What remains: **sequence models** (LSTM, GRU, Transformer, 1D CNN).

### Step 3 — LSTM specifically

For our scope:

| Architecture | Pros | Cons | Verdict |
|---|---|---|---|
| **LSTM** | Canonical, stable, hidden state = natural bottleneck, lots of teaching material | More parameters than GRU | **Primary choice** |
| GRU | Simpler than LSTM, similar performance | Slightly less expressive | Acceptable swap if LSTM is slow |
| Transformer encoder-decoder | More expressive via attention, captures long-range deps | Heavier, less stable on small data, can eat Week 3 in debugging | Out — Phase 7 ablation if time |
| 1D CNN autoencoder | Fast, captures local temporal patterns | Loses long-range dependencies; less standard for variable-length sequences | Out — second-tier alternative |

LSTM wins on **pedagogical clarity** + **training stability** + **timeline fit**.

### Step 4 — Autoencoder pattern

The autoencoder structure is what makes the unlabeled data useful:

```
Input (T, D) → Encoder LSTM → bottleneck (64-dim hidden) → Decoder LSTM → Output (T, D)
Loss = MSE(Output, Input)
```

The bottleneck (hidden=64) forces compression. Trained only on normal data, the model becomes good at compressing-and-reconstructing normal patterns. Anomalies don't fit those patterns → high reconstruction error → high anomaly score.

### Architecture (from design doc)

```
Encoder:  (T, 9)   →   LSTM(64)  →  LSTM(64)  →  hidden state (64,)
Decoder:  (64,)    →   LSTM(64)  →  LSTM(64)  →  output (T, 9)
Loss:     MSE(output, input), averaged over T and feature dim
```

`T` ≈ 10–100 timesteps (after segmentation + 10s resampling). `D = 9` features per timestep: `[lat, lon, alt, speed, heading, dist_to_lemd, in_restricted_zone, time_of_day_sin, time_of_day_cos]`.

### Threshold by construction

After training, score the validation set of *normal* trajectories. The 95th percentile of the reconstruction-error distribution is the operating threshold. By construction, ~5% of normal trajectories are flagged at this threshold (FPR ≈ 5%), comfortably within the FPR ≤ 15% guardrail.

## Baseline: Isolation Forest

Per Guardrail #10, no fancy model is judged in isolation. IF earns the baseline slot:

- **Tree-based** — no scaling, no learning rate, runs in seconds on commodity hardware
- **Operates on per-trajectory aggregate features** — `mean / std / min / max` for each of the 9 features. Deliberately **no time order** — that's exactly the contrast we want.
- **Same self-supervised setting** — train on normal, score everything; the trees learn isolation paths for normal data and anomalies have shorter paths.
- **Different model family** — trees vs neural nets, fixed-size vs sequence, aggregate vs per-step. Honest contrast.

The interesting comparison: **the IF baseline deliberately throws away time order.** If the LSTM Autoencoder doesn't beat IF by a meaningful margin, that says *"time order doesn't help much for this problem"* — a publishable finding that would also mean we should flip `model_track: dl → ml` and ship IF.

## Alternatives considered and rejected

| Alternative | Why rejected for the primary slot |
|---|---|
| **Vanilla autoencoder (no LSTM)** | Loses time structure → equivalent to IF baseline; offers nothing new. |
| **Transformer encoder-decoder** | More expressive but harder to train stably on small data; debugging risk consumes Week 3. Worth a Phase 7 ablation only if Week 4 has slack. |
| **GRU autoencoder** | Almost equivalent to LSTM; mostly a tooling preference. Acceptable swap if LSTM training is slow on Colab T4. |
| **Variational Autoencoder (VAE)** | Probabilistic outputs (likelihood scores) are nicer in principle, but the KL term + reparameterization adds complexity not earned at this scale. |
| **GAN-based anomaly detection (AnoGAN, GANomaly)** | Notoriously unstable training; does not fit a 5-week timeline. Empirically often worse than autoencoders on tabular/sequence data anyway. |
| **One-Class SVM** | Slow on >10k samples; doesn't naturally handle variable-length sequences. |
| **k-NN distance to nearest training trajectory** | Works in principle, but storing all training trajectories at inference is impractical; doesn't scale. |
| **Forecast-and-residual** (predict next step, score residual) | A real alternative — easier to debug than autoencoder, naturally streaming. **Kept warm as Phase 6 fallback** if LSTM AE training stalls. Same LSTM architecture, different objective, same threshold-by-construction approach. |
| **Image + tabular features (CNN encoder + clustering or multi-modal)** | Real approach with literature; multi-modal fusion is too complex for 5 weeks. **Logged as Phase 6 stretch / future work in writeup.** |
| **Normalizing flows (Real NVP, Masked Autoregressive Flow)** | Probabilistic density estimation. Complex training, niche tooling. Out of scope for course timeline. |

## Decision

**Primary: LSTM Autoencoder, hidden=64, 2 encoder layers + 2 decoder layers, MSE loss, train on normal-only with held-out val for threshold selection.**

**Baseline: Isolation Forest on per-trajectory aggregate features (mean/std/min/max of each of the 9 features).**

**Tentative; confirmed in Phase 6** by flipping `manifest.yml > gates.train.track_confirmed = true` once we see the val AUROC contrast between LSTM AE and IF.

## Consequences

- Phase 6 trains both models (IF first as baseline, LSTM AE primary).
- Phase 6 records val scores for both with bootstrap CI.
- Phase 7 evaluates both on the same held-out test set + injected anomalies; reports AUROC, F2, FPR, PR-AUC for each.
- The architecture is small enough to train on Colab T4 free tier in ≤ 15 min on a 6-month dataset; CPU training acceptable up to that scale.
- Inference is fast enough (< 1s / segment on a laptop) for the demo.
- Per-feature and per-timestep reconstruction error decomposition (in-scope interpretability) falls out of this architecture naturally.

## Revisit triggers

- **LSTM AE training fails to converge by Saturday Week 3** → swap to forecast-and-residual; keep IF baseline as fallback demo.
- **LSTM AE val AUROC does not meaningfully exceed IF val AUROC** (e.g., gap < 0.03) → flip `model_track: dl → ml`, ship IF, document the finding ("time order didn't help") as a primary writeup result.
- **Memory / compute constraint** (e.g., longer sequences than expected) → swap LSTM → GRU or reduce hidden size.
- **Phase 7 reveals that the AE reconstructs anomalies just as well as normals** (i.e., the bottleneck isn't tight enough) → reduce hidden size or add a regularizer; this is a Phase 6 loop, not a Phase 1 revisit.

## Scope reframe (post-Phase 1) — interpretation note

The architecture choice in this ADR (LSTM AE primary, IF baseline) remains operational, but **the claim scope was narrowed mid-project**. The original framing of "counter-drone detector via two-layer architecture" was retired once it became clear that:

1. Consumer drones do not broadcast ADS-B — the training corpus is cooperating manned aircraft only.
2. Aviation's regulatory ecosystem (registry + flight plans + ATC + Eurocontrol safety nets STCA/APW/MSAW/APM) makes "Layer 1" dramatically cleaner than the cyber/fraud playbook assumes.

The operational restatement is **a behavioral anomaly detector for cooperating aircraft**, designed to complement (not replace) the deployed safety-net stack at every European ATC center.

What this means for evaluating this ADR's choice in Phase 6+:

- The pre-committed AE-vs-IF decision rule (margin ≥ 0.03 on val AUROC) is **unchanged**. It remains the model-selection criterion.
- Phase 7 eval will be **stratified by anomaly type**. Pre-commit: AE expected to lose to safety-net analogs on zone violation (APW) and altitude violation (MSAW); AE expected to win on hovering, speed spike, and late-trajectory deviation. The architectural claim is *not* "AE beats safety nets across the board"; it is "AE earns its complexity specifically on sequence-shaped anomalies the deployed rules don't cover."
- The IF baseline's role is unchanged — it answers "does time order add value?" *within* the AE's domain (sequence-shaped behavioral anomalies on cooperating aircraft), not "does ML beat safety nets?"

See `backend/docs/writeup/09-the-architectural-critique.md` for the full reframe rationale. `01-problem.md > Scope evolution (post-Phase 1)` carries the parallel narrative note.

## References

- Design doc: `backend/docs/architecture/design-trajectory-anomaly-detection.md` (Model section)
- Guardrail #10 (baseline required) and Guardrail #11 (pretrained > custom; n/a here, no pretrained for this domain) — `/ml-lifecycle/references/guardrails.md`
- Phase 6 reference: `/ml-lifecycle/references/phase-6-train.md` (DL track)
- Medium-piece thesis (post-Phase 1 reframe): `backend/docs/writeup/09-the-architectural-critique.md`
