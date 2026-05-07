# 03 — Architecture and baseline

## The question

We need a model that can score how unusual a trajectory is, trained on data we believe is mostly normal, with no labeled anomalies. What kind of model fits, and why two of them?

## Building up to the answer

Three questions, asked in order, narrow the choice:

### Question 1: Do we have labels for anomalies?

No. Just unlabeled data we believe is normal. That immediately rules out everything supervised — logistic regression, random forest, supervised neural nets, fine-tuning a pretrained classifier. None of them work without labeled examples of both classes.

What's left is **unsupervised** or **self-supervised** methods. For sequences, the two approaches that actually work are density estimation (model `p(trajectory)`, flag low-density inputs) and reconstruction-based (train a model to reproduce normal data, flag what it can't reproduce).

We pick reconstruction-based. The score (reconstruction error) is a continuous, comparable scalar. The architecture (encoder-decoder) is well-trodden, with lots of teaching material — appropriate for a course project.

### Question 2: Does the order of points in the trajectory matter?

Yes, fundamentally. Consider two trajectories near LEMD with the same set of altitude values but in different order:

- **Trajectory A** (normal landing): 3000 → 2400 → 1800 → 1200 → 600 → 0. Smooth, monotonic descent.
- **Trajectory B** (anomalous oscillation): 1800 → 600 → 2400 → 0 → 3000 → 1200. Same values, scrambled.

Reduce each to summary statistics (mean altitude, std, min, max) and they look identical. But A is a normal landing and B is wildly anomalous.

This rules out fixed-size feature-vector models for the *primary* model — they discard the temporal structure that distinguishes A from B. We need a sequence model (LSTM, GRU, Transformer, or 1D CNN).

### Question 3: Why LSTM specifically?

For a course project on a 5-week timeline:

| Architecture | Why we considered it | Why we passed |
|---|---|---|
| Transformer | More expressive, captures long-range deps via attention | Heavier; less stable on small datasets; debugging eats Week 3 |
| GRU | Simpler than LSTM, similar performance | Acceptable swap, but LSTM is more canonical |
| 1D CNN | Fast, captures local temporal patterns | Loses long-range deps; non-standard for variable-length trajectories |
| **LSTM** | **Canonical, stable, hidden state = natural bottleneck, lots of teaching material** | **Primary choice** |

LSTM wins on pedagogical clarity, training stability, and timeline fit. Worth saying out loud: the *best* architecture for this problem in 2025-2026 is probably a Transformer encoder-decoder, but "best" doesn't help us if it doesn't converge in Week 3. We pick the architecture that matches our risk profile, not the one with the highest theoretical ceiling.

## The autoencoder pattern

The whole idea, in one sentence:

> Train a model to copy its input. Give it a bottleneck so it can't just memorize. Train it only on normal data. The reconstruction error tells you how unusual a new input is.

Four pieces:

1. **Copy its input.** The training target is the input. No labels needed — the data labels itself. This is what *self-supervised* means in our context.

2. **Bottleneck.** Without a bottleneck, the model could trivially learn `output = input` and reconstruct anything perfectly — anomalies included. The bottleneck (a 64-dimensional hidden state, in our case) forces compression. The model has to find structure in normal data to represent it efficiently.

3. **Train only on normal data.** This is what makes it an anomaly detector instead of just an autoencoder. The model gets really good at reconstructing normal trajectories. It never sees anomalies during training, so it never learns to compress them.

4. **Reconstruction error → anomaly score.** At inference, show the model a trajectory, get its reconstruction, compute MSE between the two. Low MSE → "looks normal." High MSE → "doesn't fit anything I've seen."

The architecture we sketched out in our initial scoping:

```
Encoder:  Input (T, 9)  →  LSTM(64)  →  LSTM(64)  →  hidden state (64,)
Decoder:  hidden state  →  LSTM(64)  →  LSTM(64)  →  Output (T, 9)
Loss:     MSE(Output, Input), averaged over T and the 9 features
```

About 50 lines of PyTorch.

## Threshold by construction

After training, we score the validation set of *normal* trajectories. The 95th percentile of the reconstruction-error distribution is our operating threshold. By construction, ~5% of normal trajectories get flagged (FPR ≈ 5%) — comfortably within our 15% guardrail.

The threshold is operator-tunable in the demo. The 5% default is just where we ship.

## Why also Isolation Forest?

Guardrail: never judge a fancy model in isolation. AUROC of 0.88 means nothing if the baseline gets 0.87. We need a baseline.

Isolation Forest earns the slot:
- Tree-based — no scaling, no learning rate, runs in seconds
- Operates on **per-trajectory aggregate features** (mean, std, min, max of each feature)
- Same self-supervised setting (train on normal, score everything)
- Different model family — trees vs neural nets, fixed-size vs sequence, aggregate vs per-step

Here's the interesting part: **the IF baseline deliberately throws away time order.** It only sees aggregates. If the LSTM Autoencoder doesn't beat IF by a meaningful margin on AUROC, the conclusion is *"time order doesn't help much for this problem."* That would be a publishable finding. It would also mean we should ship the IF model, because it's simpler and runs faster.

Either way, the comparison teaches us something. Building both isn't wasted work — it's the only honest way to know what the LSTM is actually contributing.

## Alternatives we considered and rejected

For the writeup's "alternatives considered" section:

| Alternative | Why we passed |
|---|---|
| Vanilla autoencoder (no LSTM) | Loses time structure, equivalent to IF — no contribution |
| Variational Autoencoder (VAE) | Probabilistic, nicer in principle; KL term + reparameterization adds complexity not earned at this scale |
| GAN-based (AnoGAN, GANomaly) | Notoriously unstable training; doesn't fit a 5-week timeline |
| One-Class SVM | Slow on >10k samples; doesn't handle sequences naturally |
| k-NN distance to nearest training trajectory | Works in principle, but storing all training trajectories at inference is impractical |
| **Forecast-and-residual** (predict next step, score residual) | A real alternative — easier to debug than autoencoder, naturally streaming. Kept warm as a fallback we'd swap to during training if our primary architecture stalls. |
| Image + tabular features (CNN encoder + clustering) | Real approach with literature; multi-modal fusion too complex for 5 weeks. Logged as future work. |

The forecast-and-residual one is worth noting publicly — it's a defensible alternative that we'd swap to if our primary architecture doesn't train cleanly. Having it in our back pocket is part of how we keep the 5-week timeline from blowing up.

## The takeaway

We didn't pick LSTM because it's the trendiest architecture. We picked it because it's the architecture that lets us *finish*. We didn't add an Isolation Forest baseline as a checkbox — it's the only honest way to know whether the time-aware model is adding value. And we wrote down our alternatives because the project is more credible when we're explicit about what we considered and rejected.

## Slide hooks

- "We have unlabeled data and zero anomaly labels. That decides the model class."
- "Time order matters. Two trajectories with the same statistics can be one normal and one anomalous."
- "We built two models. The simple one tells us whether the complex one is earning its complexity."
- "If LSTM doesn't beat Isolation Forest, we ship Isolation Forest. That's not a fallback — it's the finding."
