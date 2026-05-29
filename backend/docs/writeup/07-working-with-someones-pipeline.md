# 07 — Working with someone else's pipeline

## The setup

Our four-person team split work naturally. Monica wrote the data ingestion: a Python script that pulls ADS-B trajectory records from OpenSky's Trino-backed historical archive, applies a 200km radius filter around Madrid-Barajas, derives a few useful columns (distance to nearest runway, a rule-based flight phase, a velocity in km/h), and uploads the result into a Supabase project as one table per day.

The rest of us — including the person writing this — needed to use that data for everything downstream: validation, exploration, preprocessing, model training. We did not write Monica's script. We do not own Monica's pipeline. And yet, every assumption we make about the data is implicitly an assumption about her code.

This is the most common configuration in collaborative ML projects. *One person closer to the data, several people further out.* It produces a real coordination problem nobody talks about: how do you trust someone else's pipeline without re-implementing it?

The answer turns out to have layers.

## The data is a starting point, not a contract

The first thing to be clear about: **data delivered to us is not a specification we have to accept**. Monica's pipeline is a starting point — the best version of the data we currently have, not the final word on what the data should be.

When we audit the data and find something off, the right response isn't necessarily "work around it downstream." Often it's "tell Monica and ask if her pipeline should change."

We split the kinds of findings into three categories:

| Finding | Example | Response |
|---|---|---|
| **Schema matches expectations and data is sane** | All 21 columns present, dtypes correct, nulls only where expected | Accept. Document. Move on. |
| **Bug or inconsistency** | The flight_phase rule misclassifies hovering helicopters as "on ground"; range violations indicate a unit error; systematic null patterns suggest a Trino query is filtering wrong | Surface to Monica. Agree on a fix. Update upstream code. Re-run the export. Re-snapshot. |
| **Gap or missing feature** | We discover we need a column from the raw OpenSky data that wasn't included; the radius filter is too narrow; certain days were missed | Same protocol as a bug — surface, agree, update upstream, re-run |

Phase 2 does not silently accept whatever arrived. If validation reveals the pipeline produced something incorrect or insufficient, the right answer is to fix the pipeline, not to work around it downstream.

That sounds obvious in writing. In practice, the temptation is the opposite: "Monica's pipeline did what it did, let's not bother her, we'll just clean it up in our preprocessing." That move *seems* polite — minimize friction, just keep moving — but it has hidden costs. The pipeline keeps producing the same issue. Future contributors hit the same problem. The 'fix' lives in whoever's preprocessing step touched it last, not at the source.

## Trust, but verify

Even with that stance — that the pipeline is a starting point — we still want to *measure* whether the data we received matches what we expect. Hence the consistency check.

The mechanic is small but powerful. For each column Monica's pipeline computed (the velocity in km/h, the distance to runway, the flight phase, the parsed UTC datetime), we re-derive that column from the raw inputs *using her own code* (imported directly from the repo) and compare to the value she stored. If they match, the pipeline is consistent across versions — what's in the database is what the current code would produce. If they don't, *somebody is running a different version of the code than what's in the repo*.

That's a tiny amount of work for an enormous amount of insight. The cost is four lines of Python and a few lookups. The payoff is that we know whether we're working with the same logic she is.

The 100% exact-match requirement on `flight_phase` is the most valuable part. Phase classification is a deterministic rule with no float arithmetic — any disagreement *cannot* be float noise. So a < 100% match is *literally* "Monica deployed a different version of the rule than what we read." That diagnostic is precise enough to act on: she pulls the latest, re-runs, we re-snapshot.

When we actually ran this check on cycle 1's data, the result was clean. Velocity-in-km/h agreed to within 6.6 × 10⁻¹² (essentially perfect floating-point arithmetic). Distance-to-runway agreed to within 6 × 10⁻⁹ meters — billions of meters of haversine computation later. The datetime conversion agreed to within zero seconds. And `flight_phase` agreed at exactly 100.0000% across 1.14 million rows.

That's a strong signal: Monica's deployed code matches what's in the repo. We're working from the same logic. It's the most boring possible outcome of the consistency check, and it's exactly what we wanted — boredom here means we don't have a coordination problem to solve. The interesting outcome is the cheap one to run; we'd much rather have written a cell that returns "all four checks pass" than have to chase down version skew across a four-person team.

## The dependency norm

Halfway through Phase 2, we tried to install the project's dependencies and one of them (`onnxruntime`, pulled in transitively by `traffic`) didn't have a wheel for one of our machines. The instinct was to remove the offending dep — `traffic` wasn't being used in any of our code anyway.

We almost did. Then we checked the git history.

`traffic` had been added by Monica when she first set up the project's `pyproject.toml`. It was tagged with a Spanish comment — "✈️ Análisis de tráfico aéreo (nivel pro)" — suggesting she added it deliberately for some "pro-level analysis" she had in mind. Nobody else had ever pushed the file.

That changes the calculation. **A dependency someone else chose isn't ours to delete.** Even if it's currently unused. Even if our local environment is failing. The right move isn't unilateral removal; it's a conversation.

We landed on a different fix that didn't require touching her dependency: a small `[tool.uv]` config block telling our resolver to find versions compatible with the platform that was failing. The lockfile picks an older `onnxruntime` that has the right wheel. `traffic` stays. Monica's intent stays preserved. We're unblocked.

The conversation about whether `traffic` should *actually* stay in the project gets to happen on its own timeline — as a real discussion, not as a fait accompli triggered by an install error.

This is the kind of small thing that sounds bureaucratic but actually compounds. A four-person team where everyone treats `pyproject.toml` (or `.gitignore`, or `CLAUDE.md`, or any shared config) as collectively owned is a team where things stay coherent. A team where each person trims to taste, expecting nobody to notice, ends up with a config that nobody understands.

## The lockfile question

The same posture applies to the dependency *lockfile*. We discovered, partway through, that the project's `.gitignore` had a `*.lock` rule that was preventing `uv.lock` from being tracked. That's contrary to current Python packaging guidance — the lockfile is supposed to be committed for reproducibility. Without it, "git clone + uv sync" can produce subtly different versions across teammate machines.

We considered just adding the exception (`!uv.lock`) and committing. But again — the `.gitignore` is shared config. The original rule was someone's choice (maybe to exclude a different `*.lock` we don't know about, maybe just an over-broad pattern). We should ask, not unilaterally edit.

So we paused. The Phase 2 implementation work is committed; the lockfile commit waits for a quick team conversation about the rule. Probably 30 seconds of "yeah, exception is fine, here's why we want it" — but the conversation is the point. The pause documents that there's an open call to make, not a hidden one we made for everyone.

## What this looks like in practice

Concretely, on a four-person team working through the ML lifecycle, the upstream-collaboration norms turn into:

- **Audit findings get raised as issues, not silently worked around.** A `[Bug]: flight_phase rule misclassifies helicopters` issue is more valuable than five teammates each handling helicopters in their own preprocessing step.
- **Shared config files are touched with conversation.** `pyproject.toml`, `.gitignore`, `CLAUDE.md` — all three came up this week and all three got the "ask first" treatment.
- **Pipeline outputs are validated, not consumed.** Even from a teammate. The consistency check is the technical version of "trust but verify." It catches version skew before it becomes a mystery debug session.
- **Coordination protocol is documented up front.** Not "we'll figure it out when we hit it" — a one-paragraph statement of "if you find a bug in someone's pipeline, here's what to do" written down before anyone hits a bug.

Most of that is just being a good collaborator. But ML projects in particular have a way of making implicit assumptions explicit *exactly when they're most expensive to fix* — at training time, at evaluation time, at presentation time. Spending a few minutes up front on coordination norms costs less than spending hours later debugging "why does our model behave differently from theirs?"

## The takeaway

Working with someone else's pipeline is the default state of any ML team larger than one person. It's also the place where most coordination problems compound silently. The norm we landed on is simple: *the data is a starting point, not a contract; we audit, we surface findings, we don't unilaterally change shared config*. That's not specific to ML — it's collaboration hygiene — but ML projects punish bad hygiene more than most because the failure modes are subtle and late.

## Slide hooks

- "Data delivered to us is not a specification we have to accept."
- "We didn't write Monica's pipeline. Every assumption we make is implicitly an assumption about her code."
- "Bug, gap, or sane — three findings, one protocol: surface upstream, don't work around."
- "Shared config files are collectively owned. Touch with conversation, not unilateral edits."
- "The consistency check is 'trust but verify' in four lines of Python."
