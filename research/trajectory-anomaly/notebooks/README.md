# Notebook evidence

## Lifecycle

Run these in evidence order, not filename order:

1. `lifecycle/05_phase2_data_validation.ipynb` — source-data audit and snapshots.
2. `lifecycle/07_phase3_preprocess.ipynb` — preprocessing decisions and parity.
3. `lifecycle/06_phase4_eda.ipynb` — structural exploratory analysis.
4. `lifecycle/08_phase4_dataset6_emergency_eda.ipynb` — external dataset limits.
5. `lifecycle/09_phase6_train.ipynb` — model/baseline training bake-off.
6. `lifecycle/10_sadar_comparison.ipynb` — cross-project comparison.
7. `lifecycle/11_phase6_loopback.ipynb` — ceiling-raising experiments.
8. `lifecycle/12_density_baselines.ipynb` — wider non-deep-learning baseline panel.
9. `lifecycle/13_phase7_eval.ipynb` — Phase-7 sealed-fold test burn + blind real-anomaly head-to-head.

Each notebook starts with an explicit historical-research banner. Embedded output
is evidence from the recorded run; rerunning requires the external datasets and
artifacts identified by the research manifests.

`13_phase7_eval.ipynb` is preserved as recorded evidence but, unlike 05–12, its code
cells were **not** rewritten to the current `sadar_research` package — they reference the
pre-restructure `backend.core` layout (preserved via the pre-restructure tag), so it is not
in execution parity. Its companions are the burn script `../scripts/phase7_burn.py` and the
decision `docs/research/trajectory-anomaly/lifecycle/decisions/D-012-phase7-zone-reweight.md`.

## Archive

`archive/01_*` through `archive/04_*` are early, largely self-contained exploratory
notebooks. They preserve project history but are not kept in execution parity with
the tested research package.
