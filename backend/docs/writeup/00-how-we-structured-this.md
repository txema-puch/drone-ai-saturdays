# 00 — How we structured this

## Why this section exists

The rest of these notes occasionally talk about *exploratory data analysis*, *training*, *evaluation*, and so on as if they're discrete steps with rules attached. They are. We worked through the project using a structured **ML lifecycle**, and a sentence or two about that framework makes the rest of the writeup easier to follow.

If you're an ML practitioner, this will be familiar — feel free to skip ahead. If not, two minutes here will save you a paragraph of confusion later.

## The eight phases

Most ML projects, deliberately or accidentally, pass through eight stages:

| # | Phase | Question it answers |
|---|---|---|
| 1 | **Problem** | What are we building, for whom, and how will we know it's good? |
| 2 | **Data** | Where does the data come from? Is it usable? |
| 3 | **Preprocessing** | How do we clean, scale, and shape the data for modeling? |
| 4 | **Exploratory data analysis (EDA)** | What does the data actually look like? What surprises us? |
| 5 | **Features** | What do we feed the model — raw inputs or engineered combinations? |
| 6 | **Training** | Build the model. Pick a baseline. Iterate. |
| 7 | **Evaluation** | Score the final model on held-out data, *once*, and report honestly. |
| 8 | **Deployment** | Ship the artifact. Monitor it. Retrain when reality drifts. |

The order matters. Each phase has a "gate" — a checklist that has to be passed before advancing. The most consequential rule is the **test-set firewall**: once you split off a held-out test set, you don't look at it until evaluation. Not for EDA, not for feature selection, not for hyperparameter tuning. Peek and the test score becomes meaningless.

These rules sound rigid until you've seen what happens without them. Most ML failures aren't about picking the wrong model — they're about peeking at the test set, optimizing for accuracy on imbalanced data, deploying without a baseline to compare against, or training without a held-out validation set. The phase structure exists to make those failures harder.

## Why we wrote it down

This wasn't us inventing process for fun. We used a structured methodology because:

1. **Five-week timelines reward discipline.** Skipping EDA to "get to modeling faster" is the most common way to end up with a model that learned the wrong thing. The phase gates force us to pause where it matters.

2. **Four people coordinating need shared language.** "I'm in EDA" tells the team what state the project is in and what's safe to do. Vague status doesn't.

3. **The writeup is part of the deliverable.** If we don't write decisions down as they happen, we won't remember why we made them. That's how good projects produce confused reports.

## A note on tooling (optional reading)

We used a Claude Code skill (`/ml-lifecycle`) to enforce the gates between phases — it refused to advance unless the right artifacts were produced and the right questions answered. It's not the only way to keep ML methodology on track; ML textbooks, course outlines, and team practices all do similar work. But it's how we kept ourselves honest, and there's a separate writeup we may publish later about that workflow specifically. (See if you spot it.)

For the rest of these notes, you can read references to "during EDA" or "in evaluation" as phase 4 or phase 7 from the table above. We won't keep numbering them — descriptive language reads better.
