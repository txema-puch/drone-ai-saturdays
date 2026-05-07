# 01 — Anomaly detection, not classification

## The question

The course brief gave us *Scenario 8*: classify drone trajectories as `cooperative`, `negligent`, or `hostile`. Three classes. Looks like a clean ML problem.

It isn't. Or rather — it's the wrong framing for the data we can actually get. This is the most fundamental decision in the whole project, and getting it right early saved us weeks of pointless modeling.

## Why three-class classification doesn't work

**You can't get the data.** Three-class classification needs labeled examples of each class. Cooperative drones (the boring ones, broadcasting authorized flight plans) are everywhere. Negligent and hostile drones are not. There is no public dataset of "hostile drone trajectories" because:
- Real hostile incidents are rare, sensitive, and not reusable
- Labeling synthetic ones requires deciding what makes a trajectory "hostile" — and that decision is itself the project

**Intent isn't in the data.** The same flight pattern — a drone hovering 200m above a runway — could be a wedding photographer who got lost, a journalist trying to get a shot of a delayed flight, or someone deliberately disrupting operations. The trajectory is identical. The intent is not in the radar return, the ADS-B broadcast, or any sensor we have access to. A model trained to predict intent from sensor data is being asked to do something the data fundamentally doesn't support.

**Even if we could get labels, the boundaries are subjective.** What separates "negligent" from "hostile"? It's a regulatory and legal judgment, not a data-driven distinction. Teaching a model to make that judgment puts the model in a position no model should be in.

## Why anomaly detection works

We flipped the question. Instead of asking *"is this drone hostile?"*, we ask *"is this trajectory statistically unusual relative to authorized flight patterns near LEMD?"*

That second question is answerable. Because:
- We have abundant labeled normal data — every authorized flight broadcasting on ADS-B around Madrid-Barajas, free via OpenSky Network
- Statistical unusualness is a property of the data, not of intent
- The output is a continuous score, not a categorical label — operators can choose where to draw the line

The threshold becomes the operator's tool, not the model's commitment. A real airport security operator might set the threshold low (more alerts, more recall) during a high-threat period; lower at quiet hours. We give them the dial; they decide where it points.

## What we lose by reframing

Two things, both worth being honest about.

**We don't tell hostile from negligent.** Both look anomalous. The model flags either. A regulatory or operator judgment decides what to do next — call the police, send a drone-jamming team, send a friendly text. That's not the model's job. We say so explicitly.

**We need synthetic anomalies for evaluation.** Since real anomalies are rare and unlabeled, we can't measure how well the model catches them by waiting for reality to provide examples. We inject synthetic anomalies into the test set: zone violations, altitude violations, hovering, speed spikes. The choice of injection types is itself a research decision (we picked four classes that cover both spatial and temporal anomalies). And we cross-check by measuring whether a stupid rule-based geofence beats our model on the same injections — if it does, the injections are too easy and our ML approach isn't earning its complexity.

## The takeaway

The course brief implied a classifier. We built an anomaly detector. The real-world cost of that swap is small (we don't tell intent), and the data cost is enormous (we don't need labeled hostile examples that don't exist anyway).

This single decision shapes everything downstream — the loss function (reconstruction, not cross-entropy), the metric (AUROC, not classification accuracy), the evaluation (synthetic injection, not labeled test set), and the demo (a tunable threshold, not a hard yes/no).

If we'd kept the classification framing, we'd have spent Week 1 trying to source a hostile drone dataset, Week 2 admitting it doesn't exist, Week 3 generating synthetic hostile labels, Week 4 realizing those labels just encoded our own assumptions, and Week 5 presenting a model that learned to detect our assumptions. The reframing happens early because it has to.

## Slide hooks

- "The brief asked for three classes. We're delivering a continuous score, and here's why."
- "There is no labeled dataset of hostile drone behavior. There never will be one."
- "We don't predict intent. We measure statistical unusualness."
- "The threshold is the operator's job. The score is ours."
