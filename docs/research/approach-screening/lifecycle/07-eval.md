# Phase 7 — Sealed holdout evaluation

## Frozen evaluation contract

The 2026 snapshot was burned once from commit
`7e52fc05eae72159c5d4616f4b2538ff8e5341e7`. Before any Parquet row was read, the runner
verified the precommitted input digest, schema-v3 release, and immutable approach-reference
digest. The criteria and empirical bands were not changed after the burn.

- holdout: 1,774,859 rows / 1,426 operations;
- reconstructed attempts: 613;
- assessable attempts: 387 (63.1% retention);
- not assessable: 226 (36.9% abstention);
- review required: 82 (21.2% of assessable attempts);
- outcomes: 578 final-gate observed, 34 incomplete, 1 go-around.

The machine-readable report is
`docs/research/approach-screening/lifecycle/artifacts/2026-holdout-burn.json`.

## Gate comparison

The precommitted Phase-1 retention target was at least 65%. The holdout retains 63.1%, missing
the target by 1.9 percentage points. The independent weighted human audit required to establish
at least 80% review precision does not exist, so precision, recall, AUROC and safety performance
are unknown and must not be inferred from status counts.

Review workload also drifts from 15.2% on the 2025 newer-source development cohort to 21.2% on
the 2026 holdout. Ground-speed envelope evidence is the dominant contributor (119 criterion
flags); this is a review-workload observation, not proof that the attempts were operationally
unstable. Position-rate conflicts account for 192 abstentions, and barometric path remains mostly
unavailable without QNH or a trustworthy altitude bias.

## Decision

The qualification gate **fails**. The ADS-B-only release is useful as a transparent research
demonstrator and evidence-labeling tool, but it is not qualified as an operational conformance
product. It must be presented as post-flight screening, default to abstention where evidence is
missing, and never claim emergency detection, stabilized-approach certification, or safety
performance.

No threshold or reference change may be justified from this holdout. A replacement release needs
a new untouched cohort plus independent analyst labels. The next lifecycle iteration may add
weather/QNH/wind and aircraft context using development data, but cannot reuse this burn as a
fresh release gate.
