# 10 — The unglamorous middle: preprocessing and features

> **What this covers:** Phases 3 (preprocessing) and 5 (feature engineering) of the ML lifecycle.
> The part of the project that doesn't make the Medium piece but is where most of the actual
> decisions live. If chapter 09 is the thesis, this is the load-bearing wall behind it.
> Cross-refs: `backend/docs/ml/03-preprocess.md`, `05-features.md`, decisions D-009/D-010.

There's a stretch of every ML project that no one writes about: after the data is validated and
before the model does anything interesting. It's all plumbing — segmenting, resampling, masking,
deciding what counts as one example. It's also where you quietly win or lose, because every
leakage bug and every framing mistake gets baked in here and is invisible by the time you're
staring at a confusion matrix. Three decisions from this stretch were load-bearing.

## The firewall: nothing gets fitted until we've split

The single most important rule in the preprocessing code is what it *doesn't* do: it never calls
`.fit()`. Not on the scaler, not on anything. The preprocessing pipeline is a pure, unfitted
transformation — sort, segment, filter, resample, impute, encode — and it is identical for every
trajectory regardless of which split it lands in.

Why be this strict? Because the most common silent leak in anomaly detection is fitting a scaler
(or imputing a mean, or choosing a sequence length) on *all* the data before splitting. Do that
and your "normal" statistics already know something about the test set. The model looks better
than it is, and you don't find out until production — or, for us, until a reviewer asks "wait,
when did you fit that scaler?"

So we drew a hard line, which we called the fit/transform firewall: **the StandardScaler fit, the
sequence length `T`, and the train/val/test split all happen in Phase 6, on the training fold
only.** Phase 3 produces an unfitted recipe; Phase 6 is the only place a number derived from data
touches the pipeline. The preprocessing module's `make_scaler()` deliberately returns an *unfitted*
scaler, and there's a test that fails if anyone ships a fitted one. It's a small discipline that
makes the whole evaluation trustworthy.

## What is one example? The segment, not the flight

The next decision sounds pedantic and isn't: what is a single training example? The obvious answer
is "a flight." We rejected it.

ADS-B coverage near an airport is patchy — an aircraft drops below radio horizon, passes through a
coverage gap, and reappears minutes later. Treat the whole flight as one example and you get a
sequence with a multi-minute hole in the middle that the model has to reconstruct, which it can't,
which inflates its error for reasons that have nothing to do with anomaly. So we split every flight
at any gap longer than three minutes and made the **segment** the unit of modeling. A segment is a
continuous stretch of observation with no large hole. The model reconstructs segments; anomalies
are scored per segment.

This also forced an honest small rule that bit us later in a good way: interpolation is allowed to
fill *within* a segment (short gaps, resampled to a strict 10-second grid) but is forbidden from
ever crossing a segment boundary. There's a test guarding exactly that, because an interpolation
that bridges two segments would manufacture a smooth trajectory through a real coverage hole — a
fabricated normal where there was no data. Two of the three most critical tests in the whole
codebase are about this boundary.

## Anomalies aren't one thing: the multi-detector split

The reframe in chapter 09 — that the AE has a *narrow* job — actually started here, in a
preprocessing decision (D-010). We stopped treating "anomaly" as one phenomenon for one model to
catch and split it into three channels:

1. **Physically impossible values** (altitude below ground, speeds no aircraft flies) — caught by
   a deterministic bounds rule, not the model. These are sensor errors, not behavior. We count
   them, flag them, and route them out; asking a reconstruction model to "detect" a GPS glitch is
   a category error.
2. **Missing data** — handled by imputation with explicit `*_missing` mask channels, so the model
   knows which values were observed and which were filled.
3. **Behavioral anomalies** — the only channel the LSTM AE owns.

This three-way split is why chapter 09 can say the AE has a specific remit. We designed the remit
into the pipeline before we trained anything. The 513 "physically impossible" segments that show up
in the data are not the AE's problem by construction — they're the bounds rule's.

## The feature that didn't earn its place (and stayed anyway)

Phase 5 was feature engineering, and its headline feature is a cautionary tale. We computed
`dist_to_runway_m` — distance from each point to the nearest of LEMD's eight runways — as a
nonlinear "how close to the airport" signal, and **promoted it into the autoencoder's input
vector** (taking it from 8 features to 9). The reasoning was sound: proximity-to-runway is exactly
the geometry a zone violation distorts.

Then Phase 6 ran the ablation, and the honest result was: **adding `dist_to_runway_m` to the AE
changed its score by +0.003 — noise.** The feature we'd reasoned ourselves into promoting did
nothing measurable for the reconstruction model.

We kept it anyway, and the reason is the interesting part. `dist_to_runway_m` is load-bearing for
*other* components — it's the shared geometry the rule-based geofence/APW baseline binds to, and the
coordinate the synthetic zone-violation injection perturbs. Ripping it out of one consumer because
a different consumer doesn't benefit would fragment the definition. So it stays, documented as
"neutral for the AE, required by the baseline." The lesson we wrote down: *a feature can be right
to compute and wrong to feed the model, and an ablation is how you tell the difference.* If we'd
trusted the reasoning instead of testing it, we'd have shipped a slightly-more-complex model for no
gain and never known.

## The held-aside cohort: building the Phase-7 test set, in Phase 5

The decision from this stretch that paid off biggest was the quietest. While engineering features,
we wrote a geometric detector for **go-arounds** — the descend-then-climb signature of an aborted
landing — using a single-airborne-run rule (an engineering review caught and fixed a touch-and-go
misclassification in the first version). It found 191 go-around segments, about 1% of the data.

We didn't use them. We *held them aside* — routed them out of the training set entirely, alongside
the handful of real 7700-squawk emergencies — and left them sealed.

The reason only became clear two phases later. Those 191 real go-arounds and 4 real emergencies are
the closest thing we have to *labeled real behavioral anomalies* on our own data. By keeping them
out of training, we reserved them as a real-anomaly test cohort the model had provably never seen —
which is exactly what chapter 09's "the ranking inverted" result is scored on. The single most
important evaluation in the project was made possible by a held-aside decision made in Phase 5,
before we'd trained a single model, for a reason ("these aren't normal, don't train on them") that
turned into a far better one ("these are our real-anomaly ground truth").

That's the recurring shape of the unglamorous middle: the decisions look like plumbing, and two
phases later you find out they were the experiment.
