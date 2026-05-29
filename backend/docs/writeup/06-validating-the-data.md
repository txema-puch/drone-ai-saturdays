# 06 — Validating the data before doing anything else

## The question

A teammate (Monica) had pulled ADS-B trajectory data from OpenSky Network's historical database and uploaded it into a Supabase project. The data was *there*, ready to be queried. We had not yet looked at any of it.

The temptation: open a notebook, plot some altitudes, build a model. The discipline: stop, *look at the data*, and prove it's what we think it is before anything else gets built on top of it.

This is the unglamorous part of an ML project. It's also where most ML projects silently break — not in the model, but in a column whose dtype shifted, a sentinel value that snuck in, or a duplicate row that doubled the weight of a flight in training. The cost of skipping this step is not just possible bugs — it's *invisible* bugs that surface weeks later and force a re-run of everything downstream.

So we did the audit.

## "Trust but verify" the data

The first decision wasn't even technical. It was: do we trust what's in the database, or do we treat it as something to be checked?

The honest answer for any collaborative ML project: **don't fully trust anything you didn't generate yourself**. Not because you don't trust your teammate — but because real pipelines drift. Code versions change. A teammate fixes a bug and re-uploads. A library updates and changes how nulls are encoded. None of these are bad acts; they're just normal collaboration. The only way to know whether the data still matches your assumptions is to *check*.

The mechanic for "check" is straightforward:

1. **Snapshot** — pull the data into a stable local file. The remote database can change; the snapshot can't.
2. **Hash** — compute a sha256 of the snapshot file. The hash is the contract: any later phase that loads "the data" can verify the hash matches. If it doesn't, the data has drifted.
3. **Validate** — run a battery of checks on the snapshot. Schema match. Type sanity. Critical-null check. Duplicate check. Range check. Pipeline-consistency check.
4. **Document** — write up what you found, the verdict, and any open questions. Future-you and your teammates need this trail.

We pushed back on this discipline at one point. Couldn't we just query the database live every time we need to look at the data? Why duplicate it locally?

The answer surfaced two things we hadn't fully thought through:
- A live database is *mutable*. If Monica uploads a new day, our row counts change. If she fixes a bug and re-uploads, our distributions shift. The audit results would be inconsistent across time.
- The point of an audit is to *fix the data* in our minds at a specific moment. Once we've said "this is what the data looked like on May 8 and here's its sha256," we have something to compare against later. Without a frozen snapshot, there's nothing to compare to.

The snapshot doesn't replace the database. The database is still the source of truth. The snapshot is *the version we audited*. Phase 3, Phase 4, Phase 6 — they all reference that snapshot via hash. If it stops matching what's in the database, that's a deliberate decision (we re-snapshot) rather than silent drift.

## Seven decisions in ninety minutes

The validation suite required seven small methodology decisions before any code was written. Each affects what we conclude about the data. Each was easy to skip and harder to do well.

### 1. Which columns must never be null?

Not all columns are equal. Some are *structural* — without them, the row is meaningless. Others are *informative* but tolerable to lose occasionally.

We split them: `time, icao24, lat, lon, baroaltitude, flight_id` are critical (six columns out of twenty-one). If any are null, the row is structurally broken and we surface it as a real issue. Everything else is reported but doesn't fail the gate.

The interesting call was on `velocity` and `heading` — the model needs them as features, but a null `velocity` doesn't make the row meaningless, just unusable for training. We left them off the critical list for now. The cost: a row missing `velocity` will pass our audit but fail later in feature engineering. The benefit: we don't conflate "structurally broken" with "ML-unusable" — those are different concerns at different stages.

### 2. What does "FAIL" actually trigger?

If the audit finds nulls in a critical column, what happens? Three options:
- Document it and move on
- Drop the bad rows from the snapshot
- Surface it back to the team

We chose all three: document the finding in our audit report, open a GitHub issue tagging the team (not just Monica — everyone), and *keep the broken rows in the snapshot*.

That last part is non-obvious. Why keep them? Because if we drop them silently, the snapshot no longer mirrors what's in the database, and the hash-as-contract breaks. The audit's job is to identify problems, not to clean them up. Cleaning is the next phase's job.

### 3. What counts as a duplicate?

Pipelines occasionally insert the same row twice. Most projects pick one definition of "duplicate" and run it. We discovered that ADS-B has edge cases that make a single definition lie: multiple ground receivers can pick up the same broadcast at the same instant, and the aggregator may not perfectly merge them. So "duplicate" depends on what you mean.

We ended up reporting *three* counts:
- **Loose**: same flight, same epoch second (catches everything, including the multi-receiver edge case)
- **Medium**: same flight, same time, same lat/lon (filters out GPS-jitter edge cases)
- **Strict**: byte-for-byte identical row (only fires for genuine pipeline re-insertion bugs)

The combination is *diagnostic*. All zero → clean. Loose only → multi-receiver noise, investigate. Medium → suspicious. Strict → definite bug. Three numbers told us more than one ever could.

### 4. Range bounds: catching broken data, not narrowing the question

When we check that altitudes are in a "plausible" range, what does plausible mean?

There are two answers. *"Within physical limits"* (lat between -90 and 90, altitudes below the upper atmosphere). *"Within what we want to model"* (drone-shaped: under 1500m, slow). These are different questions and they belong to different phases. Phase 2 catches *broken* data — values outside physical possibility, sentinel values like `-9999` standing in for "unknown." Phase 5 will filter to *interesting* data once we know what we're modeling.

Mixing the two would mean rejecting valid airliner data as "broken." We used generous physical bounds, plus a soft cross-check that the lat/lon falls within a ~200km box around Madrid (a sanity check on Monica's spatial filter, not a rejection criterion).

### 5. Tolerances for "did the pipeline drift?"

Monica's code computes some derived columns: `velocity_kmh = velocity × 3.6`, `dist_to_runway_m` via haversine, a rule-based `flight_phase`, and a `time_utc` parsed from the epoch. We can re-derive each of these from the raw inputs and compare to her stored values. If they match, the pipeline is consistent across versions; if they don't, something has shifted.

The tolerance for "match" depends on the math involved:
- Pure multiplication (velocity_kmh): only IEEE-754 rounding noise. Tolerance: vanishingly small.
- Haversine distance: trig functions accumulate small errors. Tolerance: 1 meter.
- Datetime parsing: deterministic. Tolerance: 1 second (effectively exact).
- Rule-based classification: discrete output. Tolerance: **none**, must match 100%.

The `flight_phase` exact-match is the cheapest and most powerful. If the rule outputs disagree, *somebody is running a different version of the code*. That diagnostic costs four lines of Python and protects us from silent code drift across collaborators.

### 6. The verdict has shape

Real / Usable / Enough — three questions, three different answers.

*Real?* Is this actually ADS-B data near the airport we think it is? Pass/fail from schema, range, and bbox checks.

*Usable?* Is the data structurally sound? Pass/fail from null, duplicate, and consistency checks.

*Enough?* Do we have enough volume and diversity to train an LSTM autoencoder? *Not* a binary — four buckets:
- **Not yet** (under 500 trajectories) — the design's viability floor isn't met
- **Soft dev** (under 30 days OR under 5K trajectories) — pipeline development can proceed; training is blocked
- **Conditional** (between 30 and 90 days, between 5K and 20K trajectories) — trainable but with limited diversity
- **Pass** (90+ days, 20K+ trajectories) — well-supported

The four-bucket framing forced us to confront a real possibility: that one day of data is enough to *build the pipeline* but not enough to *train the model*. Without it, we'd have either declared "yes, we have enough" prematurely or "no, blocked, can't proceed" when we could absolutely have proceeded with caution.

### 7. What "Enough" actually means is a deeper question than it looks

We were ready to lock the four buckets when one of us asked: *how do we define "enough" anyway?*

The answer turned out to be: *it depends on the lens*. Three lenses, three different thresholds:

**Project viability lens.** Below 500 usable tracks, the project's premise breaks; switch approaches. This is from the original scoping.

**DL training rule of thumb.** Roughly 10× the model parameters in training examples. For our LSTM autoencoder (~150K parameters), that's ~1.5M timesteps — but timesteps within a flight are correlated, so the *effective* sample size is closer to the *trajectory count*. Practical floor: ~5,000 trajectories for trainable, ~20,000 for reliable.

**Diversity coverage.** Even hitting the trajectory threshold isn't enough if all the data is from a single Tuesday morning. The model would learn "Tuesday morning at LEMD," not "normal flight at LEMD." We need different times of day, days of week, weather conditions.

So "enough" isn't one number — it's a multidimensional check. The audit reports trajectory count *and* day count *and* day-of-week coverage *and* hour coverage. The four buckets compress those into a single verdict, but they're informed by all of them.

## What the audit caught

The first time we ran the validation against the actual data, it surfaced exactly the kind of issue the audit is for. Out of 1.83 million rows, only 1.14 million were unique. **Thirty-seven percent of the data was duplicates.**

The diagnostic was the three-key duplicate detection paying off. Loose key, medium key, and full-row counts all came back high together — same flights, same epoch seconds, same lat/lon, full byte-for-byte equality. That combination rules out the multi-receiver edge case (which would show loose-key dups but not full-row dups) and points unambiguously at *the same row inserted multiple times*.

Looking at duplication multiplicity (we added a quick diagnostic cell), the pattern was a clean staircase from 1× to 7×: 665K rows seen once, 324K seen twice, 116K three times, all the way down to 303 rows seen seven times. Not random noise — a precise overlay of an extraction script that had run roughly seven times over partially overlapping date ranges.

So we knew exactly what had happened upstream: the export script had been re-run more than once during development without an idempotency check, and each rerun added new rows on top of the existing ones.

### What we did with the finding

Three actions, in order:

1. **Surfaced upstream**, not silently worked around. A briefing to Monica with the multiplicity table and the proposed fix at the source: a unique constraint on `(icao24, time, lat, lon)` plus `INSERT ... ON CONFLICT DO NOTHING`, so the extraction script becomes idempotent on future runs. Monica's script is now updated; future extractions will arrive clean directly.

2. **Deduped the existing batch locally.** The audit's default rule is "snapshot mirrors source, don't silently clean." But the override applied here — the duplicates were known garbage, no information was lost by removing them, and keeping them would have weighted some flights 7× more in training. We produced two artifacts: the raw parquet (audit evidence — proof the issue existed) and a deduped parquet (the canonical version downstream phases load). Both stored, both hashed, both documented.

3. **Documented it explicitly.** The Phase 2 doc records the duplicate rate, the rule used for deduplication, and why deduplication was justified at this stage rather than deferred to preprocessing. Future readers — including ourselves three months later — see the audit caught a real bug and what was done about it.

### Why this is worth telling

The discipline of "audit the data before doing anything" is sometimes pitched as a thoroughness ritual. The duplicate finding is an example of why it isn't ritual: a model trained on the raw data would have learned that some trajectories are seven times more common than they really are. The training would have completed without errors. The metrics would have looked plausible. The model would have been quietly wrong, and we would have had no obvious way to know.

The audit caught it before any training started. The fix took less than a day. The same bug, undetected, could have eaten a week of debugging downstream. That's the value of doing this work explicitly and early.

## The audit doesn't just defend — it discovers

A second, quieter finding from the same audit run made a different point. The class-balance cell reported:

- **Rows**: arrivals 1,107,934 vs departures 726,150 — roughly 60/40
- **Unique flights**: arrivals 653 vs departures 632 — roughly 51/49, almost balanced

The flight counts are balanced. The row counts are not. We almost missed it because the audit "passed" — class balance isn't a fail condition. But sitting with the two numbers for a moment surfaced the underlying pattern: **arrivals carry about 50% more state vectors per trajectory than departures** (≈1,696 rows/arrival vs ≈1,149 rows/departure).

That's not a bug. It's physics. Arriving aircraft enter our 200km radius at cruise altitude and descend gradually — a typical approach takes about 30 minutes inside the zone. Departing aircraft climb quickly out of the zone in about 17-20 minutes. The data faithfully records what aircraft actually do, and what aircraft actually do creates this asymmetry.

The audit's job was to validate. It validated. But sitting with the validated numbers, we noticed a *structural property of the data* that we hadn't designed the audit to surface. A few practical implications:

- **For per-timestep training**, arrivals would be weighted 1.5× more than departures. The model's notion of "normal" would lean toward approach patterns.
- **For per-trajectory training** (which the LSTM autoencoder uses), counts are equal but mean sequence lengths differ. Phase 5 and Phase 6 will need to think about this.
- **For the writeup**, this is a more interesting finding than "we have N flights" — it tells the reader something about how the project's modeling choices interact with the physics of the data.

The bigger lesson: audits are usually pitched as defensive. They catch bugs. But a careful audit also surfaces structural insights — properties of the data that aren't bugs but matter for modeling. The same is true of the LEMD bounding-box edge case we hit (our conservative cutoff of -1.20 lon caught 0.04% of valid rows because the data legitimately extends to -1.15). Not a bug; not a critical issue; but a real piece of geography we wouldn't have noticed without the audit.

The right framing isn't "the audit defends against bad data." It's "the audit forces you to actually look at the data, and looking surfaces things you didn't know." Phase 4 EDA picks up where the audit leaves off, but Phase 2 isn't a separate activity — it's the first time anyone actually opened the box.

## When one finding became a framework

Section 6 above describes how we handled the duplicate finding: surface upstream, override locally with a deduped parquet, document. That was the response we landed on after analyzing the specific situation.

A separate observation surfaced midway through the audit: we'd hand-built a response for the duplicate case, but other findings could appear in future cycles, and each would need its own response. Without a general framework, every new finding would re-invent the analysis from scratch. The team member at the keyboard next week would have to re-derive "is this Response B territory, or D, or something else?" without prior reasoning to lean on.

So we paused the audit-close to write the framework. Six response categories, mapping the kinds of findings the audit can produce to the kinds of actions that make sense:

- **A — Block**: the data is so broken downstream use produces nonsense. Surface urgently, don't update the manifest, ask for a re-extract.
- **B — Override fix**: the finding is known garbage with no signal value (the duplicate case). Apply the fix in the notebook, produce a cleaned parquet alongside the raw, document.
- **C — Surface upstream + proceed**: the finding indicates an upstream bug worth fixing, but the current cycle's data is still usable. Open an issue, document, proceed.
- **D — Document + proceed**: the finding is expected or has no practical upstream fix (e.g., natural ADS-B null rates). Just record.
- **E — Investigate first**: when the finding's nature isn't immediately clear. Default to this when in doubt.
- **F — Update the methodology**: when the audit itself is the problem. Fix the audit; don't apply the wrong response.

Six categories sounds like overkill for one project. But the structure was exactly right when the audit's *other* findings landed (the geoaltitude nulls, the range outliers, the bbox tightness) — each one fit a category cleanly, and the response was decided in seconds instead of minutes. The framework's value isn't in handling the dup case; it's in handling everything *after* the dup case without re-deriving.

The general pattern: **when a specific case suggests a recurring shape, write the recurring shape down**. Every minute spent on the framework saves N minutes on N future cases. The break-even is usually somewhere around the third instance — which means the right time to write the framework is when you can see the third instance coming, even if it hasn't arrived yet.

## What the audit produced

By the end, we had:
- A frozen, hashed local snapshot of every available day's data
- A schema dictionary documenting every column (type, range, null rate, kind)
- A validation report with explicit PASS / FAIL / REVIEW outcomes for each check
- A class-balance summary
- Volume metrics across all snapshots
- A three-part verdict (Real / Usable / Enough) with concrete numbers and recommended next actions

That's a lot of structure for what felt like a short detour. But the structure is exactly what makes the rest of the project trustworthy. Phase 3 (preprocessing) doesn't have to wonder if the data is clean; it has the audit. Phase 6 (training) doesn't have to wonder if the data drifted between when the audit ran and when training started; it has the hash. The writeup doesn't have to invent a "we checked the data" section; it has the audit report verbatim.

## The takeaway

Auditing data before modeling isn't due diligence. It's the foundation downstream phases stand on. Skipping it means the foundation is implicit, untested, and discovered to be cracked at the worst possible moment. Doing it explicitly takes a couple of hours and produces an artifact teammates and reviewers can read.

The seven decisions don't generalize unchanged to other projects — your data has different columns, different dependencies between them, different "broken" patterns. But the *practice* of identifying which decisions you'd be making, surfacing them, and writing them down before any code runs — that part travels.

## Slide hooks

- "We had data. We didn't look at it. Most ML projects fail right here."
- "Snapshot, hash, audit, document — the four-step audit discipline."
- "Three counts of duplicates told us more than one ever could."
- "Phase 2 catches *broken*. Phase 5 catches *uninteresting*. Don't mix them."
- "'Enough' isn't a yes/no. It's a four-bucket verdict from a multi-lens definition."
