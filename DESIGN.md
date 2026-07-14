# DESIGN.md — LEMD Conformance Audit & Evaluation (post-hoc analyst tool)

Design system for the trajectory-anomaly **audit and frozen-model evaluation** UI (the
SADAR-merge frontend, Direction C "Forensic Dossier"). Locked via `/design-shotgun` +
`/plan-design-review` 2026-06-03 and extended for analyst evaluation 2026-07-14. The visual
reference prototypes live at `~/.gstack/projects/txema-puch-drone-ai-saturdays/designs/ranked-queue-20260603/`
(`variant-C.html` = queue, `case-C.html` = case file). This file is the token source of truth for
the React build.

## Framing (the rule everything serves)

This is a **retrospective audit** tool — completed flights reviewed after the fact — NOT a live
controller monitor. Our model scores a whole segment once; a real-time scope would be dishonest.
Every UI choice must read as "case review" or "evaluate completed observations," not "live ops."
(This is why we rejected the green-on-black radar direction.)

There are two honest product modes:

- **Audit queue:** inspect release-baked, labeled cases and their operation context.
- **Evaluate data:** apply the same frozen release model to a new analyst-supplied CSV/Parquet
  file and inspect ephemeral, unlabeled model evidence.

The second mode makes the model a product feature, but it does not turn the output into an
authorization, incident, intent, or drone-detection verdict.

## Color tokens

```
--bg:      #13161c   page (dark slate, NOT radar-green)
--panel:   #191d25   cards
--panel2:  #1c212b   inputs / nested surfaces
--edge:    #272d39   borders / rules
--ink:     #e7e3d8   primary text (paper-cream)
--mut:     #8b8e98   secondary text  verified ≥4.5:1 on --bg and --panel
--accent:  #c9a25a   gold — interactive / case numbers
--amber:   #e0a93b   severity: elevated / go-around
--red:     #e0564f   severity: high / emergency
--blue:    #6f8fb5   model reconstruction line + altitude trace
--green:   #7e9a86   normal-range / below threshold
```

Severity is encoded by color **and** a non-color cue (the label text NORMAL/GO-AROUND/EMERGENCY +
the sparkbar length + the percentile number) so it survives colorblindness.

## Severity bands (score interpretability — review fix #3)

Raw reconstruction error is meaningless alone; always pair it with the **percentile** + band:

```
pct ≥ 95  → "highly anomalous"   --red
pct ≥ 80  → "elevated"           --amber
pct ≥ 50  → "upper-normal"       --accent
else      → "normal range"       --green
```

Operating threshold (frozen, never retuned): **RE ≥ 0.222** = flagged. Served by the backend.

## Typography

- Display / headings: **Newsreader** (serif), Georgia fallback — the editorial "dossier" voice.
- Data / labels / UI chrome: bundled **Inter**, with `ui-sans-serif, system-ui` fallback.
- Numbers / ids / code: bundled **IBM Plex Mono**, with `ui-monospace, Menlo` fallback.
- Body never below 16px effective; uppercase micro-labels at 10-11px with ≥.12em tracking only for
  section headers, never running text.

## Layout

- Queue: left meta column (search + order/category/threshold filters) + a dense table-style docket.
  Columns: Case (number + timestamp) · Segment (id + aircraft) · Percentile · Score (+ sparkbar) ·
  Category stamp. Rows ~40px. **Virtualize** the full 4,480-row list in React (prototype shows top 80).
- Case file: trajectory map (1.55fr) + attribution (1fr); full-width temporal analysis; what-if panel.
- Spacing scale: 6 / 9 / 14 / 18 / 28 px. Card radius 10px, tags 3px, pills 99px.

## Information architecture

Persistent navigation separates the two evidence sources before the analyst sees a score:

```text
SADAR / LEMD CONFORMANCE
├── Audit queue                 release-baked, labeled retrospective evidence
│   └── Operation
│       └── Case file
└── Evaluate data              analyst upload, unlabeled and ephemeral
    ├── Prepare frozen model
    ├── Select CSV/Parquet
    └── Evaluation results
        └── Segment evidence   map + temporal + attribution + quality
```

The current section is always visible in the header. `Audit queue` remains the default route;
`Evaluate data` appears only when `/api/health.evaluation_enabled` is true. Case and operation
pages retain a compact return path to the audit queue. Evaluation results never link into case
or operation routes because an `evaluation_ref` is not a release case ID.

## Evaluate-data workspace

This is **app UI**, not a landing page. It uses one primary workspace and a secondary evidence
rail, not a dashboard-card mosaic.

First-screen hierarchy:

1. **Orientation:** `Evaluate new data` plus frozen release/model identity.
2. **Trust boundary:** compact, always-visible notice that processing is ephemeral, the public
   demo is unauthenticated, and confidential/proprietary uploads are prohibited.
3. **Action:** one visible file selector/drop target with CSV/Parquet, 10 MiB, 50,000-row, and
   25-segment limits; adjacent links download the exact schema and synthetic sample.

After success, the action area contracts but remains available for replacement. The results
workspace shows, in order: dataset counts and rejections; an accepted-segment selector; neutral
`above threshold` / `below threshold` model status with score and cohort percentile; data-quality
assessment; trajectory and temporal evidence; feature attribution; `Export JSON` and `Clear`.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ SADAR / LEMD CONFORMANCE       Audit queue  |  Evaluate data               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Evaluate new data                         release + model status            │
│ Public demo · ephemeral · do not upload confidential/proprietary data      │
│ ┌ Select or drop CSV/Parquet ─────────┐  Schema  Sample  Limits            │
│ └──────────────────────────────────────┘                                    │
├───────────────────────┬─────────────────────────────────────────────────────┤
│ Dataset summary       │ Segment evidence                                   │
│ accepted / rejected   │ status · score · frozen-cohort percentile          │
│ segment selector      │ quality notice                                      │
│ rejection reasons     │ trajectory map                                      │
│                       │ temporal evidence + reconstruction error             │
│ Export JSON · Clear   │ feature attribution                                 │
└───────────────────────┴─────────────────────────────────────────────────────┘
```

The file control has a persistent visible label; the drop target is an enhancement, not the
only input mechanism. It never claims that processing is private. Filenames are rendered as
text, never HTML, and are not echoed by the server.

## Required states (review fix #4)

Every list/detail view ships with: **loading** (skeleton rows), **empty** (warm message + clear-
filter action, never a bare "No results"), **error** (retry), and the populated state. The queue
empty state is implemented in the prototype.

Evaluation adds this explicit state model:

| State | What the analyst sees | Primary action |
|---|---|---|
| Capability disabled | Evaluation navigation hidden; direct route explains that this deployment is read-only | Return to audit queue |
| Model not loaded | Model status `Not prepared`; file action disabled without looking broken | Prepare model |
| Model loading | Indeterminate activity and plain `Preparing frozen model…`; no invented percentage | Continue browsing audit queue |
| Model failed | Bounded error, one retry when allowed; audit data remains usable | Retry preparation / return to queue |
| Ready / no file | Privacy notice, schema, sample, constraints, and enabled file control | Select file |
| Reading upload | Indeterminate `Reading file…`, selected filename, cancel/replace affordance | Cancel |
| Waiting for slot | `Analysis is busy` plus retry timing from `Retry-After` | Retry when available |
| Validation error | Summary beside the file control plus field/rejection details; no raw values echoed | Replace file |
| No accepted segments | Warm explanation that no LEMD-engaging assessable segments were found | Review schema / choose another file |
| Partial preprocessing | Accepted and rejected counts with bounded reason groups; only accepted segments are selectable | Inspect accepted segment |
| Success | Dataset summary, segment selector, evidence workspace, export and clear actions | Inspect / export / clear |
| Client abort | Selection returns to ready; late server response is ignored | Select another file |

Replacing or clearing data removes every result from browser state. Refreshing `/evaluate` is an
intentional empty reset, not a failed recovery. The UI never promises cancellation of Python work
that has already entered the shared inference slot.

## Evaluation journey

| Step | Analyst does | Intended feeling | Design support |
|---|---|---|---|
| 1 | Opens Evaluate data | Oriented, not surprised | Separate nav item and `post-hoc` framing |
| 2 | Checks contract/privacy | In control of risk | Short visible notice, exact schema/sample/limits |
| 3 | Prepares model | Patient but informed | Honest four-state readiness, audit remains available |
| 4 | Selects a file | Confident about compatibility | Native selector + drop target + persistent format guidance |
| 5 | Resolves validation | Able to recover | Specific bounded reasons located beside the action |
| 6 | Reviews segments | Skeptical in a productive way | Quality before model status; neutral threshold language |
| 7 | Exports or clears | In control of the evidence | Local JSON export and explicit destructive clear |

The five-second impression is `this is a serious retrospective analysis tool`; the five-minute
experience is `I can explain why a segment received this evidence`; the lasting trust signal is
that provenance, limits, quality, and uncertainty remain visible instead of being hidden behind
a verdict.

## Evaluation copy and claims

- Use `above threshold`, `below threshold`, `not assessable`, `data-quality limited`, and
  `percentile within frozen release cohort`.
- Never use uploaded-data labels such as `emergency`, `go-around`, `unauthorized`, `hostile`,
  `incident`, `drone detected`, or `confirmed anomalous`.
- Do not reuse baked-case stamps whose semantics depend on ground truth. The evaluation status
  treatment uses neutral text plus threshold position; color is secondary.
- Uploaded evidence receives no generated narrative. Show deterministic quality/model facts and
  `No generated narrative for uploaded data.`
- Every result identifies the release/model contract and makes clear that the percentile compares
  against a fixed reference cohort, not the analyst's uploaded file.

## Case-file substance (review fixes #1, #2)

- **Altitude profile** is mandatory — a go-around is a vertical maneuver; a 2D map alone hides the
  story. Stack altitude-vs-time above the RE-vs-time chart on a shared x-axis.
- **Linked scrub** — hovering the temporal charts drives a single playhead across both AND a marker
  on the trajectory, with a readout (step · altitude · RE). This is the core analyst interaction.
- Deviation steps (per-step RE ≥ step-threshold) are marked on the trajectory in --amber.

## Accessibility (review fix #5 — carry into React)

- Verify all text ≥ WCAG AA (4.5:1); `--mut` on `--bg` is the one to check first.
- SVG charts need a text/data-table fallback for screen readers.
- Full keyboard nav: queue rows focusable, Enter opens the case, Esc returns.
- Touch targets ≥ 44px if a mobile pass is ever in scope (currently desktop-only — explicit).

For `/evaluate` specifically: file selection works without drag-and-drop; preparation, retry,
segment selection, export, and clear are keyboard reachable; status transitions use an ARIA live
region without repeatedly announcing polling; validation summaries receive focus after failure;
the active segment is programmatically exposed; and clearing results requires an explicit button,
not an icon-only control.

## Viewport behavior

- **≥1440 px:** 320 px dataset/segment rail plus the flexible evidence workspace shown above.
- **1024–1439 px:** 260 px rail; map and temporal panels stack within the evidence column while
  retaining the segment selector and status above them.
- **<1024 px:** do not compress the forensic workspace into an unusable mobile stack. Show a
  concise `Desktop workspace required` state with the privacy notice and a route back to the
  audit queue. File upload/evaluation is disabled at this viewport for this release.

## Out of scope (deliberately)

Mobile evaluation workflow (desktop analyst tool for the course demo); real-time/streaming views
(model is whole-segment); theming/light mode; arbitrary schema mapping; server-side evaluation
history; shareable uploaded-result URLs; generated narratives for uploaded evidence.
