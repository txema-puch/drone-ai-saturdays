# 11 — The bake-off, the loop-back, and the one-shot burn

> **What this covers:** Phases 6 (training) and 7 (evaluation). The receipts behind chapter 09's
> thesis — the full model comparison, the surprise that a simple model won the synthetic bench, the
> loop-back that didn't rescue it, and the single irreversible test-set evaluation that decided
> everything. Cross-refs: `backend/docs/ml/07-train.md`, `07-eval.md`, decisions D-005/D-006/D-012.

Chapter 09 tells the story; this one shows the work. It's an engineering log, in order.

## The split, and the firewall made real

Everything Phase 3 refused to fit gets fitted here — once, on the training fold only. The split has
to satisfy two non-negotiables at the same time:

- **No group leakage.** The same aircraft (`icao24`) or flight must not appear in two folds, or the
  model can "recognize" a test trajectory by having memorized that airframe's habits in training.
- **No temporal leakage.** Test must be strictly later in time than train, so we're measuring
  "predict the future," not "interpolate the past."

We used the Mondays from 2017–2018 for training, 2019 for validation, and **sealed all of 2020 as
the test set** — which doubles as a free distribution-shift stress test (the start of COVID). A
teammate's parallel project (SADAR) independently chose the same dual-criterion split, which was
reassuring: two teams reasoning separately to the same discipline.

One subtlety we measured rather than assumed. A few hundred airframes recur across folds (you can't
avoid it — the same airlines fly LEMD every Monday). That's only a leak if the *identifier* is a
feature, and ours isn't — `icao24` and `flight_id` are explicitly excluded from the model's inputs.
We checked the effect directly: validation AUROC on aircraft seen in training vs unseen differed by
**−0.066** — recurring airframes were if anything *harder*, not easier. The "recurrence optimism" a
reviewer worried about simply wasn't there, and we have the number instead of a hand-wave.

From here the test set is untouchable until Phase 7. `burned: false` in the manifest, and it stays
that way through every decision below.

## The bake-off: deep model clears the bar, then a simpler one clears it higher

The pre-committed rule (D-006) was simple: the LSTM AE ships only if it beats the Isolation Forest
baseline by at least 0.03 AUROC on validation. It did — 0.664 vs 0.625, a clean +0.039 with
non-overlapping confidence intervals. By the rule we'd written in Phase 1, we ship the AE.

Then we did the thing the rule didn't require and widened the baseline panel — same firewall, same
validation set — to see whether the *deep* model was actually pulling its weight or just beating a
weak opponent:

| detector (validation AUROC) | overall |
|---|---|
| Isolation Forest | 0.625 |
| LSTM autoencoder (small/mean) | 0.664 |
| **kNN on summary stats (k=5)** | **0.707** |
| GMM on summary stats | 0.664 |

A k-nearest-neighbors distance over four summary statistics per channel (mean, std, min, max) beat
the trained sequence model by a wider margin than the AE had beaten the Isolation Forest. The deep
model was not earning its complexity on synthetic anomalies. We marked the model choice
**provisional** in the manifest (`track_confirmed: false`) rather than declaring victory — the
D-006 rule had been satisfied against too weak a field.

## The loop-back: is 0.66 a tuning problem or an architecture problem?

A validation AUROC of 0.664 is well under the 0.85 we'd set as the Phase-1 target, so before
proceeding we looped back and ran the obvious ceiling-raising levers — all blind on validation, test
still sealed: a longer training schedule, swapping raw lat/lon for runway-relative ENU coordinates,
per-flight-phase models, and a per-anomaly-type characterization. None beat the baseline
meaningfully.

The reason they couldn't was the per-type read, and it's the same finding chapter 09 leads with:
the AE is near-chance on *spatial* anomalies (zone, altitude — geometries the deployed APW/MSAW
rules already own) and strong on *dynamic* ones (loiter, intercept). The 0.66 isn't under-tuning;
it's an honest average of an in-remit capability and an out-of-remit one. More validation tuning
would only overfit validation. So we stopped, and wrote down that the ceiling is architectural, not
a knob we failed to turn.

**The codex review that mattered.** An independent AI code review (OpenAI's codex, run adversarially
against the diff) caught two real bugs before we trusted any of these numbers. One: an injected
anomaly's onset could land past the end of the kept window, so a sample was labeled "anomaly" while
containing no perturbation. Two, and worse: the LSTM encoder was ingesting padding — for the ~95% of
segments shorter than the max length, the encoder's final hidden state came from zero-padding, not
from the trajectory. Fixing it removed an artifact that had been inflating the bigger configs and
*flattened the entire config grid to ~0.65* — which is how we learned that model capacity was
immaterial here and the simplest config should ship. The honest headline (0.664) is lower than the
buggy one (0.684); we kept the honest one.

## Phase 7, the entry decision: re-weighting the bench (carefully)

Before the one-shot burn there was one judgment call. Our synthetic bench weighted
`zone_violation` at 40% of the mix — and zone is precisely the anomaly the AE is *not* responsible
for (APW owns it). At 40%, a category outside the model's remit was the single biggest drag on its
headline number. We re-weighted it out (decision D-012).

The risk of changing a benchmark after seeing results is obvious — it's how people fish for better
numbers. So we fenced it: the rationale was architectural and pre-dated the result (the "zone is
APW's job" reframe was written before any Phase-7 number existed); we kept `zone_violation` as a
reported out-of-remit *diagnostic* rather than deleting it; we preserved the original mix verbatim
in the code so the Phase-6 results stay reproducible; and a codex review caught that the Phase-6
notebooks needed pinning to the old mix or they'd silently pick up the new one. It's a deliberate,
documented, signed-off deviation, not a quiet goalpost move — and it changes none of the real-anomaly
results, which use no synthetic mix at all.

## The burn

The test set is scored exactly once. We ran all three models — AE, kNN, Isolation Forest — on the
sealed 2020 fold, reported every number, dropped none (a pre-registered guardrail against quietly
keeping only the flattering model). The synthetic headline:

| model | synthetic test AUROC | real-anomaly ROC |
|---|---|---|
| LSTM-AE | 0.731 | **0.667** |
| kNN | **0.786** | 0.595 |
| Isolation Forest | 0.717 | 0.495 |

The re-weight lifted the AE's synthetic number from ~0.66 to 0.731, but the target (0.85) still
went unmet and the kNN still won the synthetic bench. At the AE's validation-chosen operating point
(threshold 0.222, never re-tuned on test), false-positive rate came in at 0.089 — under the 15%
guardrail — with F2 0.520. Per-type, the test fold confirmed validation exactly: loiter 0.971,
intercept 0.789 (the AE's remit), zone 0.551 (out of it).

And then the column that decided the project: **real anomalies.** Scored on the held-aside cohort of
191 real go-arounds and 4 emergencies (set aside back in Phase 5) versus 2020-normal, the deep model
beat the kNN it had lost to on synthetic — 0.667 vs 0.595 — and the Isolation Forest fell to chance.
The kNN's edge was an artifact of summary-statistic-shaped synthetic anomalies; real go-arounds are
order-anomalies a summary can't see and a sequence model can. Per the pre-registered rule (decide on
real-anomaly score, not synthetic), **we ship the LSTM-AE.**

## The external checks

Two more, both pre-committed:

- **A real head-to-head.** The SADAR project's VAE-LSTM, built independently on the same data, scored
  ROC 0.659 on real anomalies against the same 2020-normal baseline. Ours: 0.667. Two independent
  implementations within 0.01 of each other on the one metric neither team could tune toward — the
  closest a five-week project gets to a replication. (We reproduced his published number exactly from
  his released weights first, to be sure the comparison was real.)
- **A real emergency from outside our pipeline.** BCS63A — an A306 that declared emergency and turned
  back to LEMD, from OpenSky's curated 7700-squawk dataset — scored at the 98.8th percentile (AE) /
  100th (kNN) of normal. N=1, a case study, but a real emergency the model never saw landing among
  the most anomalous tracks in the airspace.

A qualitative pass over the 20 highest-error "normal" flights found holding patterns and
order-anomalies, not noise — including three the AE flagged that the kNN thought normal, the exact
sequence-vs-summary distinction the whole argument rests on.

## The verdict, stated plainly

We ship the LSTM-AE, and we say what that does and doesn't mean. It is the best model on the metric
that matters — real anomalies — and it matches an independent team's model there. It also missed our
own primary synthetic target (0.731 < 0.85) and lost the synthetic bench to a plain kNN that we keep
and report rather than hide. The kNN is the honest cheaper alternative; the AE earns the pick because
real go-arounds, not synthetic injections, are what a deployed system actually meets.

That tension — simple wins the benchmark, deep wins reality — is the most useful thing the project
produced. It is exactly why you don't let a synthetic bench, however carefully calibrated, be the
last word.
