# Dataset #6 — In-Flight Emergencies as External Validation (Layer 4)

**Status**: exploration / acquisition spec. Data not yet pulled. Inspection is Phase-4-legal (see Firewall); scoring is **sealed until Phase 7**.
**Created**: 2026-06-01.
**Owner of the eventual analysis**: writeup owner (Layer 4 + Layer 5).
**Cross-references**:
- D-008 (`docs/research/trajectory-anomaly/lifecycle/decisions/D-008-output-validation-layers.md`) — defines the 5-layer validation stack; this is Layer 4.
- `docs/research/trajectory-anomaly/lifecycle/07-eval-prep.md` > "Layer 4 — external validation via real emergencies (Dataset #6)" — the execution protocol + pre-committed finding template.
- the archived architectural-critique draft listed in `docs/archive-manifest.yml` > "External validation" — the narrative slot this fills (`[N]`, `[X]`, `[K]` placeholders).
- Cycle-3 acquisition pattern: `backend/research/src/sadar_research/trajectory_anomaly/data/download.py` (Dataset #1, the *normal* training corpus) and D-007.

---

## 0. Why this dataset, in one paragraph

The autoencoder outputs a reconstruction error per trajectory. That number is meaningless until external evidence grounds it (the "imagination-leakage" risk from Phase 1: synthetic AUROC only proves the model catches anomalies *we hand-designed*). Dataset #6 is the closest publicly available proxy for ground-truth anomalies in cooperative-aviation airspace: real flights a pilot declared an emergency on, by squawking 7700. ATC, dispatch and emergency services treated them as significant. **The model never trains on them, never sees them injected, and is never told they exist until Phase 7.** Scoring them then is the one test that isn't circular with our own bench.

## 1. What it actually is (verified 2026-06-01)

| Property | Value |
|---|---|
| Name | "Reference datasets for in-flight emergency situations" (Olive et al.) |
| Publication | *OpenSky Report 2020: Analysing in-flight emergencies using big data*, DASC 2020 |
| Access (preferred) | `from traffic.data.datasets import squawk7700` (traffic library) — auto-downloads from Zenodo |
| Access (direct) | Zenodo record `10.5281/zenodo.3937483` → https://zenodo.org/records/3937483 |
| Total flights | **832** unique 7700-squawk trajectories (global) |
| Time span | 2018-01-01 → 2020-01-29 |
| Resolution | **1 s** (note: our training corpus is 10 s — see §4 resampling) |
| Per-flight metadata | `callsign`, `number`, `icao24`, `registration`, `typecode`, `origin`, `destination`, `landing`, `diverted`, plus emergency-category fields from Aviation Herald (`avh_problem`, `avh_result`, `avh_fueldump`) and Twitter (`tweet_problem`, `tweet_result`, `tweet_fueldump`) |
| Emergency categories | engine, medical, cabin pressure, cracked windshield, fuel leak, hydraulics, landing gear, brakes, door, others |

The rich metadata is a gift: we can filter to LEMD by **airport ICAO code** (not just a bbox) and **stratify by emergency type** (§5) — neither was possible for the normal corpus.

Sources: [traffic-viz squawk7700 gallery](https://traffic-viz.github.io/gallery/squawk7700.html) · [Zenodo 3937483](https://zenodo.org/records/3937483) · [OpenSky Report 2020 (PDF)](http://www.cs.ox.ac.uk/files/12039/OpenSky%20Report%202020.pdf) · [OpenSky scientific datasets index](https://opensky-network.org/data/scientific)

## 2. The firewall posture (non-negotiable)

Same discipline as the test set. Per D-008 and the test-set firewall in `manifest.yml`:

- **Phase 4 (now / allowed):** *inspect* — count LEMD-area flights, tabulate emergency types, look at altitude/approach profiles, sanity-check the LEMD filter. This is EDA on an external set, not model evaluation. Document the inspection under the Phase 4 EDA artifact.
- **Phase 6 (sealed):** Dataset #6 is **not** used in any training, validation, threshold selection, or AE-vs-IF model selection. Touching it there contaminates the only un-circular external check we have.
- **Phase 7 (execution, after model selection per D-006):** score every LEMD-area trajectory once with the locked model; compute the percentile + Mann-Whitney U per the 07-eval-prep protocol; fill the pre-committed finding template.

> If anyone scores Dataset #6 before the model is locked, the Layer-4 result is burned — treat it like the test set.

## 3. LEMD-association filter — and why NOT to reuse Filter B/D

> **⚠️ Superseded for Layer-4 scoreability (see §9).** The trajectory pass (2026-06-01) showed airport-code association is the *wrong* filter for Layer 4: Dataset #6 stores the emergency-window segment, which is often far from the metadata destination, so 5 of the 6 airport-code flights have **zero** trajectory points near LEMD. Use the **trajectory radius** (§9) as the authoritative Layer-4 filter; airport code is only a first cut.

The normal corpus used a 200 km bbox + **Filter B** (`min_dist<10km AND min_alt<3km` per trajectory) / **Filter D** (the three-criterion engagement gate, D-010) to keep only flights that *operated* at LEMD. **Do not apply Filter B/D to the emergency set.** Those gates select for *normal-LEMD-operation geometry* — applying them to emergencies would keep only emergencies that look like normal approaches, which is exactly the circularity Layer 4 exists to avoid (you'd discard the trajectory-anomalous emergencies, the ones that matter).

Instead, associate by **airport code**, which the metadata makes precise:

```python
from traffic.data.datasets import squawk7700
LEMD = {"LEMD"}  # ICAO; Madrid-Barajas
lemd_assoc = squawk7700.query(
    "origin in @LEMD or destination in @LEMD or landing in @LEMD or diverted in @LEMD"
)
```

Then **cross-check against the 200 km bbox** (the same geographic window as cycle 3) to (a) catch flights whose emergency happened in the LEMD TMA even if origin/dest is elsewhere, and (b) confirm the trajectory actually has points in our area of competence. Keep the union of "airport-code associated" and "has ≥ N points inside the bbox"; record both counts.

**Stratify, don't just pool, by relationship to LEMD:**
- **Arriving / landing at LEMD** — comparable geometry to the training approach manifold; the fair test.
- **Departing LEMD** — comparable to the departure manifold.
- **Diverted *to* LEMD** — unusual approach (off nominal STAR), expected to score higher.
- **Overflew / declared near LEMD but landed elsewhere** — partial trajectory in-area; interpret with care.

## 4. Matching the model's input representation (the offline/online check in miniature)

Dataset #6 trajectories must pass through the **exact same preprocessing pipeline** as training, with the **train-fit scaler** — otherwise the reconstruction errors aren't comparable. Concretely:

1. **Resample 1 s → 10 s** to match the training grid (cycle 3 is 10 s). Do this *before* windowing.
2. Apply the same feature construction: runway-relative coords (pyproj), heading `(sin, cos)`, the same feature column order, the same window length/stride (per the Phase-3 `preprocessing` config once locked).
3. Apply the **saved train scaler** (`transform`, never `fit`).
4. Apply the same Stage-1 physical-bounds rule + Stage-2 imputation from the multi-detector pipeline (D-010) so the AE sees inputs of the same quality.

If the representation diverges, a "high" emergency score could be a preprocessing artifact, not a real signal. This is the same offline/online-consistency discipline that protects the test set.

## 5. The interpretation refinement that makes the result un-ambiguous

**The key threat to validity:** most 7700 emergencies are *manned commercial aircraft that keep flying a normal approach* — a medical emergency often flies a textbook STAR and just squawks 7700 for priority handling. Its *trajectory* is normal; only its *transponder code* is anomalous. Our model scores trajectory shape. So a low Layer-4 percentile would be **ambiguous**: weak model, or emergencies that simply aren't trajectory-anomalies?

Dataset #6's emergency-category metadata dissolves the ambiguity. **Pre-commit to a per-category expectation, before scoring** (mirrors the per-type pre-commit in 09):

| Emergency category | Expected trajectory signature | Expected AE score |
|---|---|---|
| Fuel dump / fuel leak (`*_fueldump`) | Holding/racetrack patterns to burn fuel | **High** — sequence-shaped, like our "holding/loiter" injection |
| Diversion (`diverted` set) | Off-nominal route, unusual approach | **High** |
| Engine / hydraulics / gear / brakes | Often non-standard approach, possible holding | **Medium–high** |
| Medical, with normal `landing` | Normal STAR, priority only | **~Normal** (correctly) |
| Cabin pressure | Rapid descent | **High on altitude/vertrate** |

This converts Layer 4 from a single ambiguous percentile into a **structured claim**: *"the model scores the trajectory-anomalous emergency categories (fuel dumps, diversions, rapid descents) high, and the trajectory-normal ones (uncomplicated medical) near normal — which is the correct behavior for a trajectory-shape detector."* That is a far stronger and more honest finding than "emergencies scored at the Nth percentile" pooled, and it ties directly to the architectural thesis (AE earns its keep on sequence-shaped anomalies).

Report the pooled percentile + Mann-Whitney U (per 07-eval-prep) **and** the per-category breakdown. The pooled number is the headline the template needs; the breakdown is what defends it.

## 6. Expected N and fallbacks

> **Resolved 2026-06-01 (see §9 + D-008 Amendment 2).** The estimate below was the pre-inspection guess. Reality: the scoreable in-range set is **~7 flights (≈4 in the TMA, 1 close-in)**, and the **Western-Europe fallback is rejected** (it re-imports the cross-airport confound). Layer 4 is therefore a **case study (BCS63A)**, and the quantitative external-grounding role moves to D-011's real-derived injections + Layer 5. The paragraph below is kept for the record.

832 flights globally; the LEMD-associated subset will be small. Europe is well-covered by OpenSky, and LEMD is Europe's 4th-busiest hub, so expect the upper end of the 07-eval-prep estimate — realistically **~10–40** flights, fewer once split by category. This supports a **small-N non-parametric** signal (percentile + Mann-Whitney U with reported N), **not** a headline AUROC. Report CIs; do not spin small N as definitive.

- **If LEMD-direct N is too small to stratify:** report pooled + note categories qualitatively.
- ~~**Fallback if N ≈ 0:** widen to the Western-European subset~~ — **rejected**, see above.

## 7. Concrete next actions

**Phase 4 (do now, firewall-safe):**
- [ ] Add `traffic` to deps (`uv add traffic`) — confirm it isn't already pulled transitively.
- [ ] `from traffic.data.datasets import squawk7700`; pull, cache locally (note: downloads from Zenodo).
- [ ] Build the LEMD-association filter (§3); record N for airport-code, bbox, and union.
- [ ] Tabulate emergency categories for the LEMD subset; map to the §5 expectation table.
- [ ] Plot altitude/approach profiles for a handful; sanity-check they're in our area of competence.
- [ ] Document counts + category table in the Phase 4 EDA artifact (`04-eda.md`), link back here.

**Phase 6 (do nothing):** leave Dataset #6 untouched. Add a one-line reminder at the Phase 6 entry gate.

**Phase 7 (sealed until then):**
- [ ] Run the locked model over the LEMD subset through the §4 pipeline, once.
- [ ] Pooled percentile + Mann-Whitney U (07-eval-prep template) + the §5 per-category breakdown.
- [ ] Fill `[N]`, `[X]`, `[K]` in 09; update `manifest.yml > gates.eval.summary`.

## 8. Open questions to resolve before Phase 7

> **Update 2026-06-01 — trajectory schema verified.** Read the `squawk7700_trajectories` parquet (Zenodo 3937483): 4,344,359 rows, 11 cols — `timestamp` (ms, UTC), `altitude`, `callsign`, `flight_id`, `groundspeed`, `icao24`, `latitude`, `longitude`, **`squawk` (string, per-timestamp)**, `track`, `vertical_rate`. `AFR11DN_20190816` transitions `1000`→`7700`, confirming the emergency **onset is recoverable per-timestamp**. This unblocks the onset-anchored maneuver-transplant idea (the ~826 non-LEMD flights as real injection sources) — see **D-011**. Note for our pipeline: a single `altitude` column (no baro/geo split), 1 s resolution (resample to 10 s).

1. **Runway-relative projection for diversions:** our projection is anchored to a LEMD runway ref. Flights diverted *to* LEMD on a non-nominal heading are still valid; flights that merely overflew the bbox may need a different anchor or exclusion. Decide the inclusion rule when N is known.
2. **typecode filtering:** the training corpus is dominated by commercial jets. If a 7700 flight is a type absent from training (e.g. GA, military), a high score may reflect type-novelty, not emergency behavior. Consider reporting with/without type-matched subset.
3. **Partial trajectories:** OpenSky coverage gaps are larger for some emergency flights. Apply the same `max_gap` / `min_points` cleaning as training; record how many emergency flights are dropped by it (and whether that biases the sample).

## 9. Trajectory-pass results (2026-06-01) — airport-code filter superseded

Ran the radius filter on the actual trajectory parquet (haversine to LEMD ref `40.4936 / -3.5668`, all 832 flights, 4.34M points). **Critical finding: Dataset #6 trajectories are emergency-window segments, frequently far from the metadata destination.** Of the 6 airport-code-LEMD flights, only **one** has trajectory points near LEMD; the other five have **zero** points within 200 km — the emergency happened en route or at the diversion field, hundreds-to-thousands of km away:

| flight_id | min dist to LEMD | pts <200km | note |
|---|---|---|---|
| BCS63A_20190829 | **2.9 km** | 1873 | departed LEMD, returned — **turn-back** |
| AFR11DN_20190816 | 537 km | 0 | dest LEMD but diverted to LFBD |
| EZY42LB_20181213 | 1063 km | 0 | |
| IBK6241_20180616 | 1339 km | 0 | |
| LAN706_20180918 | 5980 km | 0 | emergency near SCEL |
| LCO1501_20191208 | 9710 km | 0 | emergency near origin |

So airport-code association selects flights *intended* for LEMD, **not** flights *flying near* LEMD during the emergency — useless for a LEMD-anchored scorer (5 of 6 have nothing in range). **The authoritative Layer-4 filter is the trajectory radius**, which gives a near-disjoint, more honest set:

| radius | flights |
|---|---|
| < 10 km | 1 |
| < 30 km | 2 |
| < 50 km | 4 |
| < 100 km | 7 |
| < 200 km | 7 |

**Scoreable Layer-4 set ≈ 7 flights within 200 km; only ~4 reach the TMA (<50 km); only BCS63A is a genuine close-in LEMD operation** (a turn-back, 1,239 pts <50 km). The three TMA-transit recoveries are `JAF20K_20190919` (16.9 km, B738), `TOM517_20190705` (34.4 km, A320, **engine**, diverted LFBD), `BLX236_20180201` (39.6 km, B738) — all passing near LEMD en route/diverting, not operating at it.

**Consequences (this supersedes the N=6 headline in §6 and notebook 08 for Layer-4 purposes):**

- **N is even smaller once you require a scoreable trajectory: ~7 (within 200 km), ~4 TMA, 1 close-in.** Layer 4 is a handful of **per-flight case studies + Mann-Whitney**, not AUROC. **BCS63A is the qualitative centerpiece** (a real LEMD turn-back the model never saw).
- **The Western-Europe fallback is REJECTED (decided 2026-06-01, D-008 Amendment 2).** Widening to other EU hubs re-imports the cross-airport confound (a LEMD-only model flags any non-LEMD flight for *being non-LEMD*, not for the emergency) — the same expansion D-008 Alternative #2 already rejected. So Layer 4 stays **small-N by design**: a case study, not a statistical test.
- **The §8 q1 projection concern is now concrete:** only BCS63A is close enough for the runway-relative projection to be meaningful; the 50–200 km transit flights sit at the edge of the model's spatial domain — interpret their scores accordingly (likely trivially high for "wrong place", not for "emergency").
- **Firewall split (D-011) is refined:** the sealed LEMD-area set = **trajectory radius < 200 km (these 7)**, NOT the airport-code 6. Everything else (825) is injection-source fuel. The radius criterion, not airport code, draws the firewall line.
