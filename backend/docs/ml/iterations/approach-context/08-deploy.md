# Phase 8 — Research deployment

## Candidate contract

The local immutable schema-v3 candidate is release `541006baf9ed3748aea3` with:

- engine `approach_context_v1`;
- reference digest `53c6998329131d7fc6a86334b7b4e14f749a8e6c64b0944bd769f5ad123bb1cf`;
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

## Publication gate

Publication to the existing immutable Hugging Face artifact repository and Fly deployment may
occur only after code review, full tests, strict anonymous artifact installation, container
smoke testing, and live QA. Promotion beyond research requires independent labels and another
precommitted untouched cohort.
