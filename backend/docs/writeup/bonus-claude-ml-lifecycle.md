# Bonus — How we used Claude as an ML coach

> **Status:** Draft. Undecided whether to publish publicly. If we do, it's a different audience from the drone-detection piece — practitioners interested in AI-assisted development workflows, not airport security or anomaly detection. We drafted it separately so the main writeup doesn't drift into meta-commentary.

## The premise

ML projects fail in predictable ways. Anyone who has shipped a model has the scars: peeking at the test set, optimizing accuracy on imbalanced data, deploying without a baseline to compare against, training without a held-out validation set, refactoring features after seeing the eval results. Most of these aren't caused by bad ML knowledge. They're caused by *not having someone watching* — when you're a team of one (or four undergrads working Saturdays), it's easy to skip the discipline that an experienced reviewer would have caught.

A common solution: methodology. The 8-phase ML lifecycle (problem → data → preprocess → EDA → features → train → eval → deploy) is well-documented in any ML textbook. Phases are gated — you don't advance until certain artifacts exist and certain questions are answered. The gates exist precisely because skipping them is so easy.

A less common solution: **tooling that enforces the methodology actively, in conversation, while you work.** That's what we did on this project.

## What we used

One member of the team (Txema) had built a custom Claude Code skill called `/ml-lifecycle`. It runs inside Claude Code — the AI coding assistant we use for development — and acts as a methodology layer on top.

When invoked, the skill:

- **Reads a manifest file** (`manifest.yml` in the project) that tracks which phase we're in and which gates have passed
- **Loads the right phase reference** — each phase has its own checklist of questions, common failure modes, and exit criteria
- **Refuses to advance** the manifest unless the exit criteria are checked off
- **Surfaces cross-cutting guardrails** — test-set firewall, baseline required, train-test parity, etc. — at the moments they matter
- **Logs significant decisions** as ADR-style files under a `decisions/` directory, so future-us can trace why we made a choice three weeks ago

It works as a coach, not an oracle. It walks through Socratic questions ("what's your primary metric, and why this one?") instead of dumping answers. When we say "go faster," it does. When we say "slow down, I'm lost," it goes back to first principles and rebuilds the explanation.

## What it actually feels like

Here's a condensed exchange from a real conversation in this project — the moment we worked through which metrics to use:

> **Us:** Let's start framing the problem.

> **Skill:** Most of the framing is already done in your initial scoping. Let me map your decisions onto the Phase 1 fields. Two things still need confirming: the cost of false positives vs false negatives, and the out-of-scope list. Also: we need to discuss model selection if you want to commit a track even tentatively.

> **Us:** Yes — but go slow on metrics. I'm a bit lost.

> **Skill:** OK. Forget metrics for a second. Just the four outcomes — true positive, false negative, false positive, true negative. In our LEMD context: a true positive is a real hostile drone correctly flagged...

> *(45 minutes of step-by-step buildup: confusion matrix → precision/recall → F-beta → AUROC. At each step, the skill paused, gave a concrete example with numbers, and asked whether to continue or slow further.)*

> **Us:** Got it. Lock the metric stack.

> **Skill:** Locked into the manifest. Writing decision record D-005. Ready to discuss model selection?

The output of this kind of conversation is a paper trail — a manifest with passed gates, phase docs that read like a real-time decision journal, ADRs for the high-stakes calls. By the end of the project, the writeup is half-drafted: every "why did we do this?" question already has an answer in the audit trail.

## Why this fit our project

Three reasons specific to our situation:

**Four people sharing context.** Saying "I'm doing EDA" tells the team what state the project is in, what's safe to do, and what isn't. Without that shared vocabulary, status updates get vague and coordination gets harder. The phase scaffold gave us a common language.

**Five-week timeline rewards discipline.** Skipping exploratory analysis to "get to modeling faster" is one of the most common ways to end up with a model that learned the wrong thing. The phase gates forced pauses where they mattered most. Annoying in the moment; saved us probable rework later.

**The writeup is part of the deliverable.** This is the big one. We're producing a 15-minute presentation and (likely) a Medium piece. If we hadn't written decisions down as we made them, we'd be reconstructing reasoning from memory weeks late. With the audit trail, the writeup is half-drafted before we sit down to write it.

## Honest caveats

This isn't magic, and it isn't for everyone.

**You can do all of this with paper and a textbook.** Methodology predates AI. The skill enforces what a careful researcher would do anyway. If you have an experienced ML mentor reviewing your work, you may not need a tool to enforce it.

**The skill is opinionated.** Sometimes it pushes back on a decision we'd like to make — "you're trying to skip EDA, let's not." Most of the time the pushback is correct. Occasionally it's annoying. Override is allowed; the override gets logged as a decision so we can revisit it.

**There's a learning curve.** You have to be willing to slow down, answer Socratic questions, and write things down. If you just want a model trained quickly, this isn't the workflow.

**The specific tool is custom.** The `/ml-lifecycle` skill is private. The *principles* are not — anyone can build a similar layer, and the methodology it enforces is in every introductory ML course. If others want to adopt this pattern, we'd recommend starting with the principles (gated phases, audit trail, cross-cutting guardrails) and building tooling that fits their own workflow.

## When this kind of workflow makes sense

| Probably yes | Probably no |
|---|---|
| Multi-week ML project | One-afternoon prototype |
| Working with an LLM coding assistant anyway | Working without AI tooling |
| Audit trail will feed a writeup or presentation | Internal-only model with no external explanation |
| Comfortable with a slower pace in exchange for fewer foot-guns | Already an experienced practitioner who finds scaffolding annoying |
| Project fits a clean ML lifecycle | Open-ended research where the question itself is unknown |

For us, on this project, it's been the right call. The model isn't done yet — but the path to "done" is documented, the decisions are logged, and the writeup is already half-drafted because of it.

## What we'd tell someone trying this

Three pieces of advice if you want to replicate this pattern, with or without our specific skill:

1. **Start with the manifest.** Even one YAML file tracking what phase you're in and what gates have passed is enough to make decisions visible to your future self and your teammates.
2. **Write decisions down as you make them.** Not after. The compounding cost of "I'll write it up later" is a writeup that's vaguer than the decisions actually were.
3. **Pick a methodology that has phase gates.** It can be the 8-phase lifecycle, CRISP-DM, TDSP, or your own. The point isn't *which* — it's *that*. Gates that you have to actively pass make the right discipline cheaper than the wrong shortcut.

## Slide hooks

- "Most ML projects fail not because of bad ML, but because of skipped methodology."
- "We used a Claude skill as an ML coach. The skill enforces the gates between phases."
- "It's a coach, not an oracle. It asks Socratic questions; we make the calls."
- "By the end of the project, the writeup was half-drafted in the audit trail."
- "The principles are public, the specific tool is custom, the pattern is replicable."
