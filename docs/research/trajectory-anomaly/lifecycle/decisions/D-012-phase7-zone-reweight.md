> **Post-restructure note (added when preserved into the tracked tree).** This
> decision predates the repository refactor (PR #39); the path references in the
> body below use the pre-restructure layout and are kept verbatim as an immutable
> record. Current homes: `07-eval-prep.md` → [`../07-eval-prep.md`](../07-eval-prep.md);
> `07-train.md` → [`../07-train.md`](../07-train.md); D-005/D-008/D-010/D-011 are in
> this same `decisions/` directory. The injection bench (`backend/core/inject.py`,
> `DEFAULT_MIX`, `MIX_V1_WITH_ZONE`) lived in the pre-restructure package (preserved
> via the pre-restructure tag) and is not part of the current `sadar_research` package.

---

# D-012: Re-weight `zone_violation` out of the synthetic bench for Phase-7 entry

**Phase:** eval
**Date:** 2026-06-02
**Status:** decided
**Amends:** D-005 (metric stack — what the headline synthetic AUROC means), D-008 (Layer 2
discriminative validation), D-010 (multi-detector remit split), D-011 (bench calibration).
**Supersedes for Phase 7 only:** the §6 / Phase-6 frozen mix (`MIX_V1_WITH_ZONE`, zone @ 40%).

## Context

The Phase-6 synthetic bench (`backend/core/inject.py`, "Generator A") draws anomalies from a
§6-calibrated mix where **`zone_violation` is 40%** of injections (07-eval-prep.md §6). On the
shipped LSTM-AE (`small/mean`), the per-type val AUROCs are:

| type | AE val AUROC | in AE's remit? |
|---|---|---|
| zone_violation | **0.556** (≈ chance) | **no** — APW owns it |
| altitude_high | 0.569 | partial — MSAW-adjacent |
| sustained_loiter | 0.955 | **yes** |
| final_approach_intercept | 0.790 | **yes** |
| speed_spike | 0.578 | **yes** |

At 40% weight, `zone_violation` — the AE's worst, near-chance category — is the single largest
drag on the headline mean (0.664). But under the **D-010 manned-conformance reframe** (and
`writeup/09-the-architectural-critique.md`), the model is a *behavioral conformance monitor on
cooperating manned aircraft*, and **small zone/position violations are owned by the deployed APW
(Area Proximity Warning) safety net — a comparison baseline (D-008 Layer 3), not something the AE
is responsible for.** `zone_violation` is also a **§6 pre-reframe, drone-era category**
(07-eval-prep.md §"Post-reframe reconciliation" flags that §6 predates D-010). So the AE's
near-chance zone score is **out-of-remit, not a model deficiency** — yet it dominates a metric
read as "how good is the AE."

The Phase-6 close-out (07-train.md §4b, "Phase-7 entry decision") explicitly deferred this as
"a candidate to re-weight out of the (frozen) bench before Phase 7 — a deliberate, signed-off
decision."

## Decision

For **Phase-7 entry**, **re-weight `zone_violation` out of the default injection mix.** The four
remaining DYNAMIC types — the AE's actual remit — are renormalized proportionally:

```
DEFAULT_MIX (Phase 7, D-012):           MIX_V1_WITH_ZONE (Phase 6, preserved):
  altitude_high            0.3333         zone_violation           0.40
  sustained_loiter         0.3333         altitude_high            0.20
  final_approach_intercept 0.1667         sustained_loiter         0.20
  speed_spike              0.1667         final_approach_intercept 0.10
                                          speed_spike              0.10
```

This changes the headline synthetic mean from a zone-dominated ~0.66 to a remit-aligned figure
(the test-burn number; ~0.74 projected from the per-type val AUROCs above).

## Guardrails — what makes this *not* a goalpost move

A post-hoc bench edit after seeing val results is exactly the kind of move the test-set firewall
exists to prevent. These conditions, all met, keep it honest:

1. **The decision rationale is architectural, pre-dated, and pre-registered**, not metric-driven:
   the D-010 reframe (2026-05-23) and 07-train.md §4b (2026-06-02) both named zone as out-of-AE-remit
   *before* this re-weight, and named the re-weight as a candidate. The trigger is "zone belongs to
   APW," not "removing zone raises our number."
2. **`zone_violation` is NOT deleted — it stays a first-class injectable kind** and is **still
   scored as a standalone out-of-remit diagnostic** in Phase 7 (reported in the per-type table,
   just not in the headline mix). Nothing is hidden; the reader sees the 0.556 and why it's excluded.
3. **The original mix is preserved verbatim** as `inject.MIX_V1_WITH_ZONE`, so the Phase-6 val
   bake-off (07-train.md §4) stays byte-for-byte reproducible. We did not overwrite history.
   **The Phase-6 companion notebooks (09 train, 10 SADAR, 11 loop-back, 12 density panel) were
   updated to pass `mix=MIX_V1_WITH_ZONE` explicitly** — without that, re-running them would
   silently pick up the new dynamic-only `DEFAULT_MIX` and the reproducibility claim would be
   hollow (codex review, 2026-06-02). Only the new Phase-7 eval notebook reads the new default.
4. **The deliverable was never the mean.** Per D-010 / writeup-09 the bench output is the *per-type
   AE-vs-rules table*; the writeup leads with that table, not the re-weighted mean. The mean is a
   convenience aggregate over the AE's remit, explicitly labeled as such.
5. **It does not touch the sealed test fold's firewall.** The re-weight changes which *synthetic*
   perturbations are injected at burn time; the held-out 2020 segments are unchanged. And it does
   not change the model — no tuning, no selection, happens against this bench.

## Consequences

- The Phase-7 synthetic headline (test burn) reports the remit-aligned mean over 4 dynamic types,
  with `zone_violation` shown separately as an out-of-remit diagnostic and APW named as its owner.
- **The model-selection contest (AE vs kNN) does NOT rest on this** — it is decided by
  real-anomaly PR-AUC (07-eval-prep Layer 6), where this mix plays no part. Note: kNN also beats
  the AE on the *dynamic-only* synthetic mean (≈0.80 vs ≈0.74 from §4c per-type), so the re-weight
  does not rescue the AE-vs-kNN synthetic gap — reinforcing that real anomalies, not synthetic,
  decide the track.
- D-005's "AUROC primary, target > 0.85" is now read against the remit-aligned mean; the target
  remains unmet on synthetic (the honest framing of 07-train.md "Phase-7 entry decision" stands).

## Rejected alternatives

- **Keep zone @ 40%, prose-only framing** — defensible and maximally conservative, but leaves the
  headline number actively misleading (40% of it measures a capability the AE is not built for).
- **Keep frozen bench + report a labeled zone-excluded secondary mean** (no file edit) — equivalent
  transparency, but the team chose to make the remit-aligned mix the Phase-7 default so downstream
  (test burn, writeup) reads one canonical number; the secondary-view goal is met by retaining the
  per-type zone diagnostic (guardrail #2) and `MIX_V1_WITH_ZONE` (guardrail #3).
