# Phase 8 — Research deployment

## Candidate contract

The local immutable schema-v3 candidate is release `df22ce72488273f28c8a` with:

- engine `approach_context_v1`;
- reference digest `93903a371728257390b2099aae44bf040f1ea212714d85f80dc6b47dcf0e2f24`;
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

The candidate was published to `Txemapuch/sadar-demo-release` on 2026-07-15 at immutable
revision `1f1ac1bd2e8ca2cf6ff868d372e7508b902cfc13`. The deterministic archive SHA-256 is
`52e4cbd799c62ba40c701d6d07a9b9c48cdcb031e288108f455a6eeb26e8b182`. Both the publisher's
anonymous redownload and the independent CI fetch path installed and strictly validated release
`df22ce72488273f28c8a`.

Fly deployment, remote container smoke, and live QA remain the delivery gate. Promotion beyond
research requires independent labels and another precommitted untouched cohort.
