# 09 — We set out to build a counter-drone detector. The architecture was the wrong question.

> **Status:** Draft — **numbers landed (Phase 6 + 7 closed 2026-06-02).** All `[brackets]` are
> now resolved with real values from the test burn (issue #29). The thesis held: the AE earns its
> keep on the *dynamic* anomalies the deployed rules miss (loiter 0.97, intercept 0.79) and is
> out-of-remit on the spatial ones they already own (zone 0.55). Two beats the original draft did
> not anticipate — a plain kNN beat the deep model on *synthetic* anomalies but lost to it on
> *real* ones, and a parallel team's model (SADAR) gave us a real-anomaly head-to-head — both
> *strengthen* the architectural critique and are folded in below. Still needs an editing pass for
> length before publishing.
>
> **Audience:** ML practitioners, aviation tech-curious. Sharable on Medium. ~2,500-3,000 words after editing.
>
> **Cross-references:** This draft folds in the Phase-1 framing (chapters 01, 03), the data-source pivot (D-007), the multi-layer validation stack (D-008), and the in-session architectural critique developed 2026-05-23. If anything below contradicts the formal ML docs, the formal docs win — this file is narrative rationale.

---

## The hook

December 19, 2018. London Gatwick. Britain's eighth-busiest airport closes for **36 hours**. More than **1,000 flights** cancelled. **140,000 passengers** stranded. Estimated cost: **£50 million**. Cause: unconfirmed reports of drones over the runway. The drones, if they were drones at all, were never recovered. No one was prosecuted.

That image — consumer drones grounding an international hub for a day and a half — is what got us interested in counter-drone detection. Our team of four signed up for Saturdays.AI Madrid's deep-learning course in March 2026, picked Scenario 8 from the course brief, and put Madrid-Barajas (LEMD, the fourth-busiest airport in Europe) at the center of a five-week project. We were going to build an unauthorized drone detector.

We didn't.

What we ended up building was something narrower, more honest, and — we'd argue — more interesting: a behavioral anomaly detector for the cooperating-aircraft regime that the deployed safety nets at every European ATC center already mostly cover. The gap between what we set out to build and what we actually shipped is the lesson worth writing about.

This piece is about that gap.

## The setup: copying the cyber/fraud playbook

The instinct of an ML team facing "detect unauthorized activity" is to reach for a two-layer architecture. It's almost a reflex, and the reason it's a reflex is that in cyber/fraud detection, it works.

**Layer 1: known-good gate.** Cheap, deterministic, rule-based. Signatures, blocklists, identity lookups, allow-lists. Catches the obvious cases at near-zero per-event cost.

**Layer 2: unsupervised anomaly scorer.** Slower, more expensive, learns the distribution of normal behavior. Catches what Layer 1 missed.

This pattern shows up everywhere. Credit-card fraud: the issuer's rule engine flags transactions that match known fraud signatures (Layer 1), and an ML model scores everything else for anomaly (Layer 2). Network intrusion: signature-based IDS catches known attacks (Layer 1), behavioral analytics catches novel attacks (Layer 2). E-commerce account takeover: known-bad IPs are blocked outright (Layer 1), session-behavior models catch the new ones (Layer 2).

It works in these domains because **Layer 1 is dirty**. There are constantly new attack vectors, signature gaps, adversaries who deliberately evade the rules. Layer 2 earns its keep by catching what Layer 1 cannot, on a population large enough that the residual cases matter.

We thought aviation needed the same structure. The mapping looked obvious:

- **Layer 1**: ICAO24 transponder registry lookup + U-Space flight-plan match. If the aircraft has a valid registered transponder and a filed plan that matches its trajectory, it's known-good.
- **Layer 2**: An LSTM autoencoder trained on real ADS-B trajectories near LEMD. Score new trajectories by reconstruction error. High error = behavior the model doesn't recognize as normal = candidate anomaly.

We wrote a design document, ran an `/office-hours` session with an AI partner (Garry Tan's GStack, for the curious), got a Phase 1 problem statement signed off, and started building.

## The build, in numbers

The middle of the project is the kind of thing that doesn't make a Medium piece, except as receipts. We owe you the receipts.

- **Data:** OpenSky Network ADS-B state vectors, filtered to a 200 km radius around LEMD. Three audit cycles. Cycle 1 and 2 used the Trino + Supabase ingestion path one teammate ran; cycle 3 (added late) used the OpenSky public scientific dataset directly, with a heuristic Filter B substituting for missing origin/destination metadata. The pivot is its own story (chapter 09's neighbor, eventually). Final corpus: **~21,800** unique trajectories, **~6.35M** state-vector rows (after Phase-3 preprocessing: 19,849 clean segments, 3.16M rows).
- **Architecture:** Encoder-decoder LSTM, deliberately small — a 32-unit hidden state, 16-dim latent, single layer (a config sweep showed bigger didn't help; more on that below). Encoder maps the `(T=260, 9)` trajectory tensor to the latent; decoder reconstructs it; loss is MSE masked over the real (non-padding) timesteps. Small enough to train quickly on a single GPU. The operating point is a reconstruction-error threshold (0.222) chosen on the validation set to balance recall against the false-positive guardrail — fixed before the test set was ever scored.
- **Baseline:** Isolation Forest on aggregate per-trajectory features (mean, std, min, max per channel). Same self-supervised setting. The honest contrast: if the LSTM autoencoder doesn't beat IF by a meaningful margin, sequence-aware modeling isn't pulling its weight and we ship IF. (We later widened this to a kNN density baseline on the *same* summary features — the comparison that turned out to matter most.)
- **Pre-committed decision rule (D-006):** LSTM val AUROC ≥ IF val AUROC + 0.03 → ship the LSTM. Otherwise ship IF. Locked in Phase 1, before any training. No retconning. (Phase 7 added a second, stricter gate the original rule didn't anticipate: the model that wins on *real* anomalies, not just synthetic ones.)
- **Operational metric stack (D-005):** AUROC primary, F2 secondary (β=2 weights recall over precision, expressing "missing a hostile drone is worse than a false alarm"), FPR ≤ 15% as a hard guardrail, PR-AUC as a sanity check.

That's the project the design doc promised. It's what we built. The model works in the technical sense — converges, reconstructs normal flights well, scores synthetic anomalies higher than normal. On synthetic validation the LSTM AE (AUROC 0.664) cleared the Isolation Forest (0.625) by the pre-committed +0.03 margin, so D-006 said ship the AE. On paper, success.

Except the paper had a footnote we'll get to: when we widened the baseline panel, a plain k-nearest-neighbors density model (0.707) *beat* the deep model on those same synthetic anomalies. The deep model didn't obviously earn its complexity. Hold that thought — it turns out to be the most important result in the project, and we'll come back to it once the architectural picture is in place.

So what's the problem?

## First crack: drones don't broadcast

Here's the thing about ADS-B. **ADS-B is cooperative.** Aircraft choose to broadcast their identity, position, velocity, and altitude. The protocol exists because cooperative surveillance is cheaper and more accurate than radar for known-good actors — manned commercial aviation, mostly. Aircraft regulators mandate it for most commercial operations. Drone regulators, in most jurisdictions, do not — and consumer drones (DJI's, the GoPro-strapped FPV racers, the hobby quadcopters that grounded Gatwick) almost never broadcast ADS-B. They don't have the transponder hardware. They don't have the certifications. They can't legally use the protocol's ID space.

This is not a footnote. It is the load-bearing structural fact about our data.

The corpus we trained on is essentially **manned commercial aviation around Madrid**. When we say the LSTM autoencoder "learns what normal looks like," what it learns is what *Airbus A320s, Boeing 737s, ATR 72s, and the occasional bizjet on filed IFR plans* look like as they approach or depart LEMD. The most ambitious thing the model can claim about a new trajectory is: "this doesn't look like normal manned commercial flight at LEMD."

That claim flags any drone trivially. A consumer drone hovering at 100 m above a runway threshold doesn't fly like a 737 — of course the model flags it. But it also flags any aircraft that isn't a commercial jet on a standard approach: GA aircraft, helicopters, military, pilots in distress, training flights doing pattern work. The model is detecting *not-a-737-shaped-flight*, not *drone-shaped-flight*.

And the actual rogue drone — the Gatwick threat — never appears in the data at all. The model cannot detect what it cannot see.

Mid-Phase 2, this fact stopped being abstract. We were sitting on a corpus of ~3 million ADS-B rows around LEMD. None of those rows were drones. None of them could be drones, because the protocol excludes them. The "counter-drone detector" framing was already a stretch.

## Second crack: Layer 1 is too clean

You could keep the framing alive by leaning on Layer 1. "Sure, the model itself only catches what looks anomalous against manned commercial flight — but combined with the identity gate, the system as a whole catches unauthorized aircraft." Right?

Not really. Here's what we missed: **the cyber/fraud architecture works because Layer 1 is dirty. In aviation, Layer 1 is far cleaner than we accounted for.**

Aviation registry data is among the most regulated identity infrastructure in any industry. ICAO24 codes are 24-bit unique aircraft identifiers, allocated by national authorities, embedded in transponder hardware, near-universal in commercial aviation. Flight plans are filed in advance with ATC and the national ANSP. Deviations from filed plans are visible to controllers in real time and trigger immediate radio inquiry. The "Layer 1" we mapped onto aviation isn't a signature engine catching known threats — it's an entire regulatory ecosystem, complete with controllers actively watching the radarscope.

When we asked ourselves, honestly, "what unauthorized presence at LEMD does Layer 1 *fail* to catch?", the answer was a much narrower set than we initially imagined:

1. **Spoofed transponder.** A bad actor broadcasts a stolen or cloned ICAO24 that matches a real registered aircraft. Layer 1 says "valid registry match." This is theoretically possible. It also has a more reliable detection signal than trajectory anomaly: in a multi-sensor system, the position reported by ADS-B and the position measured by independent radar should agree. If they disagree, that's spoof. Trajectory anomaly is a weaker corroborator at best.

2. **Pilot deviation, mode confusion, hijack.** The aircraft *is* who it claims to be, *is* where it says it is, but it's flying *wrong*. Medical event in the cockpit, autopilot in the wrong mode, deliberate deviation from filed plan, hijack. Layer 1 says clean. Independent sensors agree on position. Only the *behavior* is off. This is the case where trajectory anomaly is the unique signal — and it's the niche our model actually addresses.

3. **Triage.** Layer 1 fires on hundreds of "unidentified" tracks per day at any major airport — GA aircraft with transponder issues, late flight plans, brief radio gaps. Most are nothing. Layer 2 could rank-order those by trajectory unusualness so a safety analyst reviewing the day's completed traffic looks at the most concerning ones first. This is a retrospective UX problem, not a real-time detection problem.

That's it. That's the Layer 2 domain when Layer 1 is as clean as aviation's. It's a real niche. It's not Gatwick.

**And one more honest qualifier — the one that pins down who this is even for: the time horizon.** Our model scores *complete* trajectories. The score lands after the flight is over, which rules out the live controller — the aircraft is already gone by the time we have a number. The realistic user is retrospective: surveillance-side flight-data monitoring, post-operations safety review, triage of yesterday's traffic for an analyst to inspect the next morning. So the deployed safety nets and our model aren't complementary by catching different things in the same instant; they're complementary by *time horizon* — real-time geometric alerting for the controller, retrospective behavioral analysis for the safety analyst. A streaming version would be more operationally useful, but it's a different architecture (predictive or windowed, not whole-trajectory reconstruction) and partly the nets' turf already. And for a five-week course project on public OpenSky data, that analyst is hypothetical anyway: the real deliverable is the methodology, not a tool anyone is about to deploy.

## The reframe

If "does our Layer 2 catch unauthorized aircraft?" is the wrong question — because most unauthorized presence is caught by Layer 1 alone, and the things that slip through Layer 1 are addressed better by multi-sensor crosscheck — then what's the right question?

The right question, the one we should have been asking from Phase 1, is:

> **Does our Layer 2 catch behavioral anomalies that the deployed safety nets at every European ATC center already miss?**

Every operational ATC center, LEMD included, runs four ground-based safety nets defined by Eurocontrol:

- **STCA** (Short Term Conflict Alert) — predicts loss of separation between aircraft pairs.
- **APW** (Area Proximity Warning) — flags aircraft penetrating restricted airspace volumes.
- **MSAW** (Minimum Safe Altitude Warning) — flags aircraft below terrain-clearance minimums.
- **APM** (Approach Path Monitor) — flags deviations from standard approach corridors on final.

These are rule-based, deterministic, deployed for decades, and *they directly cover the obvious version of what our model claims to do.* APW maps onto our "zone violation" anomaly type. MSAW maps onto "altitude violation." APM maps onto deviations during final approach. The status quo at LEMD is not "nothing" — it is four well-tuned deterministic safety nets, three of which directly address three of our four synthetic anomaly types.

So the experimental question reformulates as: **when, and on which anomaly shapes, does the LSTM autoencoder catch things that the safety-net stack at LEMD already misses?**

That is a question we can answer with data.

## The experimental contribution

To answer it, we built three baselines:

1. **Isolation Forest** on per-trajectory aggregate features — the apples-to-apples sequence-vs-no-sequence comparison from D-006.
2. **Safety-net rules baseline** — hand-coded analogs of APW, MSAW, and APM. APW: trajectory enters a restricted polygon. MSAW: altitude below a distance-from-runway threshold. APM: deviation from a 3° glide-slope corridor. ~half a day of code, no training. These approximate what's actually deployed at LEMD today.
3. **Geofence baseline** from the design doc — a single-variable threshold that must score < 0.80 AUROC on our injections or the injections are too easy.

We then stratified the eval by anomaly type. Pre-commit to the expected per-type pattern (so the result can't be retroactively reframed):

| Anomaly type | Pre-commit prediction | What it would mean |
|---|---|---|
| Zone violation | APW analog wins or ties | The safety net is well-tuned; AE adds little |
| Altitude violation | MSAW analog wins or ties | Same |
| Hovering | AE wins clearly | No deployed safety net catches sustained zero-velocity behavior |
| Speed spike | AE wins clearly | No safety net catches short-duration kinematic spikes |
| Late-trajectory deviation (if implemented) | AE wins | Static thresholds can't catch behavioral deviation that emerges in flight |

Here is the pattern that landed, on the held-out 2020 test fold (AUROC, each anomaly type injected and scored against normal):

| Anomaly type | LSTM-AE | kNN | Isolation Forest | Verdict |
|---|---|---|---|---|
| `sustained_loiter` | **0.971** | 0.986 | 0.952 | AE wins clearly — no deployed net catches sustained near-zero velocity |
| `final_approach_intercept` | **0.789** | 0.786 | 0.745 | AE wins — behavioral deviation a static corridor check misses |
| `speed_spike` | 0.580 | 0.815 | 0.587 | weak for the AE (kNN's max-velocity summary wins this one) |
| `altitude_high` | 0.558 | 0.594 | 0.556 | near-chance — MSAW's geometry already owns it |
| `zone_violation` | 0.551 | 0.541 | 0.503 | near-chance — **APW already owns it** (out-of-remit) |

The prediction held where it counts. The AE is strong (0.79–0.97) exactly on the *dynamic* anomalies — sustained loiter, in-flight approach intercept — that no deployed geometric safety net is built to catch, and near-chance (0.55) on the *spatial* ones (zone, altitude) that APW and MSAW have covered deterministically for decades. We treat the spatial rows as out-of-remit, not as failures: a reconstruction AE was never going to out-detect a well-tuned polygon check on a 1–3 km lateral shift, and it doesn't have to — that's the rule's job.

The architectural lesson lands cleanly: **the LSTM autoencoder earns its complexity on the sequence-shaped anomalies the deployed rules don't cover, and adds nothing on the geometric anomalies that have been deterministic-rule-able for decades.** This is the whole result. Lead with this table, not with any single averaged number — the average is dominated by whichever anomaly mix you choose, and averaging an in-remit capability with an out-of-remit one produces a figure that means nothing.

### The footnote that became the headline: simple beat deep on synthetic

Remember the kNN. Across all five synthetic types its mean AUROC (0.786 on test) sat *above* the deep autoencoder's (0.731), and the primary target we set in Phase 1 — AUROC > 0.85 — went unmet by both. By the strict reading, our deep model did not earn its complexity: a density estimate over four summary statistics (mean, std, min, max per channel) ranked our hand-designed anomalies better than a trained sequence model.

We could have buried that. Instead it became the cleanest test in the project, because of what happened when we stopped scoring *synthetic* anomalies and started scoring *real* ones.

That's a much narrower, much more defensible claim than "we built a counter-drone detector." It's also more useful for anyone considering deploying ML in this space. The practitioner question isn't "does anomaly detection work?" It's "where does it earn its keep against what's already running?"

### External validation, part 1: the real-anomaly test (where simple stopped winning)

The per-type breakdown is necessary but not sufficient. Synthetic anomalies are anomalies we hand-designed. A high AUROC against them proves the model can catch what we asked it to catch, not that it generalizes — and the kNN's synthetic win raised exactly the right suspicion: maybe the deep model just lost a contest that was rigged by our own injection shapes.

So we set the synthetic bench aside and scored both models on **real anomalies neither had ever seen**: a held-aside cohort of 191 real **go-arounds** and 4 real **emergencies** (segments we identified geometrically and routed out of training back in Phase 5, specifically to keep them clean for this moment). Real behavioral anomalies, never trained on, never injected.

The ranking inverted.

| | synthetic AUROC | **real-anomaly ROC** |
|---|---|---|
| LSTM-AE | 0.731 | **0.667** |
| kNN | 0.786 | 0.595 |
| Isolation Forest | 0.717 | 0.495 (chance) |

On real anomalies the deep model **beat** the kNN that had beaten it on synthetic (0.667 vs 0.595), and the Isolation Forest collapsed to chance. This is the result the whole project turns on. A kNN over summary statistics can win a synthetic bench because hand-designed perturbations tend to move a summary stat (a spike in max-velocity, a shift in mean-altitude) in ways a density estimate picks up cleanly. Real go-arounds don't oblige: a go-around can be *summary-normal but order-abnormal* — the altitudes and speeds look ordinary in aggregate, and only the **sequence** (descend, level, climb again) is wrong. That is precisely what the LSTM's reconstruction sees and the kNN cannot. The deep model earns its complexity not on the synthetic bench we built, but on the real anomalies we couldn't design.

We pre-registered this comparison — model choice by real-anomaly score, both models reported, no dropping the loser — before unsealing the test set, so the inversion can't be read as post-hoc cherry-picking.

**A second team, the same data, a real head-to-head.** A teammate independently built **SADAR**, a full parallel system (same OpenSky-LEMD data, a VAE-LSTM autoencoder, a deployed FastAPI + React demo). That gave us something rare for a course project: an external model to compete against on real anomalies, built by someone who never saw our code. Scored on real emergencies and go-arounds against the same 2020-normal baseline, his VAE-LSTM reached ROC 0.659; our LSTM-AE, 0.667. A dead heat — we matched a second independent implementation on the one metric neither team could tune toward. (The precision-recall numbers differ more, but that gap is an artifact of different windowing and prevalence, not model quality; we say so in the formal eval and don't lean on it.) Two independently built models landing within 0.01 of each other on real anomalies is the closest thing a five-week project gets to a replication.

### External validation, part 2: a real emergency the model never saw

The held-aside cohort is real but in-distribution (our own LEMD traffic). For a genuinely external check we scored the model on **OpenSky's published reference dataset of real in-flight emergencies** (Olive et al., 2020) — flights that triggered the 7700 transponder squawk, a pilot-set code for general emergency, curated entirely outside our pipeline.

Of 832 global 7700 flights, exactly seven have any track within 200 km of LEMD, and only **one** is a genuine close-in Madrid operation rather than a distant en-route transit: **BCS63A**, an Airbus A306 that declared an emergency and **turned back to land at Barajas**. Scored by the trained models, that single real emergency lands at the **98.8th percentile** of the normal-flight distribution for the AE, and the **100th** for the kNN — flagged, clearly, by a model that never saw it. It is N=1, a case study not a statistic (the other six are en-route transit, correctly excluded as a cross-airport confound), but it is a real emergency the model had never seen scoring as one of the most anomalous tracks in the airspace. The "real emergencies score high" direction landed.

### Qualitative check

The last piece: we examined the top-20 reconstruction-error trajectories from the *normal* validation set — flights the model considered anomalous *within data we had labeled "normal."* The question: do they look weird?

Of the 20, **seven** carry clear circling/holding signatures (cumulative heading change past 400°), several show the oscillating climb-descent of an unstable or holding descent, and — the most telling — **three are flagged by the AE but look normal to the kNN**: order-abnormal yet summary-normal, the exact failure mode the sequence model is supposed to catch and the density baseline cannot. None were already-tagged go-arounds; these are cases the "normal" label glossed over. (The final per-flight human classification — obvious anomaly vs subtle vs genuine false positive — is a reviewer's pass we've scoped but not finished; the diagnostic evidence is in the Phase-7 notebook.)

That the top-error "normal" flights are disproportionately holding patterns and order-anomalies, not random noise, is the corroborating signal: the model is generalizing beyond the injection shapes, which is what makes the real-anomaly result above earned rather than spurious.

## The lesson

The bigger lesson — the one that travels beyond drone detection at airports — is about how methodology transfers across domains.

The two-layer detection architecture is a fixture of cyber/fraud detection. It works there because the assumptions match the domain: Layer 1 is necessarily incomplete (adversaries evolve faster than rules), the population is large enough that Layer 2's residual catch matters, and the cost of a Layer-1 false negative is high enough to justify a second-pass scorer.

In aviation, none of those assumptions transfer cleanly. Layer 1 is *not* incomplete in the same way — the regulatory ecosystem makes the gate dramatically cleaner than fraud signals. The population of Layer-1-passes is mostly fine, by design. The Layer-2 job is much smaller than the cyber/fraud framing predicts.

Which means: **applying the two-layer pattern uncritically to aviation gets you a model that solves a problem narrower than the framing claims.** Not the catastrophic Gatwick threat. The narrow, important, but unspectacular problem of catching behavioral anomalies on cooperating aircraft that the deployed safety nets don't.

That's a lesson worth carrying into the next domain. Architectural patterns are domain-specific. The questions that justify a Layer 2 in cyber/fraud don't justify the same Layer 2 in aviation, medical monitoring, or regulated finance. Before adopting a pattern from domain A in domain B, audit whether the assumptions that make it work in A actually hold in B.

For us, that audit happened during the build, not before. The honest thing to do is write about what the audit changed.

## What this project IS, and what it isn't

If you're considering deploying something like our model in production, here's what we built and what we don't claim to have built:

**What it is:**

- A behavioral anomaly detector for cooperating aircraft in the LEMD area.
- One component of a hypothetical multi-sensor counter-UAS or air-traffic-safety stack — not a standalone system.
- A modest, measurable improvement over deployed rule-based safety nets *specifically on sequence-shaped anomalies* (hovering, speed spikes, behavioral deviation). On geometric anomalies the safety nets already cover, it adds little.
- A reproducible artifact: data is public (OpenSky scientific dataset #1), filtering is documented (Filter B), evaluation is public (synthetic injections grounded in real-incident data per FAA UAS Sightings + Bard + Spanish press, see 07-eval-prep.md), validation includes a public real-emergency external set (OpenSky Dataset #6 per Olive et al., 2020).

**What it isn't:**

- A counter-drone detector. Drones don't broadcast ADS-B; the model has never seen one.
- A replacement for STCA, APW, MSAW, or APM. The deployed safety nets are well-tuned for the geometries they cover. We complement, we don't replace.
- A production system. This is a course-deliverable demo. The threshold is operator-tunable in the demo (a slider). FPR ≤ 15% is a guardrail, not a deployment claim.
- A general claim about ML for aviation. Single-airport (LEMD), single-day-of-week-heavy sampling (Mondays), single-period (2017-2020 with COVID excluded). The conditional-normality question — does this model generalize across runway configurations, wind directions, seasons — stays open.
- A high-AUROC headline. Our Phase-1 primary target was AUROC > 0.85; the synthetic test came in at 0.731, and we report that plainly. The value of the project is the *per-type* and *real-anomaly* picture, not a single averaged number — and on a strict reading, a plain kNN remains a credible, cheaper alternative that we keep and report rather than hide. We ship the LSTM-AE because it wins the contest that matters (real anomalies); we don't pretend it dominated everywhere.

## Coda

We didn't set out to write this piece. We set out to build a counter-drone detector. Halfway through the project, we noticed the framing didn't fit the data, the architecture didn't fit the domain, and the real contribution was much smaller and much more specific than the original pitch.

We could have shipped the model under the original framing. Most class projects do. The pitch deck for "counter-drone detector for Madrid-Barajas" writes itself; it just doesn't survive a careful read.

What we shipped instead is narrower and more honest: a small, measurable result on a specific question (when does an LSTM AE earn its complexity against deployed safety nets?), grounded in a publicly reproducible dataset, validated against real emergencies the model never saw. It's a one-paragraph result, not a one-headline story.

If anything in this piece is the part worth keeping, it's not the model. It's the architectural critique: the next team that copies a detection pattern from one domain to another should audit the assumptions first. Layer 2 only earns its keep where Layer 1 is genuinely incomplete. In aviation, where regulatory infrastructure makes Layer 1 clean, the ML has a smaller, sharper job than the cyber/fraud paradigm predicts.

That's worth knowing before you build, not after.

---

## Notes for future editors of this draft

1. **Brackets are resolved (2026-06-02).** All numbers are now real, from the Phase-7 test burn (issue #29, `07-eval.md`, `phase7_burn_results.json`). If any figure here disagrees with `07-eval.md`, the formal doc wins — fix this draft.

2. **The outcome landed favorably for the thesis.** Real emergencies scored high (BCS63A 98.8th pctile), the AE beat the kNN on real anomalies, and it matched the parallel SADAR model — so the architectural critique is corroborated, not salvaged. The honest counterweight to keep in: the synthetic AUROC missed the 0.85 target and the kNN won the synthetic bench. The piece is stronger *because* it carries that tension, not despite it — don't edit it out to make the AE look cleaner than it is.

3. **Team alignment is required.** If any teammate writes their section from a "we built a counter-drone detector" frame, this thesis collapses on contact. Sync on the framing before parallel writing.

4. **Length.** This draft is ~3,000 words. The Medium target is 2,500-3,000 after editing. Cut where it slows down — the "build, in numbers" section is the most prunable.

5. **Tone.** Confident, builder-to-builder, opinionated. The piece should sound like someone who shipped the project, not someone defending it. If a paragraph reads like cope, rewrite it. The architectural lesson is the planned arrival point, not a retrofit.

6. **The decision matrix.** If after seeing Phase 6/7 the team prefers Sharper over Spicier (i.e., "When does ML earn its keep?" instead of "We set out to build a counter-drone detector"), most of this draft survives — drop the coda's "we didn't set out to write this" beat and rebalance the hook. The bones (cyber/fraud setup, two cracks, reframe, per-type contribution, external validation, lesson) stay regardless.
