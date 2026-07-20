# SADAR Analyst Console

SADAR is a post-flight analyst workflow for screening ADS-B-observable approach
attempts at Madrid-Barajas (LEMD). It separates observed rule evidence from missing
coverage and does not claim to detect emergencies, intent or operational safety.

The current product is rules-first. It uses runway-relative geometry, observed data
quality, train-only reference envelopes and explicit contextual criteria. The earlier
LSTM trajectory-anomaly model remains historical benchmark evidence and cannot alter
the Analyst Console verdict or queue priority.

The public application has three deliberately separate evidence lanes:

1. **Synthetic demonstration cases.** Fourteen generated scenarios exercise the
   analyst workflow and rule explanations. They are not recorded flights, and their
   scenario mix is not an estimate of operational prevalence.
2. **Aggregate real-data research.** Counts, rates and limitations derived from
   reviewed OpenSky research cohorts are published without individual trajectories or
   source records. Users obtain any source data directly from OpenSky under its terms.
3. **Ephemeral user uploads.** A bounded CSV or Parquet file is evaluated in memory,
   is not retained, and never joins either the demo set or the research aggregates.
   The user remains responsible for permission to process the file.

The application supports:

- a release-backed queue of synthetic approach scenarios;
- attempt and operation evidence inspection;
- a dedicated Research evidence page for real aggregate findings, source access,
  citation and qualification limits;
- bounded, ephemeral CSV or Parquet evaluation using the same published assessment
  contract; and
- explicit abstention when the available observations cannot support a criterion.

Every route carries the same origin boundary: `Synthetic demo cases · Real research
results shown only in aggregate.` Research qualification is adjacent but secondary.
No demo or aggregate result is presented as representative operational performance or
certified safety evidence.

## Qualification and source access

The frozen qualification is
`not_qualified_no_independent_labels_or_fresh_holdout`; the only allowed role is
`research_and_evidence_labeling_demonstrator`. Operational monitoring, emergency
detection, stabilized-approach certification, ATC decision support and
safety-performance claims are explicitly blocked.

Real aggregate findings cite: Matthias Schäfer, Martin Strohmeier, Vincent Lenders,
Ivan Martinovic, and Matthias Wilhelm. “Bringing Up OpenSky: A Large-scale ADS-B
Sensor Network for Research.” IPSN 2014. Users obtain source observations through
[OpenSky data access](https://opensky-network.org/data/data-access) under the
[OpenSky terms](https://opensky-network.org/about/terms-of-use). Publication notice is
pending and therefore has no notice date.

The former schema-3 application archive was withdrawn from the delivery path because
it contained row-level upstream data. Schema 4 keeps real results in aggregate, uses
deterministic synthetic scenarios for interactive records, and treats user uploads as
ephemeral. The schema-v4 archive is a dataset/application evidence bundle, not a served
model.
