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

## When the coach drifts (and how it recovers)

The smooth example above is the workflow at its best. The interesting part is what happens when it goes wrong — because that says more about the methodology than the smooth case does.

Phase 2 produced an instructive moment. Working through the helper module's small implementation choices (how to handle parallel HTTP requests, what chunk size to use for hashing, whether to default a verbose flag), the coach drifted. Instead of asking "how should we handle this," it laid out the four options as decision tables and asked the human to pick. That's not coaching — it's *tell, then ask permission*. The skill spec calls this out by name as an anti-pattern: *"Doing without explaining. If you generate a notebook cell that picks a metric, but didn't first walk Txema through why, you've turned coach into autocomplete."*

The user caught it: *"Is that the /ml-lifecycle way of coaching?"*

That single question reset the workflow. The coach:
1. Re-read the coaching-style reference document
2. Acknowledged the drift in writing
3. Recognized the secondary issue: those weren't even the right *kind* of decisions for coach mode — implementation minutiae like chunk sizes don't earn coaching cycles; substantive ML methodology decisions do
4. Recalibrated: just write the helper module (executor mode), save coaching for the actual methodology decisions ahead (validation tolerances, verdict criteria, what "enough" means)

The methodology *built in* this self-correction. The coaching-style document explicitly distinguishes between **slow down** moments (test-set firewall risk, baseline absence, hyperparameter tuning by feel — decisions that compound silently if rushed) and **speed up** moments (mechanical choices, user signaling readiness to move). Knowing which mode to be in is itself part of the discipline.

Two takeaways from this:

**The user as the second pair of eyes is essential.** A coach that never gets called out drifts. One that gets called out, reads its own spec, and corrects produces better work over time. The accountability loop is a feature, not friction. The user being able to say "wait, that doesn't feel like the right mode" — and have the coach take that seriously — is what keeps the methodology honest.

**Not every decision deserves coaching.** Coaching is for *ML methodology choices that shape what we conclude* — metric selection, split design, baseline validity, what counts as a clean validation, when to stop iterating. It's not for choosing chunk sizes or default flag values. Burning coaching cycles on the wrong decisions trains both human and machine to tune out the framework. Good coaching is selective.

The Phase 2 sequence eventually produced seven *real* methodology decisions — critical columns, FAIL action chain, three-key duplicate detection, range bounds, consistency tolerances, Real/Usable verdict structure, the four-bucket Enough verdict — each with substantive Socratic conversation. The implementation details that didn't deserve that conversation got written in executor mode in two minutes. That ratio is the right ratio.

## When the coach overstates (and the user catches it)

The most useful part of the methodology isn't the coach being right. It's the user being able to catch when the coach is wrong, and the coach responding well to that.

A real example from this project. We were closing Phase 2 and discussing what `status: "passed"` actually meant in the manifest, because our data gate had cyclic semantics — new data batches keep arriving, the audit re-applies — but the manifest used a single label that didn't capture the distinction. I proposed two options (a YAML comment, or a structured field) and offered, by way of motivating the second option:

> "At least three phases (Data, Train, Deploy) have semantics that differ from one-shot. That's not an edge case — it's a structural feature of real ML projects."

That sentence was overstated. I had folded "this is real for some projects" into "this is structurally true for real ML projects" without checking each case carefully.

The user replied: *"is this true?"*

That single push prompted me to actually re-examine each phase. Phase 6 train, on closer look, is iterative *within* the phase — sweeps and retries — but the gate fires once when "best model selected." That's one_shot at the gate level, not cyclic. Phase 8 deploy is genuinely cyclic in production but irrelevant for academic projects that don't deploy. Phase 2 in our project is cyclic, but that's because of a specific infrastructure constraint (Supabase's 500MB free-tier limit), not a general pattern.

So the honest revised claim was much narrower: one phase, in our project, has a cyclic gate because infrastructure forces it. Not a structural critique of the framework.

I walked the claim back in writing, explicitly. The user then made a different argument that *did* justify the framework extension — not "the framework is structurally broken" but "I want to use this skill on future production projects where cyclic semantics will be real, so investing now means I'm prepared then."

That's a different kind of justification, and a much stronger one. We went on to add a `gate_semantics` field to the skill's manifest template — but the framing was honest: a future-investment hedge rather than a fix to a structural problem.

The interesting observation about this exchange isn't that I was wrong. AI coaches will be wrong sometimes. It's that the methodology *built in* a way for the user to push back, and the coach's response wasn't "let me defend my claim" — it was "let me actually check." That feedback loop is the engine that keeps the methodology trustworthy over time. A coach that never gets contradicted drifts; one that gets contradicted regularly and re-grounds gets better.

---

## Extending the framework: gate_semantics

This deserves its own section because it's a different kind of work than what `/develop` or `/ml-lifecycle` normally do. Most of what those skills produce are *project artifacts* — phase docs, manifest entries, validation reports. Occasionally, though, a project surfaces an insight that belongs in the *skill itself*. Recognizing those moments and acting on them is how the toolkit improves over time.

The conversation that led to this:

The `/ml-lifecycle` framework, like most ML lifecycle frameworks, implicitly assumes that phase gates are one-shot. You frame the problem once and don't re-frame it weekly. You define the preprocessing pipeline once and don't redefine it per batch. You evaluate on a held-out test set once. Each phase, when "passed," is *complete* for the project.

Our project broke that assumption in Phase 2. We have a working pattern (the truncate-fill-snapshot cycle) where new data batches arrive periodically and the same audit re-applies. The discipline passes once; the batches accumulate. The manifest's `status: "passed"` should reflect "audit operational" not "data complete."

The initial fix could have been minimal: a YAML comment, a sentence in the summary. That solves the project's local problem in two minutes.

But the user reframed the value calculation: this skill isn't a one-project tool. It's something to use across many projects. Future projects will more often be production-shaped, where cyclic data ingestion and ongoing deployment monitoring are the norm. Capturing the distinction now, while the insight is fresh, means future-us doesn't have to re-derive it from scratch on the next project.

That's the right argument. We added a `gate_semantics` field to the skill's manifest template, with three values:

- `one_shot` (default) — gate passes once, phase complete
- `cyclic` — discipline passes once, artifacts accumulate per discrete cycle
- `ongoing` — continuous operation, no discrete cycle boundaries

The default is `one_shot` for every gate, matching the framework's prior implicit assumption. Specific gates override when needed — our Phase 2 set it to `cyclic`. A future production project's Phase 8 would set it to `ongoing`. The framework now *knows* it's making the assumption, instead of silently assuming.

Worth noting what we *didn't* do: we didn't add sub-fields for cycle metadata, didn't add detection logic, didn't change the existing gate transitions. Minimum credible extension. Easy to live with; easy to extend later if a project surfaces a need.

The general lesson: **frameworks worth using are also worth improving when projects find their edges.** The cost of capturing an insight at the framework level is roughly 30 minutes — small enough that whenever you notice a real edge case, the right move is usually to fix the framework rather than work around it locally. Especially when the same person will be using the framework again on the next project.

If you're using AI-coached methodology for a single project and then moving on, this consideration doesn't apply. If you're using it as infrastructure for ongoing practice, every time you patch around an edge case locally, you're paying the cost again on the next project.

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
