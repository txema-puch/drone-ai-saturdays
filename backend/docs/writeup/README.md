# Writeup notes

Draft material for the end-of-project deliverables: presentation slides + Medium publication.

## What goes here

This folder holds **narrative rationale**: the *why* behind every significant project decision, written in conversational tone. Different from the formal `backend/docs/ml/` ML lifecycle docs, which are structured, definitive, and serve as the audit trail. Here we explain — for an outside reader — how we got from "Scenario 8 in the course brief" to "two-layer LSTM Autoencoder anomaly scorer with an IF baseline."

Each file is a topic. It captures:
- The question we were wrestling with
- The options we considered
- Why one won, and what the alternatives would have cost us
- The honest caveats — including parity issues, scope cuts, and open questions

## How to use it

When drafting the slide deck or the Medium piece, **start here, not from scratch.** Each topic file ≈ one slide group or one article section. Adapt prose, don't re-invent.

When a new design conversation produces interesting reasoning (typically when working through later questions on data exploration, training, or evaluation), add the rationale here. Either:
- Extend an existing topic file (e.g., add an "Update from EDA" section)
- Create a new topic file (e.g., `06-feature-engineering.md`)

Keep the tone conversational. We'll polish before publication.

## Index

| # | Topic | Question it answers |
|---|---|---|
| 00 | [How we structured this](00-how-we-structured-this.md) | What is the ML lifecycle and why does the rest of this writeup talk about phases? |
| 01 | [Anomaly detection vs classification](01-anomaly-detection-vs-classification.md) | Why anomaly detection, and not the three-class intent classifier the brief asked for? |
| 02 | [Metrics explained](02-metrics-explained.md) | What does it mean for the model to be "good," and why these four metrics? |
| 03 | [Architecture and baseline](03-architecture-and-baseline.md) | Why an LSTM Autoencoder, and why also an Isolation Forest baseline? |
| 04 | [Conditional normality](04-conditional-normality.md) | What if "normal flight" depends on weather, time of day, or runway configuration? |
| 05 | [Inference modes (eval vs demo)](05-inference-modes.md) | Does the model run on full trajectories or as they unfold? |
| 06 | [Validating the data before doing anything else](06-validating-the-data.md) | What did we actually do before training a single model, and why was that worth doing? |
| 07 | [Working with someone else's pipeline](07-working-with-someones-pipeline.md) | When a teammate produces the data we model on, how do we trust it without re-implementing everything? |
| 08 | [Data engineering rabbit holes](08-data-engineering-rabbit-holes.md) | Why parquet + pyarrow, why hash file bytes, and the speculative-deps trap. |

### Process / tooling notes (separate audience)

Optional draft material on how we structured the project, intended for an audience interested in AI-assisted development workflows rather than airport security. May or may not be published — and if published, separately from the main piece since the audience differs.

| # | Topic | Question it answers |
|---|---|---|
| bonus | [How we used Claude as an ML coach](bonus-claude-ml-lifecycle.md) | What was the development workflow that made the audit trail possible? |

## Style guide

- **First-person plural** ("we considered…"). The team is the narrator.
- **Concrete examples** wherever possible — Gatwick December 2018, LEMD runway 32R, "1000 normal flights, 5 anomalies."
- **Short paragraphs.** 3–5 sentences max. Readers skim.
- **Honest caveats.** Don't hide the things we cut, the parity issues, the open questions. They make the writeup credible.
- **Numbers when they help.** "AUROC > 0.85" is more useful than "good performance."
- **Avoid jargon without unpacking it.** Define `precision` the first time you use it. Same for `AUROC`, `reconstruction error`, `bottleneck`.
- **Don't call internal artifacts "the design doc" or "the spec."** Outside readers don't know what those are and shouldn't feel they're missing context. Refer to upfront brainstorming as **"our initial thinking,"** **"our scoping,"** **"how we framed it early on,"** or simply describe what we did. The internal artifact (`backend/docs/architecture/design-trajectory-anomaly-detection.md`) was a kickoff brainstorm we did to narrow scope from the original course brief — frame it that way for external readers.

## Mapping to deliverables

| Deliverable | Source files | Approx. effort |
|---|---|---|
| Presentation slides (~15 min) | All 5 topics, condensed to 2-3 slides each | Adapt + trim |
| Medium article (~2,000–3,000 words) | All 5 topics, expanded with figures + plots from EDA and evaluation | Adapt + add visuals |
| Course writeup (academic format) | All 5 topics + numbers from final evaluation + references | Reformat to LaTeX/PDF |
