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
4. **Cite this document** as the source for every perturbation parameter chosen in the final code, in the writeup's Methodology section.
5. **Cite the public sources directly** in the writeup's Limitations section, so the calibration is auditable.
6. **Update `manifest.yml > gates.eval.summary`** with the final perturbation list and link back to this doc + any ADR (likely D-010) capturing the deviation from the design doc's defaults.

## TL;DR — the five highest-value changes

For fast scan when revisiting this doc later:

1. **Altitude perturbation should be asymmetric upward, not symmetric ±300m.** Real anomalies skew high — drones operating illegally near airports are systematically *above* the 120m hobbyist ceiling, not below. Median altitude in FAA narratives is 914m; Bard data shows 575m mean even within 5 nm of an airport. Symmetric ±300m is wrong-shaped.
2. **30s hover is too short.** Real operational events at LEMD lasted 30–105 minutes of presence. Add a sustained-loiter variant (60–300s) alongside the 30s micro-hover.
3. **Speed spike is over-aggressive AND over-represented.** Only 0.7% of FAA narratives use "high-speed" descriptors. 3× is racing-drone territory, not airport-incursion territory. Drop to 1.5–2× for 5–10s and reduce its share of the injection mix to ≤10%.
4. **Zone violations are under-represented.** They should be ~40% of injections (not 25%) — they match 35–58% of real reported behavior across FAA + Bard.
5. **Two missing types worth adding:** final-approach corridor intercept (drone crosses an active arrival corridor at low altitude near the runway threshold), and multi-drone swarm (2–4 simultaneous trajectories within a 1 km radius).

The single most important meta-observation: **for the 5 documented LEMD events, the public record describes only "drone in vicinity" — no trajectory detail.** AENA/AESA do not release event-level data. So all calibration of LEMD-specific perturbations remains anchored to U.S. data; this is a confidence ceiling, not a fixable gap.

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
