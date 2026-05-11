# 08 — Data engineering rabbit holes

Three asides from the validation work that aren't about ML methodology, exactly, but kept eating real time and producing real decisions. Worth writing down because they're the kind of thing that recurs across projects and that reasonable people make different choices on.

## Aside 1 — Why parquet, why pyarrow

The validation step needs a frozen snapshot of the data. The choice of format for that snapshot turns into a small but cascading chain of decisions.

Three real options for tabular ML data:

| Format | The pitch | The cost |
|---|---|---|
| **CSV** | Works everywhere. Human-readable. Universal. | Loses dtype information on every read (everything becomes strings). No compression — files are 5-10× larger. Slow to scan. Ambiguous null handling (`""`, `NaN`, `NULL` all mean something different to different readers). |
| **JSON / JSONL** | Preserves nested structure. Human-readable. Universal. | Even more verbose than CSV. Slower. Useful for irregular data, not tabular. |
| **Parquet** | Columnar — fast reads of subsets of columns. Preserves dtypes including nullable ints, datetimes with timezones, decimal types. Compresses 5-10× smaller than CSV. Standard in modern ML pipelines (HuggingFace Datasets, Spark, Polars, DuckDB all read it natively). | Not human-readable. Requires an engine library to read or write. |

For data we'll re-read from multiple notebooks across multiple later phases, *parquet is correct*. The dtype-preservation alone is worth it. The first time you read a CSV back and your `time` column is suddenly `'1741683630'` (string) instead of `1741683630` (int), you'll never make this mistake again.

But picking parquet has a downstream consequence: **pandas does not bundle a parquet engine**. `df.to_parquet(...)` raises `ImportError` unless you've installed either `pyarrow` or `fastparquet`. We had to choose.

`pyarrow` won, for three reasons:
- It's the canonical engine — what pandas docs recommend, what HuggingFace and Polars and DuckDB use under the hood, so files we write are interoperable with the rest of the ML ecosystem
- It handles nullable ints and timezone-aware datetimes better than fastparquet (small but real correctness differences)
- It's actively maintained as part of the Apache Arrow project

The cost: pyarrow installs ~50MB of native binaries (it bundles a C++ Arrow runtime). For a project that already uses `scikit-learn`, `matplotlib`, and `pandas`, that's noise — but it's worth knowing.

The chain we ended up walking:
1. The discipline says snapshot the data with a hash
2. So we need a format
3. CSV's dtype problem makes it disqualifying for ML use
4. Parquet is the right format
5. Therefore pyarrow is in the dependencies

That's a *single decision* (snapshot the data) producing *one new dependency* (pyarrow) — not because we wanted a new dep, but because the discipline implies it. Good methodology has consequences.

## Aside 2 — Hash strategies: file bytes vs canonicalized data

The hash is the contract between "this snapshot" and "this version of the data." But hashing has subtleties that are worth being explicit about.

There are two real approaches:

**Hash the parquet file bytes.** Three lines of Python: `hashlib.sha256(open(path, 'rb').read()).hexdigest()`. The hash is the file as written.

**Hash a canonicalized form of the data.** Sort the dataframe by some stable ordering, serialize it as a deterministic string (e.g., sorted CSV with explicit float format), hash that. Robust against changes in the *file format* — same data, different parquet versions, same hash.

The choice has tradeoffs:

- **File-bytes hash:** simple, matches the convention. But the hash is technically tied to the *writer version*, not the data. A `pyarrow` upgrade between writes could change the bytes of a parquet file even when the data is identical. If you rely on the hash being stable across teammate machines, you need to pin the writer version.
- **Canonicalized hash:** stable across writer versions. Same data, different machines, same hash. But you have to define what "canonical" means (sort by which columns? what float precision? what line ending?), and the canonicalization step adds complexity.

We picked file-bytes. The reasoning: with a committed lockfile, all teammates use the same `pyarrow` version, and writer-induced drift is contained. The simplicity of `sha256(file.read_bytes())` is a real benefit. If we ever care about provenance independent of file format (e.g., comparing snapshots across organizations), we can add a `compute_data_hash(df)` later.

The asymmetry to remember: a *file-bytes hash protected by a lockfile* is reproducible. A file-bytes hash *without* a lockfile isn't. The decision to commit `uv.lock` (separate aside, below) is what makes our hash reliable.

## Aside 3 — The lockfile, the platform issue, and the speculative-deps trap

Three threads that turned into one decision.

### The teacher said commit the lockfile

Modern Python dependency management consensus, repeated by every course on the topic in 2025-2026:

- Use `uv` (or another modern resolver) with `pyproject.toml` listing direct deps with version constraints
- Generate `uv.lock` with exact resolved versions of all packages including transitive
- **Commit `uv.lock`** so teammates running `git clone + uv sync` get bit-exact dependency versions

Without the lockfile, `uv sync` resolves fresh on every clone. Two teammates running the same command a week apart can end up with different `pandas` minor versions. That's how "works on my machine" bugs are born.

We discovered, midway, that the project's `.gitignore` had a `*.lock` rule that was excluding `uv.lock`. Probably an over-broad pattern from when the project used a different tool. The fix is one line: `!uv.lock` exception. But because `.gitignore` is shared config, we paused that change for a team conversation rather than just doing it.

That pause is worth its own sentence: small `gitignore` edits feel like the kind of thing you just do, but they affect everyone's clone behavior. Worth the 30 seconds of "hey team, can we add this line."

### The platform issue

Halfway through `uv sync`, the install failed:

```
error: Distribution `onnxruntime==1.26.0` can't be installed because it doesn't 
have a source distribution or wheel for the current platform

hint: You're on macOS (`macosx_14_0_x86_64`)...
```

`onnxruntime` v1.26.0 ships wheels for Linux and Apple Silicon, but not for macOS Intel. One of us was on a several-years-old Intel MacBook, soon to be replaced, but not today.

The temptation: just remove the dep that pulls `onnxruntime` (`traffic`). Untraced, unused in our code.

The catch: `traffic` was added by a teammate (Monica) when she first set up the backend. The Spanish comment "✈️ Análisis de tráfico aéreo (nivel pro)" suggested intent — she had something in mind. Removing it without talking to her would be unilateral edit of shared config.

The fix that didn't require touching her dependency: a `[tool.uv] required-environments` block telling the resolver "make sure the lockfile is solvable for macOS Intel." `uv` then resolves `onnxruntime` to a slightly older version (1.23.x) that does have macOS Intel wheels. `traffic` stays. Monica's intent stays. The Intel teammate is unblocked.

We marked the block as temporary in a comment — once no team member is on macOS Intel, the constraint can be removed.

### The speculative-deps trap

Stepping back, this whole sequence revealed something about the project's `pyproject.toml`. There were deps in there that nothing in the repo actually imports — `traffic`, `python-jose[cryptography]`, `asyncpg`, `websockets`, possibly others. They were added speculatively, "in case we need them later."

The trap: speculative deps cost real money in `uv sync` time, lockfile resolution complexity, and platform compatibility constraints. The `traffic` dep alone added `onnxruntime`, `cartopy`, `pyproj`, `cartes`, `openap`, `pitot`, `metar`, `pyiceberg`, and a couple dozen other packages — a substantial chunk of the install time and a real source of platform issues.

Speculation comes from a good place — "this might be useful, let's have it ready." But it's almost always cheaper to add a dep when you actually need it, with a single-line commit, than to carry the cost of unused deps for the whole project. **Add deps as you reach for them, not as you imagine reaching for them.**

We didn't act on this beyond noting it. Removing `traffic` was off the table because it wasn't ours to remove. But the insight is one for next time: when starting a project, prefer the smaller `pyproject.toml` and let it grow with use, not with imagination.

## Aside 4 — When infrastructure shapes architecture

Monica's data delivery uses a pattern none of us specifically designed for: a single Supabase table that she fills incrementally, until it approaches the 500 MB free-tier limit, at which point she notifies us. We snapshot the data to Drive, then she truncates the table and starts the next cycle.

Spelled out, the cycle looks like:

```
Monica:  TRUNCATE table → run script → run script → ... → ~500 MB used → notify
Txema:   pull table → validate → write parquet to Drive → confirm safe → notify
Monica:  TRUNCATE table → ...
```

That's not what we would have designed if we'd started from a blank page. A blank-page design would probably have created one Supabase table per extraction batch and kept them all around. Or it would have skipped Supabase entirely and written parquets directly to Drive from the extraction script. Both of those are cleaner architectures *in isolation*.

The reason we have the cycle pattern instead is the **500 MB free-tier limit** on Supabase. Free-tier Supabase doesn't have room for the full project's worth of data. So the storage has to recycle. The cycle is what bridges "free Supabase has 500 MB" with "the project needs ~10 GB of data over time."

Two interesting properties of this pattern:

**The Supabase table is *transient*; the local parquets are *durable*.** Their roles have flipped relative to what you'd expect from a database. Most projects treat the database as the source of truth and local files as derived artifacts. We treat the local parquets in Drive as the source of truth and Supabase as a working buffer that gets recycled. The hash on each parquet is what gives us audit-grade reproducibility; Supabase is just where Monica writes things temporarily.

**The hard timing rule.** Monica must not truncate until Txema confirms the snapshot is safely in Drive. If she truncates first, the data is gone forever — Supabase has no backup, and the local parquet doesn't exist yet. We wrote this down in the workflow doc as the single most important rule of the pipeline. A coordination protocol like this only exists because the cycle pattern forces it.

What's interesting about this isn't the specific pattern. It's the more general observation: **infrastructure constraints shape architecture more than design preferences do**. The "right" design for our data pipeline, on a clean slate, doesn't look like what we have. But we don't have a clean slate. We have Supabase's free tier, Drive's ample storage, and Monica's existing extraction script. The pattern that emerges from those constraints is the one we use.

This shows up in production ML systems all the time. Streaming pipelines get designed around message-queue retention windows. Training jobs get split across compute units because individual GPUs have limited memory. Data freshness budgets get set by upstream pipeline cadences. The infrastructure shapes the choices; the choices shape the methodology; the methodology shapes the project.

The lesson worth taking away: **when designing a workflow, the question isn't "what's the cleanest architecture" — it's "what's the cleanest architecture that respects the actual constraints we have."** Our cycle pattern is ugly in the abstract; it's perfectly reasonable given the constraint. Trying to design without the constraint just produces a design that won't run on the infrastructure we actually have.

## The takeaway

Four rabbit holes, four pieces of taste:
1. Pick parquet and pyarrow, not because the rule says so, but because the failure modes of CSV are real and recurring
2. Hash the file bytes, not because it's "more rigorous," but because the lockfile makes it reliable in our setup
3. Commit the lockfile, talk before editing shared config, and prefer growing dependencies on demand
4. Infrastructure constraints shape architecture — design for what's actually available, not what you wish you had

None of these are project-specific. They're the kind of taste that comes from getting bitten once and remembering. The point of writing them down isn't to convince anyone of one answer — it's to make the considerations explicit so the next person hitting them doesn't have to re-derive them.

## Slide hooks

- "Snapshot → format → engine: one ML decision produces one new dependency"
- "File-bytes hash + lockfile = reproducibility. File-bytes hash alone = vibes."
- "The platform issue wasn't 'remove the dep.' It was 'have the conversation, then config-fix instead.'"
- "Speculative deps cost real money. Add as you reach, not as you imagine reaching."
- "Supabase 500 MB free tier → cycle pattern. Infrastructure constraints shape architecture."
- "The database is transient. The parquets are durable. Their roles inverted."
- "Four rabbit holes, four pieces of taste, all worth writing down."
