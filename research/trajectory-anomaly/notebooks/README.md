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

Each notebook starts with an explicit historical-research banner. Embedded output
is evidence from the recorded run; rerunning requires the external datasets and
artifacts identified by the research manifests.

## Archive

`archive/01_*` through `archive/04_*` are early, largely self-contained exploratory
notebooks. They preserve project history but are not kept in execution parity with
the tested research package.
