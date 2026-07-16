# Research history

SADAR contains three distinct research stages. They are preserved to show how the
project changed when its data and operational assumptions were tested.

1. **Trajectory-anomaly research.** An LSTM autoencoder and classical baselines were
   evaluated on historical LEMD trajectories. This is benchmark evidence, not the
   current product verdict engine.
2. **Approach screening.** The product was reframed around observable approach criteria,
   runway-relative geometry and explicit data-quality abstention.
3. **Approach context.** Weather and airport context were investigated as additional
   evidence with availability and qualification gates.

Each track has a versioned `reproducibility.yml` defining its question, status,
inputs, splits, commands, immutable artifacts, evidence, limitations, and successor:

- [`trajectory-anomaly/`](trajectory-anomaly/) — historical learned-model experiment;
- [`approach-screening/`](approach-screening/) — current product decision basis; and
- [`approach-context/`](approach-context/) — optional contextual evidence iteration.

Private or unavailable inputs remain explicit gates rather than implied dependencies.
