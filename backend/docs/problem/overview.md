# Problem overview

## Current question

Given post-flight ADS-B observations around LEMD, which reconstructed approach attempts contain
observable criterion evidence worth human review, and where is the evidence too incomplete or
untrustworthy to assess?

The user is an analyst reviewing completed records. The action is to inspect an exact evidence
span or label it for later study. The system evaluates only what ADS-B can support: runway-relative
position, barometric-altitude proxy, observed ground speed and vertical rate, ground track,
coverage and telemetry consistency.

It does not detect emergencies, infer intent or clearance, certify a stabilized approach, or
provide live ATC guidance. Weather, QNH, wind, aircraft type/configuration and mass are not part of
the ADS-B-only release.

## Current outcome

The rules-first schema-v3 candidate is implemented, but its sealed 2026 qualification failed:
63.1% assessable retention versus a 65% target, with independent review precision unknown. The
current console is therefore a research and evidence-labeling demonstrator. A future qualified
release requires independent analyst labels, another untouched release cohort, and evidence that
new context improves workload or review quality.

## Historical origin

The course initially scoped unauthorized-drone detection using an identity gate and an LSTM
trajectory-anomaly scorer. ADS-B cannot observe a non-cooperating drone, and the trained mixed-phase
segment model did not produce an actionable approach-level result. Those experiments remain useful
research history but no longer define the served product. See
[`../architecture/design-trajectory-anomaly-detection.md`](../architecture/design-trajectory-anomaly-detection.md).
