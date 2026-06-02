# Phase 7 — Evaluation Prep: Anomaly Injection Calibration

**Status**: prep notes only. Phase 7 has not started yet.
**Created**: 2026-05-10
**Generated during**: Phase 2 (data validation), as a research side-quest before extraction concluded.
**Why now**: to ground synthetic anomaly injection in real incident behavior, so Phase 7's `inject_anomalies(...)` parameters have evidence behind them instead of design-doc defaults.
**Cross-references**:
- Design doc (current target of revision): `backend/docs/architecture/design-trajectory-anomaly-detection.md` (Anomaly Injection section)
- Manifest pointer: `backend/docs/ml/manifest.yml > gates.eval.summary`
- Phase 1 problem framing: `backend/docs/ml/01-problem.md`
- Architecture decision the original perturbations live in: `backend/docs/ml/decisions/D-006-architecture-and-baseline.md`
- Multi-layer output validation decision (added 2026-05-23): `backend/docs/ml/decisions/D-008-output-validation-layers.md`. This doc is the Layer 2 source (discriminative validation via synthetic injection). Layer 4 (external validation via Dataset #6 real-emergency flights) and Layer 5 (qualitative top-K review) are codified below in "Validating beyond synthetic discrimination."

---

## Why this document exists

The drone trajectory anomaly detector is trained on real ADS-B normal flights. There is no public, labeled dataset of *unauthorized* drone trajectories at LEMD — and there never will be, because unauthorized drones don't broadcast ADS-B (that's why they're unauthorized). Per Decision D-001, the project is framed as anomaly detection rather than three-class classification specifically to handle this asymmetry: train on abundant labeled normal data, evaluate against synthetic perturbations of normal trajectories.

The design doc (`architecture/design-trajectory-anomaly-detection.md`, *Anomaly Injection (for evaluation)*) specifies four perturbation types as defaults:

1. **Zone violation** — reroute path through restricted polygon
2. **Altitude violation** — shift altitude sequence ±300m
3. **Hovering** — replace 30s segment with speed ≈ 0, position frozen
4. **Speed spike** — multiply velocity by 3× for a 20s window

These are reasonable defaults but were specified *before* checking how real unauthorized drones behave near airports. The risk: the perturbations could be systematically too easy (inflating AUROC), wrong-shaped (e.g., perturbing speed when reality is mostly position+altitude), or under-/over-aggressive in ways that disconnect the test from operational reality. A Phase 7 AUROC of 0.92 against perturbations the team made up is a much weaker claim than 0.85 against perturbations grounded in real incident data.

This document is the empirical grounding. The research below was run during Phase 2 (ahead of schedule), via a side-session with web-fetch access enabled, against four public sources covering ~2,200 drone-incident records. The findings should drive Phase 7 entry-gate revisions to the design doc's anomaly injection.

## How to use this in Phase 7

When Phase 7 starts (after Phase 6 model training is done, before any test-set scoring):

1. **Read this doc end-to-end** before writing the `inject_anomalies(...)` code.
2. **Revise the four perturbations** per the *Calibration recommendations* section below. Apply what's actionable in the timeline; document any deviations explicitly.
3. **Add the two new types** (final-approach intercept, multi-drone) if Phase 6 didn't run long. Defer if time-pressed.
4. **Run the Layer 4 + Layer 5 protocols** from "Validating beyond synthetic discrimination" (below). These are independent of injection calibration and produce the writeup's external-validation finding.
5. **Cite this document** as the source for every perturbation parameter chosen in the final code, in the writeup's Methodology section.
6. **Cite the public sources directly** in the writeup's Limitations section, so the calibration is auditable.
7. **Update `manifest.yml > gates.eval.summary`** with the final perturbation list, the Layer 4 finding, and link back to this doc + any ADR (likely D-010) capturing the deviation from the design doc's defaults.

## TL;DR — the five highest-value changes

For fast scan when revisiting this doc later:

1. **Altitude perturbation should be asymmetric upward, not symmetric ±300m.** Real anomalies skew high — drones operating illegally near airports are systematically *above* the 120m hobbyist ceiling, not below. Median altitude in FAA narratives is 914m; Bard data shows 575m mean even within 5 nm of an airport. Symmetric ±300m is wrong-shaped.
2. **30s hover is too short.** Real operational events at LEMD lasted 30–105 minutes of presence. Add a sustained-loiter variant (60–300s) alongside the 30s micro-hover.
3. **Speed spike is over-aggressive AND over-represented.** Only 0.7% of FAA narratives use "high-speed" descriptors. 3× is racing-drone territory, not airport-incursion territory. Drop to 1.5–2× for 5–10s and reduce its share of the injection mix to ≤10%.
4. **Zone violations are under-represented.** They should be ~40% of injections (not 25%) — they match 35–58% of real reported behavior across FAA + Bard.
5. **Two missing types worth adding:** final-approach corridor intercept (drone crosses an active arrival corridor at low altitude near the runway threshold), and multi-drone swarm (2–4 simultaneous trajectories within a 1 km radius).

The single most important meta-observation: **for the 5 documented LEMD events, the public record describes only "drone in vicinity" — no trajectory detail.** AENA/AESA do not release event-level data. So all calibration of LEMD-specific perturbations remains anchored to U.S. data; this is a confidence ceiling, not a fixable gap.

## Post-reframe reconciliation (added 2026-06-01) — READ BEFORE IMPLEMENTING §6

This document's research report below (§1–§8) was written **2026-05-10, under the original counter-drone-detector framing**. The architectural reframe (D-010 + `writeup/09-the-architectural-critique.md`, 2026-05-23) changed what the model *is*: a **behavioral conformance monitor on cooperating manned aircraft**, whose value proposition is catching the **sequence/kinematic anomalies (hovering, speed spikes)** that the deployed geometric safety nets (APW, MSAW, APM) already miss. Two items in the verbatim §6 below are now in tension with that thesis. The verbatim text is preserved per this doc's append-only rule; this note overrides it:

1. **§6 recommendation #7 ("Weight loss reconstruction toward position + altitude features over speed/heading") is a pre-reframe artifact — do NOT implement it as a model or score weighting.** Its reasoning ("the cheap tells of a *drone* are wrong-place + too-long") is drone-incident reasoning, and the model is not a drone detector. Worse, it is *backwards* against the thesis: APW already covers zone (position) and MSAW covers altitude, so down-weighting speed/heading would blind the AE in exactly the channel (hovering, speed spikes) where 09 pre-commits it must beat the rules baseline. Keep the reconstruction loss **framing-agnostic (equal-weighted)**. If you want per-feature reconstruction error, use it as a **diagnostic / interpretability output** (which channels drive a given score), never as a tuning knob — and never tune it against this bench (that would close a loop between bench design and model, inflating AUROC).

2. **The synthetic bench's deliverable is the per-type stratified comparison, not a single headline AUROC.** Per 09, the result is a table of AE vs Isolation Forest vs **safety-net-rules baseline** vs geofence, broken out by anomaly type. "Calibrate the bench harder" therefore means *keep each anomaly type/intensity realistic* (no cartoonish 80 km route-shifts or ×2.2 speed-ups that flatter every detector) so the per-type comparison is honest — it was **never about maximizing a mean**. The zone-violation 40% weighting (§6 rec) is about *bench realism*; APW is *expected* to win/tie on zone, and that is the correct, honest finding, not a failure. Do not benchmark against, or chase, a single mean like a parallel project's "0.792" — that target belongs to the abandoned framing.

Everything else in §6 (asymmetric-up altitude, sustained loiter, softened/demoted speed spike, the two new types) survives the reframe and stands.

## Validating beyond synthetic discrimination

This section is the eval-time companion to **D-008** (multi-layer output validation). It addresses a question the synthetic-injection calibration above (Layer 2) does not answer on its own:

> The AE outputs a reconstruction error per trajectory. That number has no semantic meaning until external evidence grounds it. Synthetic AUROC tells us the model can discriminate the perturbations *we hand-designed* from normal — it does not tell us whether the model behaves meaningfully on anomalies it has never seen. The Phase 1 doc acknowledges this as the "imagination leakage" risk (lines 138-141).

Two protocols below close that gap. Each contributes one layer of validation; together with Layer 1 (sanity), Layer 2 (synthetic AUROC per D-005), and Layer 3 (realism via geofence + safety-net rules baseline), they form the five-layer validation stack from D-008.

### Layer 4 — external validation via real emergencies (Dataset #6)

> **Scope decided 2026-06-01 (D-008 Amendment 2; `dataset6-emergency-external-validation.md §9`).** The Phase-4 inspection found only ~7 scoreable LEMD-area flights (6 of them edge-of-domain transit; only **BCS63A** is a genuine close-in LEMD operation). So **Layer 4 is a case study, not the Mann-Whitney statistical test the protocol below describes**, and the **Western-Europe fallback is rejected** (re-imports the cross-airport confound). The protocol below stands for the *in-range set* (report it as small-N/illustrative, lead with BCS63A), but the **quantitative external-grounding role moves to D-011** — the ~825 non-LEMD emergencies become real-derived injections on LEMD-normal trajectories (no confound, full N). Read the rest of this section with that reframing.

**Source.** OpenSky scientific Dataset #6: *Reference Datasets for In-Flight Emergency Situations*, curated by Xavier Olive (ONERA). Derived from full OpenSky ADS-B between 1 January 2018 and 29 January 2020. Flights that triggered the **7700 transponder squawk** (pilot-set general emergency code). Cite: Olive et al., *OpenSky Report 2020*, IEEE/AIAA DASC 2020.

Why these flights: the 7700 squawk is set by a pilot in a real emergency. ATC, dispatch, and emergency services treat them as significant. They are the closest publicly available proxy for "ground truth anomalies" in commercial-aviation airspace. **The model is never trained on them, never injected with them, never told they exist until this protocol runs in Phase 7.**

**Protocol.**

1. *Phase 4 EDA prerequisite* (do this when EDA runs, not during Phase 7): pull Dataset #6, filter to LEMD-area trajectories using the same 200 km bbox + Filter B as cycle 3. Inspect: N flights, types of emergencies, altitude / approach profiles. Document under Phase 4 EDA artifact.
2. *Phase 6 prerequisite (sealed firewall):* do **not** use Dataset #6 in any training, validation, threshold-tuning, or AE-vs-IF selection step. Same firewall posture as the test set. Per D-006 and D-008 open question #1.
3. *Phase 7 execution (after model selection per D-006):*
   - Score every LEMD-area Dataset #6 trajectory with the trained AE.
   - Plot reconstruction-error distribution against the normal validation distribution.
   - Report the **percentile** of the emergency-flight error distribution within the normal-flight distribution.
   - Run **Mann-Whitney U** (non-parametric, robust to small N): is the emergency-flight error distribution stochastically larger than the normal-flight distribution? Report p-value with N.
4. *Finding template, pre-committed* (prevents post-hoc reframing — this is the literal sentence we publish, with N, percentile, and p filled in by the experiment):

   > "Real-emergency reconstruction errors fell at the **Nth percentile** of the normal-flight distribution (Mann-Whitney U p = **X**), based on **K** LEMD-area 7700-squawk trajectories from OpenSky Dataset #6 (Olive et al., 2020) that the model had never seen during training or injection."

**Expected N.** 7700 squawks are rare — global rate is a few hundred per year over 2 years. The LEMD-area subset will be small (realistic estimate: 5-30 flights). This is enough for a small-N qualitative + non-parametric signal, **not** a headline AUROC. Report it honestly with confidence intervals; do not try to spin small N as definitive.

**Fallback if N=0.** Possible given how rare 7700 squawks are. Fallback: expand to "within 1000 km of LEMD" or use the full Western-European subset, *with the explicit caveat in the writeup* that this conflates LEMD-specific signal with the broader manned-aviation distribution. Decide only if it happens.

**Both outcomes are publishable.** Pre-commit to this before running the analysis:

- *Real emergencies score systematically high (e.g., >90th percentile of normal):* the model is detecting something real. The architectural-critique Medium piece is strengthened by external evidence.
- *Real emergencies score at random (~50th) or low:* the synthetic AUROC was overstating capability. The imagination-leakage risk from Phase 1 has materialized. This is arguably the *more interesting* result for the writeup — a negative result that disciplines the field.

The protocol prevents either outcome from being downplayed.

### Layer 5 — qualitative top-K review of normal-validation flagged flights

**Purpose.** A human-in-the-loop credibility check. ~2 hours total, high signal for the practitioner-audience writeup.

**Protocol.**

1. After Phase 6 model selection per D-006: score the full normal validation set with the trained AE.
2. Take the **top 20 highest reconstruction-error scores** — trajectories the model considers anomalous *within data we labeled "normal."*
3. For each, produce:
   - 2D map of the trajectory (lat / lon)
   - Altitude profile vs time
   - Velocity profile vs time
   - Reconstruction overlay (input vs AE output)
4. One reviewer (the writeup owner) inspects each one for ~5 minutes. Classify:
   - **Obvious anomaly** that should have been excluded from "normal" (e.g., aborted approach, mode confusion, holding pattern, unusual rerouting)
   - **Subtle anomaly** worth flagging (e.g., slight off-corridor approach, atypical descent profile)
   - **Actually normal** (model false positive — looks fine to a reviewer)

**What it tells the writeup.** A 1-paragraph addition to the Medium piece's experimental contribution:

> *"We hand-reviewed the top-20 reconstruction-error flights from the normal validation set. **X of 20** exhibited mode confusion, holding patterns, or aborted approaches that the 'normal' label had glossed over. **Y of 20** appeared normal under qualitative review — these represent the model's false-positive rate against human judgment at this threshold."*

**Why this matters.** If most top-20 look like genuine anomalies, the model is generalizing beyond synthetic injection shapes — strong evidence that Layer 4's expected-positive result (if it lands) is earned, not spurious. If most top-20 look normal, the model is overfitting to noise or to the specific injection patterns, and Layer 4 should be interpreted accordingly.

### Layer 4 + Layer 5 together: what they make claimable

Without these layers, the strongest writeup claim is: "AUROC 0.X on our hand-designed synthetic anomalies, against simpler baselines."

With them, the claim becomes:

> *"AUROC 0.X on synthetic anomalies. AUROC 0.Y for the rules-baseline equivalents of the deployed STCA/APW/MSAW/APM safety nets, per-anomaly-type breakdown showing the AE earns its complexity specifically on hovering and speed-spike anomalies. Real emergency flights (Olive et al., 2020) scored at the Nth percentile of the normal-flight distribution (p=X, K trajectories). Hand-review of the top-20 model-flagged 'normal' flights found Z of 20 to be operationally interesting cases."*

That is the sentence-density a Medium piece aimed at practitioners needs.

### Layer 6 — SADAR cross-project head-to-head on real anomalies (PRE-REGISTERED 2026-06-01)

**Pre-registration (written before peeking — that is what makes it blind).** A teammate's
parallel project SADAR (`huggingface.co/spaces/devrup404/sadar`) trained the same kind of
model (LSTM / VAE-LSTM AE) on the same OpenSky-LEMD data and is the natural comparison. This
block commits the comparison protocol **now**, in Phase 6, so the Phase-7 result cannot be
fished or reframed post-hoc.

**What is already settled (clean, spent nothing sealed):** the *synthetic* difficulty
question. Scoring OUR Phase-6 model (big/topk) on SADAR-style injections (his `eval.yaml`
params — 20-80 km route, ±300-1500 m altitude, ×1.6/2.2/0.4 speed, holding, freeze) gives
**mean AUROC 0.772**, next to his reported **0.792** — and the per-type pattern matches his
(easy types 0.88-0.98, realistic altitude-300 m ≈ 0.60). Conclusion already drawn: **the
0.684-vs-0.792 headline gap is benchmark difficulty, not model quality** — our §6 injections
are deliberately harder. This used only our model on our val + reproduced injections; it
touched no sealed cohort.

**What stays SEALED until Phase 7:** his real-anomaly number is **0.659 ROC / 0.299 PR**,
computed as normal-2020 vs his real emergency+go-around cohort (his report: **~4 emergency +
~100 go-around flights**, windowed; go-around-dominated, window-level label noise). Our
analogue is our held-aside cohort (`emergency ∪ go_around`, 191 GA + 4 emergency segments).
**We do not peek at it in Phase 6** — no model/feature/threshold/loop-back decision may use it
(it would contaminate both the loop-back call and the Phase-7 claim; see #27 thread).

**Phase-7 protocol (run once, blind — our AE + our frozen kNN vs SADAR's VAE-LSTM):**

0. **Our side is TWO models** (added 2026-06-02, §4c of `07-train.md`): the LSTM-AE
   (`lstm_ae_best.pt`) AND the frozen kNN-on-summary (`knn_train_summary.npy` + `scaler.joblib`,
   k=5) — because on synthetic val the kNN beat the AE (0.707 vs 0.664) and the model choice is
   deferred to this real-anomaly test. **Scoring two own-models on the sealed cohort is fine ONLY
   because we pre-commit here to: (a) report BOTH, every metric, no dropping the loser; (b) our
   "representative" model = the higher **real-anomaly PR-AUC** (PR, not ROC — the honest lens at
   ~12% prevalence); (c) no per-model threshold/feature tuning on the cohort.** This avoids
   turning a 2-model burn into multiple-comparisons cherry-picking on the test set.
1. **Fix the shared real-anomaly cohort by `flight_id`** before scoring. Pre-commit our
   go-around definition (`features.detect_go_around`, the airborne-run geometric rule) +
   `is_emergency` as the ground-truth set; if his vertrate-threshold rule disagrees on
   membership, report the intersection AND each project's own cohort (don't silently pick the
   flattering one).
2. **Each model on its NATIVE representation of the SAME flights** — his VAE-LSTM on his ENU
   60-step windows; our AE + kNN on our per-segment 260×9 / 24-dim summary. No cross-feature
   translation (lossy and would unfairly handicap a side). The comparison is "systems as each was
   actually built," not a controlled ablation — state that caveat.
3. **Metrics:** ROC-AUC **and** PR-AUC (PR is the honest lens at ~12% prevalence), reported
   **per cohort** (go-around vs emergency separately — go-arounds are the easier, dominant
   class; pooling hides it). Plus our external D-008 **Layer-4** set (OpenSky #6 7700), which
   has more real emergencies than the n=4 in-distribution either project holds.
4. **Pre-committed finding template** (fill N / numbers from the run; both outcomes publish):

   > "On a shared real-anomaly cohort (K go-around + M emergency flights neither model trained
   > on), our model scored ROC-AUC **A** / PR-AUC **B** vs SADAR VAE-LSTM **C** / **D**. [We
   > beat / matched / trailed it] on real anomalies — the comparison that, unlike synthetic
   > AUROC, neither project could calibrate toward."

**Honest confounds to state, not bury:** SADAR trains on 2017-**2019** (we hold 2019 as val →
he has more training data); different features (ENU x/y vs our raw+dist), windowing (10-min
sliding vs whole-segment), and go-around definitions. So a small gap either way is not proof
of model superiority. The un-gameable part is simply that *both* numbers are on real anomalies
neither side designed.

**Engineering note (Phase-7 setup):** his weights (`models/vae_lstm.pt`) + processed arrays
are git-LFS in his Space (cloned, uv-installable); running his model = `git lfs pull` + his
`sadar.eval.compare`. Budget that as a Phase-7 task.

---

## Sources and how to reproduce

Reproducibility note: FAA blocks anonymous fetches. WebFetch and headless browsers both got HTTP 403 on `faa.gov/uas/resources/public_records/uas_sightings_report`. Anyone reproducing this needs `curl` with a real-browser User-Agent + Referer header, or to fetch the file index from the Wayback Machine first.

Sources fetched live in the research session:

| Source | URL | Status | Records |
|---|---|---|---|
| FAA UAS Sightings — FY26 Q1 | `faa.gov/uas/resources/public_records/uas_sightings_report/FY26_Q1_UAS_Sightings.xlsx` | accessible (curl + UA) | 303 narratives |
| FAA UAS Sightings — FY25 Q4 | `faa.gov/uas/resources/public_records/uas_sightings_report/fy25_q4.xlsx` | accessible | 531 narratives |
| Bard College drone report (2015) | `dronecenter.bard.edu/files/2015/12/12-11-Drone-Sightings-and-Close-Encounters.pdf` | accessible, stale | 921 incidents |
| Wikipedia UAV-incident list | `en.wikipedia.org/wiki/List_of_unmanned_aerial_vehicle-related_incidents` | accessible | ~12 airport-relevant |
| Aviation Safety Network | `aviation-safety.net/database/?fenq=drone` | partial — search 404 | 0 |
| Newtral / AESA Spain stats | `newtral.es/incidentes-drones-aeropuertos/20240207/` | accessible | 412 Spain (2019–2023) |
| El Independiente — LEMD Feb 2020 | `elindependiente.com/politica/2020/02/08/la-historia-del-dron-fantasma-que-obligo-a-cerrar-barajas/` | accessible | 1 |
| Aeropuertos en Red — LEMD Feb 2020 | `aeropuertosenred.com/noticias/aeropuerto-barcelona/cierre-del-aeropuerto-por-drones-y-un-aterrizaje-de-emergencia-un-dia-complicado-en-para-el-aeropuerto-de-madrid-barajas/` | accessible | 1 |
| El Español — LEMD Nov 2024 | `elespanol.com/madrid/sociedad/20241106/caos-barajas-avistamiento-dron-bloquea-trafico-aeropuerto-obliga-desviar-vuelos/899160658_0.html` | accessible | 1 |
| Preferente — LEMD Nov 2024 | `preferente.com/noticias-de-transportes/noticias-de-aerolineas/un-dron-bloquea-el-aeropuerto-de-barajas-y-provoca-desvios-masivos-340183.html` | accessible | 1 |
| EASA Annual Safety Review 2025 | `easa.europa.eu/en/document-library/general-publications/annual-safety-review-2025` | partial — synopsis only | ~21 EU 2024 |

100 narratives were sampled in detail from the combined FAA file (rows 0–99 of FY26 Q1).

---

## Research report (verbatim, 2026-05-10)

The text below is the unedited report produced by the external research session — preserved as-is so the original framing, caveats, and confidence levels remain auditable. The only edit is removing a duplicated copy of part of Section 7 that was a copy-paste artifact. **Do not silently rewrite this section** — if findings need updating, append a new dated section below rather than editing the verbatim original.

### 1. Sources consulted

- **FAA UAS Sightings Report (FY26 Q1, Oct–Dec 2025)** — accessible (via curl + browser UA; both browse and WebFetch returned 403; landing page resolved via Wayback). 303 narratives reviewed. URL: `https://www.faa.gov/uas/resources/public_records/uas_sightings_report/FY26_Q1_UAS_Sightings.xlsx`
- **FAA UAS Sightings Report (FY25 Q4, Jul–Sep 2025)** — accessible. 531 narratives reviewed. URL: `https://www.faa.gov/uas/resources/public_records/uas_sightings_report/fy25_q4.xlsx`
- **Bard College — Drone Sightings and Close Encounters: An Analysis (Dec 2015)** — accessible (PDF) — stale: dataset ends Sept 2015; Center ceased operations spring 2020. 921 incidents (aggregate stats only). URLs: `https://dronecenter.bard.edu/projects/other-projects/drone-sightings-and-close-encounters/` + `https://dronecenter.bard.edu/files/2015/12/12-11-Drone-Sightings-and-Close-Encounters.pdf`
- **Wikipedia — List of UAV-related incidents (proxy for ASN)** — accessible. ~12 airport-relevant entries. URL: `https://en.wikipedia.org/wiki/List_of_unmanned_aerial_vehicle-related_incidents`
- **Aviation Safety Network direct DB queries** — partial — search/dblist URLs return 404; ASN does not maintain a queryable UAS-incident category. 0 incidents reviewed. URL: `https://aviation-safety.net/database/?fenq=drone`
- **Newtral — AESA Spain stats summary** — accessible. 412 incidents (Spain, 2019–Nov 2023). URL: `https://www.newtral.es/incidentes-drones-aeropuertos/20240207/`
- **El Independiente — LEMD Feb 2020 closure** — accessible. 1 LEMD event. URL: `https://www.elindependiente.com/politica/2020/02/08/la-historia-del-dron-fantasma-que-obligo-a-cerrar-barajas/`
- **Aeropuertos en Red — LEMD Feb 2020 follow-up day** — accessible. 1 LEMD event. URL: `https://www.aeropuertosenred.com/noticias/aeropuerto-barcelona/cierre-del-aeropuerto-por-drones-y-un-aterrizaje-de-emergencia-un-dia-complicado-en-para-el-aeropuerto-de-madrid-barajas/`
- **El Español — LEMD Nov 2024 closure** — accessible. 1 LEMD event. URL: `https://www.elespanol.com/madrid/sociedad/20241106/caos-barajas-avistamiento-dron-bloquea-trafico-aeropuerto-obliga-desviar-vuelos/899160658_0.html`
- **Preferente — LEMD Nov 2024 detail** — accessible. 1 LEMD event. URL: `https://www.preferente.com/noticias-de-transportes/noticias-de-aerolineas/un-dron-bloquea-el-aeropuerto-de-barajas-y-provoca-desvios-masivos-340183.html`
- **EASA Annual Safety Review 2025 (via WebSearch synopsis)** — partial — only press summary, full PDF not fetched. 21 EU-wide UAS incidents (2024). URL: `https://www.easa.europa.eu/en/document-library/general-publications/annual-safety-review-2025`

100 narratives sampled in detail from the combined FAA file (rows 0–99 of FY26 Q1).

### 2. Behavioral type distribution (FAA Jul 2025 – Dec 2025, N = 834)

FAA narratives are stylised pilot reports ("UAS reported from 3 o'clock at 4,000 feet, 8 SW airport"). Most do not describe a drone trajectory, only a point-in-time bearing. Tagging is regex-based on the summary text:

| Inferred behavior | Count | % |
|---|---|---|
| Passive transit / point sighting (default) | 779 | 93.4% |
| In airport zone (vcnty ARPT / on final / on departure / TFR / taxiing) | 15 | 1.8% |
| Pilot took evasive action | 15 | 1.8% |
| Hovering / stationary (explicit) | 5 | 0.6% |
| Drone collided with something (jet, crane, helicopter) | 11 | 1.3% |
| Multiple drones in single sighting (≥2) | ~6 | 0.7% |
| "High-speed" descriptor used | 6 | 0.7% |
| Tracking/following aircraft | 0 | 0.0% |
| Erratic / circling / loitering (explicit) | 0 | 0.0% |
| Drone climbed or descended (in narrative) | 0 | 0.0% |
| Runway/airport closure due to drone | 1 | 0.1% |
| Incident-Accident classification by FAA | 25 | 3.0% |

Bard 2015 categorisation across 921 cases: 64.5% Sightings, 35.5% Close Encounters; 28 evasive maneuvers; 158 incidents with drone-to-aircraft proximity ≤200 ft; 51 ≤50 ft.

### 3. Altitude / duration / distance patterns

**Altitude** (FAA, n=788/834 parsed): p25 1,500 ft (~457 m), median 3,000 ft (914 m), p75 6,000 ft, p90 10,000 ft, max 31,000 ft. Only 0.8% below 60 m, 3.7% in 60–150 m, 95.6% above 150 m.
**Bard 2015** (n=785): 9.8% ≤400 ft, 90.2% >400 ft; mean 3,278 ft, median 2,100 ft; mean 1,887 ft within 5 mi of an airport, 5,033 ft beyond — drones reported near airports are systematically lower.

**Distance from airport** (FAA, n=737): median 7 nm, p90 20 nm. 35% < 5 nm, 49% 5–15 nm, 16% > 15 nm. Bard: 58.8% within 5 mi, 41.2% beyond.

**Duration**: explicit duration is almost never reported in pilot narratives. The only durations we have are operational-impact durations from LEMD-style events: 30 min – 1 h 45 min closures.

**Drone-to-aircraft proximity** (Bard close encounters): mean 217 ft, median 150 ft; one in five close encounters ≤50 ft.

**Drone type** (Bard, n=340 identified): 72% multirotor, 22% fixed-wing, 5% helicopter.

### 4. Coverage of the 4 design-doc perturbations

1. **Zone violation (reroute through restricted polygon).** Strong real-world basis. 35% of FAA reports place the drone <5 nm from an airport reference; Bard puts 58.8% within 5 mi; every operationally-impactful LEMD event was a drone inside the 8 km exclusion ring. The geometry maps directly onto the perturbation.

2. **Altitude violation (±300 m shift).** Plausible but under-aggressive in the upward direction. Real anomalies skew high: median FAA altitude is 914 m, Bard median 640 m; pilots routinely report drones at 2,000–10,000 ft (600–3,000 m). A normal hobbyist drone is capped at ~120 m AGL. So the realistic anomaly is a drone climbing well above normal, not symmetric ±300 m. The downward direction is fine.

3. **Hovering (30 s, speed ≈ 0, position frozen).** Behavior class is real but the duration is short. Explicit hover narratives in FAA data describe stationary drones over stadiums, RFK, the Phoenix airport, Massachusetts (multiple at 8,500 ft) — implied minutes, not seconds. LEMD-style closures suggest sustained presence of 30–60 min. Hover-30s captures the micro-event, not the operational event.

4. **Speed spike (3× normal for 20 s).** Over-aggressive vs reality. "High-speed" appears in only 6/834 narratives. Most drones reported are slow and easy to spot; the canonical anomaly is the opposite — slowing down or stopping. 3× is racing-drone territory, not airport-incursion territory.

### 5. Missing perturbation types (real behaviors NOT in the 4)

- **Sustained loitering / drift in airport zone** (60 s – many minutes). The LEMD Feb 2020 event lasted ~50 min of suspected presence; St. Louis 2025: drone "drifting toward aircraft final approach path", forced go-around.
- **Drone on or over the active runway / taxiway at very low altitude.** O'Hare 2025 ("drone 9 o'clock while taxiing on TWY M2 at 50 ft"); Raleigh-Durham (drone over TWY C, ATC issued ground stop); Baltimore (drone crashed on TWY F/J intersection); San Diego (drone landed on parking garage near runway 27).
- **Multiple drones / swarm** (Springfield "3 UAS between 3,000–5,000 ft", Houston "4 black UAS", Massachusetts "2 large UAS hovering").
- **Drone–aircraft collision** (Quebec King Air wing strike at 1,500 ft; Texas DPS DJI Mavic 3T struck H60 tail rotor; Amazon MK30 struck crane).
- **Drone with suspended payload** (Ann Arbor: "hovering at 300 ft with object suspended 1 foot beneath").
- **Sudden descent toward final-approach corridor.** St. Louis "drifting toward final" forced an ATC-issued go-around — this is spatial intercept, not the standalone hover/zone/altitude shift.
- **Identity gap — drone broadcasts no Remote ID.** Pure layer-1, but relevant to anomaly framing.

### 6. Calibration recommendations

- **Bias the synthetic-anomaly mix toward the airport-zone class.** Make zone-violation ≈ 40% of test anomalies (matches FAA 35% / Bard 58.8%). The current uniform 25/25/25/25 split under-represents reality.
- **Replace symmetric ±300 m with asymmetric "high-altitude excursion".** Sample drone altitude shifts as +200 to +1,500 m above 120 m AGL baseline with 70% probability; ±100 m below baseline with 30% probability. The "normal" drone trajectory in training data is already low; flagging "drone goes much higher" is the realistic anomaly.
- **Lengthen hover events.** Add a sustained-loiter variant: 60–300 s at speed < 2 m/s, position σ < 30 m, plus the existing 30 s micro-hover. Bias toward 60–180 s. The 30 s case is fine for unit tests but won't catch operationally-meaningful events.
- **Soften the speed spike.** Drop to 1.5–2× for 5–10 s. Keep it but de-prioritise: ≤10% of synthetic anomalies.
- **Add two new types:** (5) Final-approach intercept: drone trajectory crosses an active arrival corridor at 50–300 m AGL within 5 km of the runway threshold. (6) Multi-drone: 2–4 simultaneous trajectories within a 1 km radius — important because real swarms are increasingly reported.
- **Co-vary altitude and distance.** Don't sample altitude independently. Use Bard's empirical fact: drones near airports (<5 nm) are reported at ≈575 m mean, but >5 nm at ≈1,535 m. Anomalies that violate this conditional distribution (e.g. low altitude far from any airport) will look right.
- **Mostly-stationary baseline.** Rotation/heading instability is rare in narratives; speed instability is rare. The cheap tells of an unauthorized drone are being in the wrong place and being there too long. Weight loss reconstruction toward position + altitude features over speed/heading.

### 7. LEMD-specific findings

- **Date: 2020-02-03, 12:17.** Two Iberia pilots reported one drone N of RWY 36R, near Paracuellos de Jarama. Guardia Civil found "ni una sola pista" — never confirmed an actual drone. **Impact:** RWY 36R closed 12:20–13:17 (57 min). 26 flights diverted to VLC/BCN/ALC/VLL/ZAZ. **Source:** El Independiente.
- **Date: 2020-02-04, ~12:30.** Two pilots reported 1–2 drones in airspace vicinity. Behavior not described. **Impact:** Departures suspended 12:30–14:15 (1 h 45 m). Only RWY 32L operating, very spaced. ~25 flights diverted. €225 k fine threatened. **Source:** Aeropuertos en Red.
- **Date: 2022-08-29, afternoon.** Drone in airport vicinity. Behavior not described. **Impact:** ~1 h disruption, 7 flights diverted. **Source:** Preferente / news round-up.
- **Date: 2023-03-26.** Drone sighted in vicinity. **Impact:** Diversions of arriving aircraft + departure delays. **Source:** Preferente.
- **Date: 2024-11-06, 19:15.** "Notification of a drone in the vicinity." Behavior not described. **Impact:** ~30 min suspension; 21 flights diverted (mostly to ALC), out of 1,034 daily ops. **Source:** El Español / Preferente.

**National context (AESA, via Newtral):** 412 drone incidents at Spanish airports between 2019 and Nov 2023; only 8 (≈2%) caused operational disruption — almost the entire impact tail is captured by the LEMD events above. A drone operating <8 km from a Spanish airport is a grave infraction (up to €225 000, 4 yr prison).

### 8. Limitations

- **FAA blocks anonymous fetches.** WebFetch and the headless browser both got HTTP 403; the file index was recovered via the Wayback Machine and the XLSX files via curl with a real-browser User-Agent + Referer. Anyone reproducing this needs to do the same.
- **FAA narratives describe pilot perception, not drone trajectory.** Behaviors like "circling", "tracking", "climbing" are essentially never tagged — they're absent from the data, not absent from reality. The 0.6% hovering rate is a lower bound on what gets written down, not on what happens.
- **Altitude bias.** FAA reports come from manned-aviation pilots, so the altitude distribution is the intersection of drone airspace and crewed airspace. It does not describe what drones do when no airliner is overhead.
- **Bard data ends Sept 2015 and the Center is dormant**; consumer-drone behavior (DJI capabilities, swarms, FPV racing) has shifted since then. Use Bard for proportions, not absolute numbers.
- **ASN has no usable UAS endpoint.** Wikipedia covers the salient incidents but is curated and Western-biased.
- **EASA 2025 report:** only the press synopsis is in scope; the full PDF was not fetched in this session.
- **LEMD reporting is journalistic.** No AENA/AESA event-level dataset was located. Altitudes, exact distances, and drone behaviors at Barajas are unknown from public sources; we have impact metadata (closure duration, divert counts) only.
- **No primary data on Spanish drone-incident geometry** (heights, paths, speeds) — confidence is low for any LEMD-specific calibration; recommendations in §6 are anchored to U.S. data.

---

## Open follow-ups (for someone, eventually)

These don't block Phase 7 but are worth knowing about:

- **AENA outreach.** Email `innovacion@aena.es` (suggested in the design doc's stretch goal section) with a request for academic access to anonymized incident data. Realistic outcome: aggregate stats; long shot: redacted incident summaries; project-changing shot: track-level data.
- **EASA Annual Safety Review 2025 full PDF.** Not fetched in this session; if a full read becomes available, update §3 with EU-wide altitude/distance distributions.
- **Aviation Safety Network UAS endpoint.** If ASN ever exposes a queryable UAS category, it would broaden the international coverage substantially.
- **Year-on-year FAA trend.** This research used 6 months of FAA data (Jul–Dec 2025). A longer window would let us check whether the 0.7% high-speed rate is stable or shifting upward as racing/FPV drones spread.

---

## Reference implementation — SADAR synthetic bench (added 2026-05-31)

A teammate shipped a parallel course project, **SADAR** (`huggingface.co/spaces/devrup404/sadar`), on the *same* data (OpenSky LEMD, ~18 days 2017–2020, ~20k trajectories) and the *same* approach (LSTM / VAE-LSTM autoencoder). Their `src/sadar/eval/synthetic.py` is a clean, working synthetic-anomaly bench. It is vendored verbatim (MIT) at **`backend/docs/ml/references/sadar_synthetic_bench.py`** so we don't depend on the Space staying up.

**Borrow the scaffold, not the parameters.** SADAR's bench is a good engineering skeleton; its anomaly *calibration* is exactly the "too easy / wrong-shaped" trap §6 above was written to avoid. Concretely:

| Element | Take it? | Why |
|---|---|---|
| `_ramp()` — perturbation ramps in mid-window | ✅ borrow | Matches our "anomaly onset partway through the window" framing. |
| `_mask_from()` onset masks as ground-truth labels | ✅ borrow | Doubles as the label for **detection latency** (median steps from onset to first threshold crossing). D-005's metric stack doesn't yet name latency — SADAR shows it's free once you have onset masks. Worth adding to our Phase 7 metrics. |
| `unscale → perturb → rescale` using the saved scaler | ✅ borrow | Correct discipline: perturb in physical units, re-apply the train-fit scaler. Mirrors our Stage-2/3 pipeline. |
| `holding_pattern()` geometry (constant-ω heading → integrated x/y) | ✅ borrow (adapt) | Cleanest piece; closest match to our **sustained-loiter** type. But add a low-speed station-keeping variant (speed<2 m/s, σ_pos<30 m), not just turn-period. |
| `build_cases()` driver shape `(kind, label, windows, mask)` | ✅ borrow | Reweight the mix per §6 (zone ~40%, speed ≤10%) and add the two missing types. |
| `altitude_anomaly()` **symmetric** ±offset | ❌ override | §6/TL;DR #1: ours is **asymmetric upward** (+200…+1500 m @70%, −100 m @30%). Their `signs = rng.choice([-1,1])` is precisely the wrong shape. |
| `speed_anomaly()` aggressive multiplicative factor | ❌ override / demote | §6: drop to 1.5–2× for 5–10 s and cap at ≤10% of the mix. SADAR runs it up to ×2.2 with equal weight. |
| Missing: **zone violation** through the restricted polygon | ➕ add | Our highest-weight type (~40%); SADAR's `route_deviation` is a generic random-bearing offset, not a polygon-aware zone breach. |
| Missing: **final-approach intercept**, **multi-drone** | ➕ add | §5 — neither exists in SADAR. |

**Net:** SADAR saves us the boilerplate (ramps, masks, scaler round-trip, the holding-pattern integration) and contributes the **detection-latency metric** idea. Our calibrated mix (§6) and the polygon/intercept/multi-drone types are the part that makes our eval a stronger claim than theirs. When Phase 7 starts, adapt `sadar_synthetic_bench.py` into `inject_anomalies(...)` applying every ❌/➕ row above, and cite both this doc and the SADAR source in the writeup Methodology.

### Feature-contract reconciliation (2026-06 — post-#22 merge, Phase 3 closed)

The table above (and `sadar_synthetic_bench.py`) is written in SADAR's feature vocabulary (`x_rel/y_rel` runway-relative metres, `sin_hdg/cos_hdg`, 7 features). **Our shipped Phase-3 contract is different** — see `backend/core/preprocessing.py`:

```
AE_FEATURES     = [lat, lon, baroaltitude, velocity, vertrate, hdg_sin, hdg_cos, onground]   # 8 features
SCALER_FEATURES = [lat, lon, baroaltitude, velocity, vertrate]                               # only these 5 are standardized
to_sequences(df, T, scaler)  →  (N, T, 8)   # T and the FITTED scaler are Phase-6 artifacts
```

What the injection code must do differently from the SADAR scaffold:

- **Position is raw `lat/lon` (degrees), not `x_rel/y_rel` (metres).** Route-deviation / zone injection specified in metres must convert metres→degrees (`Δlat ≈ m/111320`, `Δlon ≈ m/(111320·cos lat)`) **or** — preferred — bind to a runway-relative / zone-distance feature *if Phase 5 adds one from the retained `dist_to_runway_m`*. Coordinate that feature's geometry with the APW/geofence Layer-3 baseline (D-008) so injection and baseline share one definition.
- **Heading channels are `hdg_sin/hdg_cos`** (not `sin_hdg/cos_hdg`); `baroaltitude/velocity/vertrate` match.
- **`onground` is a new feature** SADAR lacks — injections must keep it consistent (e.g. an airborne hover sets `onground = 0`).
- **Scaling applies to the 5 `SCALER_FEATURES` only.** The unscale→perturb→rescale dance touches `lat, lon, baroaltitude, velocity, vertrate`; `hdg_sin/hdg_cos/onground` are perturbed in raw space (already O(1), unscaled).
- **Bind indices dynamically**, not by literal name. `sadar_synthetic_bench.py` already has `feature_indices(feature_columns, names)` — pass our `AE_FEATURES`. This survives Phase 5 reordering/adding features.
- **`T` and the fitted scaler come from Phase 6** (the train-only `.fit()` firewall). The generator runs *after* the Phase-6 split, against `to_sequences(...)` output + the fitted scaler — never `make_scaler()` (unfitted).

**Update — post-#25 (Phase 5 closed, issue #25).** The contract grew: `AE_FEATURES` is now **9** and `SCALER_FEATURES` is now **6** — Phase 5 promoted **`dist_to_runway_m`** (the nonlinear zone signal) into both. So "the 5 SCALER_FEATURES" above is now **6**. Consequences for the bench:
- `dist_to_runway_m` is **derived** (`= distance_to_closest_runway(lat, lon)`) → **recompute, never perturb** (same as `hdg_sin/hdg_cos` from `heading`). The clean way: perturb the **measured primitives** (`lat, lon, baroaltitude, velocity, vertrate, onground`, + `heading`) on the per-segment frame, call **`backend.core.features.apply_segment_derivations(seg)`** (replays `hdg_sin/cos` + `dist`), *then* window + scale — "recompute, don't perturb" becomes structural, no hand-maintained list.
- A route/zone injection that moves `lat/lon` lets `dist_to_runway_m` follow via the replay; bind the APW/geofence Layer-3 baseline + the zone injection to the same `backend.core.geo.distance_to_closest_runway`.
- **Injected timesteps set their `*_missing` masks to 0** (synthetic-but-present).
- The go-around held-aside cohort is `meta['is_go_around']` (routed out of TRAIN at the split; a real-anomaly validation cohort alongside Layer 4). See `backend/docs/ml/05-features.md`.
