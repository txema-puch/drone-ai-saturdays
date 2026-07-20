# D-014 — First-T window truncation inflates the RE of long arrivals (finding + demo mitigation)

**Status:** decided
**Date:** 2026-06-04
**Phase:** train/eval (Phase 6/7) — finding; deploy (SADAR-merge) — mitigation
**Affects:** the deployment demo (SADAR-merge queue/case UI), the writeup limitations section, and a future-cycle Phase-3 windowing revisit. **Does NOT change** the Phase-6 model or the Phase-7 numbers.

**Future-work tracking:** consolidated as PW-001 through PW-004 in
[`../pending-work.md`](../../../../archive-manifest.yml). The current iteration is closed with the model
unchanged. Phase-7 provenance has since been reconciled in [`../07-eval.md`](../07-eval.md);
any redesigned pipeline still requires a fresh untouched holdout.

## Context

Surfaced while reviewing the SADAR-merge analyst-triage UI: the top of the ranked anomaly queue was dominated by flights that read as "highly anomalous" but are plainly **normal LEMD arrivals shown 75–200 km from the airport at cruise altitude**. Example: `345051_1580731490#1` is a real arrival that touches the runway (dist→0) at step **401 of 402**, but the case file showed a straight descending cruise line far from LEMD with every step flagged.

Root cause is the windowing contract, not the data gate or the UI:

- `preprocessing.to_sequences` keeps the **first T rows** of each segment (`feats = feats[:T]`, T=260 ≈ 43 min at the 10 s grid). Segments longer than T have their **tail truncated** before scoring.
- The LEMD-operation gate (Filter D, [D-010]) is **per-trajectory** — a flight qualifies if *any* observation engages LEMD. For a long arrival that observation is the terminal approach, at the *end*. First-T truncation therefore keeps the **cruise/descent entry** (off-distribution) and discards the informative terminal phase.
- Cruise-entry prefixes are rare in TRAIN-normal (only 4.9% of train segments exceed T), so the AE reconstructs them poorly → high RE → they pile up at the top of the queue.

## Evidence

Length: T=260 is ≈ the 95th percentile of segment length (p95=256, p99=315). Truncation rate by fold:

| Fold | truncated (>260) |
|---|---|
| train | 4.9% |
| val | 3.7% |
| test | 3.3% (143) |
| **held-aside anomalies** | **9.5% (66)** |

Truncation inflates the score regardless of label — test-normal mean RE **0.418 truncated vs 0.104 non-truncated** (4×); score↔length r=0.42. It pollutes the queue head: **50% of the top-20, 32% of the top-50** scored segments are truncated, not anomalies.

**The decisive check — is the Phase-7 real-anomaly signal a length artifact?** No:

| Cohort | real-anomaly AUROC |
|---|---|
| All segments | 0.666 (= reported 0.667) |
| **Non-truncated only** | **0.672** |
| Truncated only | 0.364 |

Removing truncation **does not help the anomalies — it marginally improves the metric** (0.666 → 0.672). If the AE were covertly detecting "long flight," stripping truncation would collapse the separation; it does the opposite. Held-aside anomalies being more truncated (9.5% vs 3.3%) is a real confound but it **depresses** the metric (truncated normals are false positives that drag ROC down), so the headline 0.667 is genuine and if anything conservative. Within the truncated subgroup anomalies don't separate (0.364), but it is tiny (17 anomalies) and pulls down, not up.

## Decision

1. **Do NOT change T or the windowing now.** The model and Phase-7 are vindicated; altering the window would re-open the eval gate and change writeup ch.11 for no correctness gain. The SADAR-merge is a deployment change, not a model change.
2. **Demo mitigation (deployment-only):** the precompute bakes `n_steps` + `truncated` (`len > T`) per queue entry and case. The queue defaults to a **"Terminal-area only"** filter that hides truncated long arrivals (disclosed count + one-click "Include truncated"); a truncated case file shows a **banner** explaining the terminal phase was not scored. Honest and reversible — the scored population is unchanged, only annotated.

   **Cross-airport gate over-admission ([D-010] precision limitation).** A third "why is this here" class, distinct from the two above and NOT a viz artifact: some queue-topping "normals" are arrivals to **neighboring Madrid airfields** — Cuatro Vientos (LECU, ~13 km), Getafe (LEGT, ~17 km), Torrejón (LETO, ~12 km) — that clip within 10 km of a LEMD runway en route and so pass Filter D's proximity gate, but never land at LEMD. Verified: `34508c_1580746690#1` touches down 0.9 km from LECU; `484f18_1582571920#2` is on approach to LETO (its track ends 9.6 km short, low-altitude ADS-B coverage loss). Magnitude is small but top-concentrated: ~9 segments (0.2%) clearly terminate at a neighbor field, 7 of 9 at ≥95th percentile. The AE correctly flags them as non-conforming to LEMD behaviour; like truncation they are false-positive normals that *depress* the real-anomaly ROC, so Phase-7 is unaffected. Demo handling: the case-file map draws faint **neighbor-airfield reference markers** (LECU/LEGT/LETO) at their real coords, so a flight landing at Cuatro Vientos reads as exactly that rather than an unexplained anomaly — no brittle filter (the clean signal is only ~9 segments; coverage-loss cases are ambiguous). A tighter gate (require LEMD touchdown / runway-aligned approach cone / exclude trajectories terminating nearer a neighbor field) is a future-cycle Filter-D refinement.

   **Map legibility (same user-facing confusion, distinct root cause).** Reviewing the above surfaced a *second* "why is this far from LEMD" reaction on NON-truncated segments — verified spurious: every test segment's closest approach is ≤10 km (median 0.9, p95 3.3, max 9.0). The cause was the trajectory map auto-scaling with no distance reference (LEMD pinned to a corner makes a normal 0–10 km operation look thrown out). Fix: the case-file map now draws **LEMD distance rings (5/10/20 km) + a km scale bar**, so true distance is readable. Additionally, ADS-B gaps split one flight into sibling segments (`#2`, `#3`, …; 10.7% of segments are `#2`+), each scored independently; the map now overlays the **full trajectory as faint context** (`context_path`, all siblings) behind the scored segment, so a near-runway fragment reads as the tail of a complete approach rather than a lonely diagonal. Display-only, no scoring/leakage impact.
3. **Future-cycle candidate (not now):** revisit windowing for long arrivals — an **approach-anchored** or **last-T** window (or raising T) would keep the terminal phase. Expected to both clean the demo queue *and* nudge the real-anomaly ROC up (fewer false-positive truncated normals). This is a Phase-3/6 change for a later cycle, scoped behind a fresh split + re-eval.

## Update 2026-06-04 — fourth artifact class, filter consolidation, and a model-redo recommendation

**Fourth class — altitude data glitches (no relative-jump cleaning rule).** Reviewing an "overflight" case (`3c6487_1583753730#2`: cruises at 11,582 m yet reads 0.8 km from a threshold — `dist_to_runway_m` is horizontal/altitude-blind) surfaced impossible single-step altitude jumps: `647 m → 11,582 m in one 10 s step, no time gap` (>1000 m/s). **27.9 % of test segments have a >1500 m single-step baroaltitude jump** (corr with score 0.14). Cause: Phase-3 cleaning (D-010) has an **absolute** physical-bounds rule but **no relative rate-of-change rule** — both 647 m and 11,582 m are individually in-range, so the jump between them never trips it. The AE flags these (a data glitch, not behaviour).

**Consolidation.** Truncation (#1), neighbour-field traffic (#2/cross-airport), overflights (#3), and glitch-overflights (#4) are one family: *passed Filter D's 10 km gate but is not a genuine LEMD terminal operation*. The precompute now bakes a single conjunctive **`terminal_op`** flag — does the **scored window** contain a step that is both low and close (`dist_to_runway_m < 5 km` AND `baroaltitude < 1500 m`)? The queue defaults to **"LEMD operations only"** (hides the 149/4480 ≈ 3.3 % non-terminal, disclosed + one-click "Include gate artifacts"); a non-terminal case file shows a banner naming the likely cause. Verified: keeps 192/195 held-aside anomalies, removes 16 of the top-50 artifacts, eval AUROC 0.666 → 0.671 (excl. non-terminal normals — conservative, consistent with the 0.673 above). This **replaces** the truncation-only filter. Display/annotation only; the scored population and Phase-7 numbers are unchanged.

**Would a correct gate raise ROC?** Yes, in two parts. Eval-cleaning (same model, cleaner test-normals) is **measured** at +0.005–0.007 (0.666 → ~0.671–0.673) — modest, because AUROC is rank-based and contamination is only ~3.3 %. Train-cleaning (a model that never trains on overflights/neighbour/glitch normals → tighter learned-normal manifold) is **plausibly the larger win but unmeasured** — it needs a retrain.

**RECOMMENDATION — redo the model with these findings (future cycle).** This deployment merge surfaced that an unsupervised AE on gated OpenSky data substantially detects *"not a clean LEMD terminal operation"* alongside genuine behavioural anomalies. The next modeling cycle should: (a) tighten **Filter D** to a conjunctive low-AND-close gate (require an actual LEMD terminal phase, not mere 10 km proximity), excluding neighbour-field + overflight traffic at the data stage; (b) add a **relative rate-of-change / jump** outlier rule to Phase-3 cleaning (vertical-rate, groundspeed, position) to catch glitches the absolute-bounds rule misses; (c) revisit **windowing for long arrivals** (approach-anchored or last-T) so the terminal phase is scored; then **retrain + re-eval** on the cleaned population. Expectation: a cleaner queue *and* a higher, more honest real-anomaly ROC. Tracked here until promoted to a Phase-3/6 cycle ADR.

## Consequences

- The deployed tool no longer leads with gate artifacts (truncation, neighbour-field, overflight, glitch), while still letting an analyst inspect them on demand (scope toggle + per-case banner + distance rings + airfield markers).
- The writeup gains a precise, quantified set of limitations (with the 0.666→0.673 conservative-direction vindication) rather than a vague caveat — to be written up in the pending writeup stage.
- A concrete, prioritized improvement plan (gate + cleaning + windowing → retrain) is on record for the next data/modeling cycle.

[D-010]: ./D-010-filter-d-and-multi-detector-preprocessing.md
