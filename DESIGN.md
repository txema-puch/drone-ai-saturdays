# DESIGN.md — LEMD Conformance Audit (post-hoc analyst tool)

Design system for the trajectory-anomaly **audit** UI (the SADAR-merge frontend, Direction C
"Forensic Dossier"). Locked via `/design-shotgun` + `/plan-design-review` 2026-06-03. The visual
reference prototypes live at `~/.gstack/projects/txema-puch-drone-ai-saturdays/designs/ranked-queue-20260603/`
(`variant-C.html` = queue, `case-C.html` = case file). This file is the token source of truth for
the React build.

## Framing (the rule everything serves)

This is a **retrospective audit** tool — completed flights reviewed after the fact — NOT a live
controller monitor. Our model scores a whole segment once; a real-time scope would be dishonest.
Every UI choice must read as "case review," not "live ops." (This is why we rejected the green-on-
black radar direction.)

## Color tokens

```
--bg:      #13161c   page (dark slate, NOT radar-green)
--panel:   #191d25   cards
--panel2:  #1c212b   inputs / nested surfaces
--edge:    #272d39   borders / rules
--ink:     #e7e3d8   primary text (paper-cream)
--mut:     #8b8e98   secondary text  ⚠ verify ≥4.5:1 on --bg before ship (a11y)
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
- Data / labels / UI chrome: system sans (`ui-sans-serif, system-ui`). NOTE: pick a real sans
  (Inter/IBM Plex Sans) for the React build — system-ui as the primary face is an a11y/quality smell.
- Numbers / ids / code: `ui-monospace, Menlo`.
- Body never below 16px effective; uppercase micro-labels at 10-11px with ≥.12em tracking only for
  section headers, never running text.

## Layout

- Queue: left meta column (search + order/category/threshold filters) + a dense table-style docket.
  Columns: Case (number + timestamp) · Segment (id + aircraft) · Percentile · Score (+ sparkbar) ·
  Category stamp. Rows ~40px. **Virtualize** the full 4,480-row list in React (prototype shows top 80).
- Case file: trajectory map (1.55fr) + attribution (1fr); full-width temporal analysis; what-if panel.
- Spacing scale: 6 / 9 / 14 / 18 / 28 px. Card radius 10px, tags 3px, pills 99px.

## Required states (review fix #4)

Every list/detail view ships with: **loading** (skeleton rows), **empty** (warm message + clear-
filter action, never a bare "No results"), **error** (retry), and the populated state. The queue
empty state is implemented in the prototype.

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

## Out of scope (deliberately)

Mobile/responsive (desktop analyst tool for the course demo); real-time/streaming views (model is
whole-segment); theming/light mode.
