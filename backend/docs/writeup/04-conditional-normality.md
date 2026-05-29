# 04 — Conditional normality: what's "normal" depends on context

## The question

We're training a model to learn what authorized flight near LEMD looks like. But authorized flight isn't one thing — it changes depending on wind, time of day, season, and which runways are active. If our model averages over all of that, it learns a wider, fuzzier "normal" than it should. And anomalies that would obviously stand out under one regime might look fine under another.

This is the question that came up halfway through our initial scoping, and it's the kind of "wait, but…" moment that turns a course project into something interesting. It's not solved yet — we logged it as an open question to revisit during exploratory data analysis and feature engineering.

## Why airport configurations matter

Madrid-Barajas has four runways arranged as two parallel pairs:
- 14L / 32R
- 14R / 32L
- 18L / 36R
- 18R / 36L

At any given moment, two of those four are active, and they're set up in one of two configurations:

- **North configuration**: takeoffs from 36L/36R, landings on 32L/32R
- **South configuration**: takeoffs from 14L/14R, landings on 18L/18R

The choice flips primarily on wind direction — planes take off and land into the wind. But it's not the only factor:

- **Time of day**: noise abatement procedures often force single-runway operation at night
- **Day of week**: Monday morning at LEMD is a completely different traffic pattern from Saturday midday
- **Season**: holiday peaks, summer thunderstorms, winter scheduling
- **Visibility**: low ceilings push everyone onto ILS-equipped runways
- **Special operations**: VIP movements, military activity, emergencies

A perfect arrival into runway 32R in north config and a perfect arrival into runway 18L in south config look *very different* when plotted on a map. Both are normal. But the trajectories themselves — the lat/lon paths, the descent profiles, the heading sequences — are not interchangeable.

## What happens if the model doesn't know about context

If we feed the model only the trajectory, with no signal about which configuration is active or which way the wind is blowing, it learns *all of these regimes mixed together* as "normal." The decision boundary becomes wider than it should be:

- A trajectory that lands at 200m altitude two miles east of where it "should" be in north config could look fine to the model — because *some* normal trajectory used that corridor in south config.
- A descent profile with an unusual pattern at 2000ft could look unremarkable — because *some* normal descent profile passes through there during low-visibility approaches.

This is a known class of problem in ML: **conditional anomaly detection** or **context-dependent normality**. The fix is to *condition* the model on the relevant context, so it learns "normal *given* this configuration" rather than "normal *averaged over* all configurations."

## What our initial thinking got right, and what's missing

When we first scoped the project, we gave the model two context features:

- `time_of_day_sin` and `time_of_day_cos` — cyclical encoding of the hour (this is the standard trick to avoid the model thinking 23:00 and 01:00 are far apart)

Useful, but partial. It captures *time of day* but misses everything else.

What's missing:

| Context dimension | In our initial sketch? | How we'd add it |
|---|---|---|
| Time of day | ✅ `time_of_day_sin / cos` | Already there |
| Day of week | ❌ | One-hot encode, or just `weekend` boolean |
| Season / month | ❌ | `month_sin / cos` (cyclical, like time of day) |
| Active runway configuration | ❌ | Could be inferred from the dominant traffic flow direction |
| Wind direction | ❌ | Requires external METAR data |
| Visibility / ceiling | ❌ | Requires external METAR data |

The cheap ones (day of week, month) are basically free to add and worth doing. The harder ones (runway config, METAR) need either external data sources or some inference logic. Worth investigating during exploratory data analysis — can we *see* configuration regimes in the data?

## How we'll address it

Two approaches, and we'll probably mix them:

**Add context features as additional inputs.** Each timestep gets enriched with `(day_of_week, month_sin, month_cos, inferred_runway, ...)` alongside the trajectory features. The model sees both the trajectory and its context together, and learns to interpret the trajectory through the context lens.

**Train separate models per configuration** — one for north, one for south. Cleaner per-regime decision boundaries, but data-hungry and harder to demo.

For the project: we'll start with approach 1 during feature engineering, adding the cheap context features (day-of-week, month). METAR integration is a stretch; per-configuration models are out of scope for 5 weeks.

## What this means for the writeup

This is the kind of "what we wrestled with" content that makes a Medium piece readable. The arc is:

1. *We built a model that learns normality.*
2. *Wait — what's normal depends on context.*
3. *Here's how we addressed it (partially), and what we'd do next time.*

Honest, specific, and credible. The reader gets to see us notice a problem, think it through, and decide what to do about it within constraints.

## Slide hooks

- "Madrid-Barajas runs in two configurations. They look different in the data."
- "If the model doesn't know which configuration is active, it averages over both. Decision boundary gets fuzzy."
- "We added cyclical time features. We didn't add wind direction. Here's what that buys us, and what it costs us."
- "This is the kind of problem you find by looking at the data carefully — which is why exploratory data analysis is not optional."
