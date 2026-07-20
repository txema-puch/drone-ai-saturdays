# Repository and product architecture

## Authority boundaries

- Git stores source, methodology, decisions, human-readable evidence, checksums,
  artifact locks and reproducibility contracts.
- Hugging Face stores trained weights, generated numerical outputs and immutable
  release archives. The current application target is a Hugging Face **dataset**
  repository because its archive is application evidence, not a model.
- `docs/` stores curated public product and research documentation.
- `.workspace/` stores ignored local collaboration material and drafts.

## Python workspace

The backend is one uv workspace with two distributions:

```text
backend/
├── pyproject.toml                 # distribution: sadar
├── src/sadar/
├── research/
│   ├── pyproject.toml             # distribution: sadar-research
│   └── src/sadar_research/
└── tests/
    ├── product/
    ├── research/
    └── delivery/
```

`sadar` contains the deployed approach-screening domain, API, generic trajectory
primitives and release transport. `sadar-research` contains the executable historical
trajectory-anomaly pipeline and may depend on `sadar`. Production code must never
import `sadar_research`.

## Runtime boundary

The Fly image installs only the `sadar` wheel and its generated hash-locked Linux
dependencies. The Vite build is copied to an explicit directory configured with
`SADAR_FRONTEND_DIR`; it is not embedded in the wheel. Before publication, CI supplies
a deterministic local-reviewed schema-v4 directory through a BuildKit named context;
after publication, production fetches the immutable dataset lock anonymously. Both
modes run the same schema-v4 validator and install the same manifest plus eight
allowlisted payload files. The image contains no research package, notebooks, working
documents or trained-model outputs.

`SADAR_RELEASE_SOURCE` accepts only `local-reviewed` and `locked-public`.
`local-reviewed` requires the named context and never reads the retired product lock.
`locked-public` requires the marker-only fallback context and fetches the immutable
lock. Unknown modes, a missing local context, the fallback marker entering runtime, a
non-schema-v4 release, and a non-40-hex source revision fail the image build.
Credentials are not Docker inputs.

## Shared symbol ownership

- Generic geodesic math and operation segmentation belong to `sadar.trajectory`.
- Current AIP runway geometry belongs to `sadar.approach`.
- The legacy runway coordinates and derived distance feature remain frozen inside
  `sadar_research.trajectory_anomaly` because they are part of the old model contract.

## Release boundary

Canonical JSON, hashing, safe relative paths, deterministic archives and verified
transport are shared mechanics. Schema-v4 public approach evidence and schema-v2
historical model releases retain separate validators and semantics.

Schema v4 has three hard-separated lanes: synthetic demo records, real-data aggregate
research findings and ephemeral user uploads. The public archive contains the first
two; uploads are never persisted. The aggregate lane cites OpenSky, links users to
[OpenSky data access](https://opensky-network.org/data/data-access), records the current
[terms](https://opensky-network.org/about/terms-of-use), and records that publication
notice was sent on 2026-07-20 without claiming acknowledgement. The withdrawn schema-3 product artifact is not
a template: it contained row-level upstream observations and remains blocked from the
delivery path.
