# SADAR Analyst Console design system

Source of truth for the React approach-evidence interface. The console is a retrospective research
and labeling tool, not a live monitor or operational safety dashboard.

## Product language

- Lead with `review required`, `partial observation`, `criteria observed`, or `not assessable`.
- Say `approach attempt`, `observed criterion`, `ground track`, and `barometric-path proxy`.
- Never say the console detected an emergency, certified stability, inferred intent, or proved a
  safety event.
- Always expose missing context and data-quality reasons beside behavioral evidence.

## Information architecture

```text
SADAR Analyst Console
├── Attempts (default)
│   ├── cohort/status summary
│   ├── status, direction, criterion, outcome and quality filters
│   └── dense attempt records
├── Attempt dossier
│   ├── plain-language status and runway inference
│   ├── synchronized runway-relative map and timeline
│   ├── criterion evidence spans
│   ├── quality, missing context and provenance
│   └── operation grouping
└── Evaluate data
    ├── sample/template and privacy limits
    ├── bounded CSV/Parquet upload
    └── ephemeral results in the same vocabulary
```

The first viewport answers: what cohort is loaded, which attempts need review, and why. Numerical
evidence supports those answers; no opaque model score ranks the queue.

## Visual tokens

```css
--bg: #13161c;
--panel: #191d25;
--panel-2: #1c212b;
--edge: #2b313d;
--ink: #e7e3d8;
--muted: #9b9da6;
--accent: #c9a25a;
--review: #e0564f;
--partial: #e0a93b;
--observed: #8fa395;
--unavailable: #778294;
```

Color never carries status alone. Pair it with explicit text and a stable icon/border treatment.
Use Newsreader for display headings, Inter for interface text, and IBM Plex Mono for identifiers,
timestamps and measured values. Body text is at least 16 px with 4.5:1 contrast.

## Layout and interaction

- Dense records use spacing and typography rather than boxed-card grids.
- Attempt dossier is the primary detail unit; operation grouping is secondary.
- Map and timeline share selection state. Every graphical mark has a textual criterion/timestamp
  equivalent.
- Partial and unavailable evidence remain visible and explain what is missing.
- Upload errors preserve the chosen file for retry and link summary errors to field details.
- Loading preserves layout; empty states provide the next valid action; errors retain filters.
- URL query state preserves navigation and filters across reloads.

At 1200 px and wider, use workspace plus context rail. At 768–1199 px, move the rail below. Below
768 px, turn table rows into labeled records without hiding evidence. Touch targets are at least
44 px, focus is visible, reduced motion is respected, and status is announced as text.

## Qualification boundary

The sealed candidate missed its retention target and has no independent precision estimate. The
UI must keep that limitation visible in product-level explanatory copy. It may help analysts
inspect and label evidence; it must not visually imitate a certified alerting system.
