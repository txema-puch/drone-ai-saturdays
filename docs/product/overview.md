# SADAR Analyst Console

SADAR is a post-flight analyst workflow for screening ADS-B-observable approach
attempts at Madrid-Barajas (LEMD). It separates observed rule evidence from missing
coverage and does not claim to detect emergencies, intent or operational safety.

The current product is rules-first. It uses runway-relative geometry, observed data
quality, train-only reference envelopes and explicit contextual criteria. The earlier
LSTM trajectory-anomaly model remains historical benchmark evidence and cannot alter
the Analyst Console verdict or queue priority.

The application supports:

- a release-backed queue of assessed approach attempts;
- attempt and operation evidence inspection;
- bounded, ephemeral CSV or Parquet evaluation using the same published assessment
  contract; and
- explicit abstention when the available observations cannot support a criterion.
