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
defect. It remains immutable provenance but must not be deployed. Replacement candidate
`491f81fb1d896b0d793e` is pending publication and independent anonymous installation.

Fly deployment, remote container smoke, and live QA remain the delivery gate. Promotion beyond
research requires independent labels and another precommitted untouched cohort.
