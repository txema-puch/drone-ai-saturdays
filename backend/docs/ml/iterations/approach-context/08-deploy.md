# Phase 8 — Research deployment

## Candidate contract

The local immutable schema-v3 candidate is release `491f81fb1d896b0d793e` with:

- engine `approach_context_v1`;
- reference digest `68ea1a974a077e0b2ef8322564d7799c5fd52cbd21db42b8d5bf1badad57d328`;
- context-source contract digest
  `eef2a7a32ee55ee079d4263dc5c7eb339aa250837256c2e00325b5d5b401402e`;
- 388 newer-source attempts: 124 not assessable, 163 partial, 51 criteria observed, and
  50 review required;
- 31.96% abstention and 18.94% review rate among assessable attempts.

The release contains precomputed contextual evidence but no NOAA or OpenSky source databases.
New uploads use the same engine when optional QNH, wind, and type fields are supplied; missing
context follows explicit fallback. Files are evaluated ephemerally and are not intentionally
retained.

## Allowed and blocked uses

Allowed: inspect evidence, test the analyst workflow, export review packets, and collect labels.

Blocked: operational monitoring, emergency detection, stabilized-approach certification, ATC
decision support, safety-performance claims, or claims that context improves accuracy.

## Publication record

Release `df22ce72488273f28c8a` was published to `Txemapuch/sadar-demo-release` on 2026-07-15,
then superseded before deployment when final red-team review found a prompt re-approach boundary
defect. It remains immutable provenance but must not be deployed.

Corrected release `491f81fb1d896b0d793e` was published at immutable revision
`db1a1a9232b3b96276a169a070852f619eec7c21` with archive SHA-256
`1f135728a0c235c245b5107a509cb73f1757ac4ced7346f123a1ea70a732c093`. Both the publisher and
the independent CI fetch path anonymously installed and strictly validated that release.

## Deployment record

The research candidate was deployed on Fly.io on 2026-07-15 after PR #34 merged into `develop`.
UI follow-ups #35 and #36 added scroll-persistent analyst context and keyboard-scrollable evidence
rails before the final rollout. Fly release v3 serves image
`deployment-01KXK13NEF7M109WK0W1KF9Y4C` from source commit `ad4fab9` at
`https://sadar-analyst-console.fly.dev`.

Remote delivery evidence is complete:

- GitHub clean-checkout backend, frontend, image-stage and distributed-image HTTP smoke checks
  passed for the implementation and both UI follow-ups;
- Fly reports machine `7814251f390958` healthy in `cdg`, with one passing service check;
- `/api/health` reports schema 3, release `491f81fb1d896b0d793e`, reference digest
  `68ea1a974a077e0b2ef8322564d7799c5fd52cbd21db42b8d5bf1badad57d328`, and evaluation/context
  enabled;
- live browser QA covered the queue, a review-required dossier, responsive layouts, sticky queue
  context, sample CSV evaluation and JSON evidence export without console errors;
- the working sample accepted 31/31 rows and returned one partial-observation attempt.

This closes the research-delivery gate only. Promotion beyond research still requires independent
labels and another precommitted untouched cohort.
