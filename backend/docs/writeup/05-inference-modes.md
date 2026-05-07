# 05 — Inference modes: eval vs demo

## The question

When does the model actually score a trajectory — after the flight completes, or as it unfolds? It sounds like a detail, but it's a real ML systems decision with implications for how we evaluate, how we demo, and what we can honestly claim about the system.

## Two modes, two purposes

We use the same model in two different ways, for two different purposes:

| Mode | When the model scores | What it sees | What it's used for |
|---|---|---|---|
| **Batch** | Once, after the trajectory is complete | The full sequence | Final evaluation. Headline AUROC, F2, FPR, PR-AUC numbers come from this. |
| **Streaming** | At every new timestep as data arrives | The trajectory so far (`points 1..t`) | Demo. Animation shows the score evolving as the audience watches the flight unfold. |

The split exists because evaluation and demonstration serve different masters. Evaluation needs the cleanest match between what we trained on and what we're scoring — the model was trained to reconstruct full trajectories, so the fairest test is on full trajectories. Demonstration needs visual storytelling — a static "anomaly score: 0.87" bar at the end of a flight is far less compelling than a bar that climbs over time as the trajectory does something weird.

## The honest caveat: train/inference parity

There's a real systems issue here, and we want to be upfront about it in the writeup.

The model is trained on **full trajectories**. In the demo, we're feeding it **partial trajectories** as they grow. From the model's perspective, those are different things — a 30-step partial trajectory is not the same kind of input as a 50-step full trajectory, even if the first 30 steps are identical. Strictly speaking, this is a *train/inference parity* mismatch. Models trained one way and used another can behave unexpectedly.

In our case the mismatch is mild. The LSTM Autoencoder is small (hidden=64, 2 layers), trajectories are short (10-100 timesteps after resampling), and reconstruction error scales somewhat predictably with sequence length. Re-running the model on growing prefixes gives a score that increases as more of the trajectory is seen — which is exactly the visual we want for the demo.

But it's worth saying: **the headline numbers we report (AUROC = X, F2 = Y, FPR = Z) come from batch evaluation on full trajectories.** The streaming demo is a presentation of the model in motion, not an additional evaluation. We're explicit about that in the writeup so a reader can't accuse us of conflating the two.

## How we'd fix it (Week 4 stretch)

There's a clean fix, and we're planning to attempt it if Week 3 finishes ahead of schedule:

**Train the autoencoder on random subsequences instead of always-full trajectories.** Each training batch contains trajectory prefixes of varying lengths. The model becomes parity-correct across both modes — batch eval and streaming inference look the same to it, because that's what it saw in training.

Cost: roughly one day of retraining work. We change the training data sampler, retrain, re-evaluate. If it works, the parity caveat in the writeup goes from "we acknowledge this and document it" to "we addressed it and here's the result." Either outcome is honest; the second is just a polished story.

## Synthetic anomalies for the demo

The demo doesn't run on live ADS-B — too unpredictable, too much risk of an embarrassing API failure mid-presentation. Instead, we precompute a set of trajectories with synthetic anomalies injected, and the demo plays them back point-by-point with the score updating in real time.

We use the same four anomaly injection types specified for evaluation:
- **Zone violation** — reroute path through a restricted polygon. Visual: trajectory crosses a red zone.
- **Altitude violation** — shift the altitude band by ±300m. Visual: altitude profile breaks the expected envelope.
- **Hovering** — replace a 30-second segment with a stationary point. Visual: trajectory pauses mid-flight.
- **Speed spike** — multiply velocity by 3× for a 20-second window. Visual: trajectory jumps unusually far between timesteps.

The audience picks one (or random), and we animate it. They watch the score climb. When it crosses the operator-tunable threshold, an alert visual fires.

Two reasons we like this for the demo:
1. We control the anomaly types — same as what we evaluated on, so our metrics correspond to what the audience is seeing.
2. We can pick visually clear examples. A hovering anomaly is dramatic on a map; a subtle speed spike is harder to convey but more representative of real anomalies. We mix.

## A second-order question: what about real-time deployment?

For a course project, the answer is "out of scope." We're not building a deployable counter-drone system. But it's worth saying what *would* be needed for actual deployment, so the writeup has a credible "future work" section:

- **Sliding-window inference**: at each timestep, score the last N points as a chunk. Bounded compute. Train on random N-step chunks for parity.
- **Forecast-and-residual model**: a different architecture entirely — train an LSTM to predict the next point given the previous N. Score the residual. Naturally streaming, easier to debug. We've kept this warm as a fallback we'd swap to during training if the autoencoder doesn't train cleanly.
- **Inference latency budget**: the model runs in well under 1 second on a laptop, so latency is not a constraint at this scale.

These are real options for production, not just hand-waving. We mention them in the writeup to be transparent about what the gap is between course deliverable and deployable system.

## The takeaway

A demo that animates the model in real time tells a better story than a static report. But it introduces a small parity issue that we have to be honest about. Our solution is to use batch inference for the evaluation numbers (matching how the model was trained) and streaming for the demo (matching how the audience experiences it), with the parity caveat explicitly documented. If Week 3 has slack, we close the parity gap by training on random subsequences. Either way, the ML team isn't pretending the two modes are equivalent.

## Slide hooks

- "The numbers come from batch eval. The demo runs streaming. Here's why both, and what's different."
- "Trained on full trajectories. Demoed on partial ones. We acknowledge the gap."
- "The audience picks a trajectory. We animate it. The score climbs. The alert fires."
- "This is a course demo. What would change for deployment? Sliding windows, parity-fixed training, and a real operator interface."
