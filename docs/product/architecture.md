# Repository and product architecture

## Authority boundaries

- Git stores source, methodology, decisions, human-readable evidence, checksums,
  artifact locks and reproducibility contracts.
- Hugging Face stores trained weights, generated numerical outputs and immutable
  release archives.
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
`SADAR_FRONTEND_DIR`; it is not embedded in the wheel. The immutable approach release
is fetched and verified separately. The image contains no research package, notebooks,
working documents or trained-model outputs.

## Shared symbol ownership

- Generic geodesic math and operation segmentation belong to `sadar.trajectory`.
- Current AIP runway geometry belongs to `sadar.approach`.
- The legacy runway coordinates and derived distance feature remain frozen inside
  `sadar_research.trajectory_anomaly` because they are part of the old model contract.

## Release boundary

Canonical JSON, hashing, safe relative paths, deterministic archives and verified
transport are shared mechanics. Schema-v3 approach evidence and schema-v2 historical
model releases retain separate validators and semantics.
