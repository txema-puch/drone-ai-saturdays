# Decisions

Log of key decisions the team needs to make or has made.
Add a row when something is decided. Link to the discussion (Discord, PR, etc.) if relevant.

---

## Open decisions

### D-001 — Primary use case

**Question:** Which scenario do we focus on?

**Options:** See [use-cases.md](../problem/use-cases.md)

**Tradeoffs:**
- Airports → best data (OpenSky), clear stakeholder, measurable impact
- Prisons → very concrete problem, harder to get real data
- Urban environments → most general, good datasets, but fuzzier problem definition

**Status:** ⏳ Pending team discussion
**Deadline:** Before week 1 starts
**Owner:** whole team

---

### D-002 — Signal modality

**Question:** ADS-B trajectory, visual detection, RF classification, or multi-modal?

**Tradeoffs:**

| Option | Pro | Con |
|---|---|---|
| ADS-B only | Best free data, time-series ML is course-relevant | Misses 70-95% of illegal drones |
| Visual only | Easy to demo, good public datasets | Requires camera infrastructure, doesn't generalize |
| RF only | Catches non-ADS-B drones | Hard to visualize, limited public datasets |
| ADS-B + Visual | Strong value prop, covers more threat surface | More integration work |

**Status:** ⏳ Pending team discussion
**Deadline:** Before week 1 starts
**Owner:** whole team

---

### D-003 — Dataset primary source

**Question:** Which dataset do we use as the foundation?

**Current candidates:**
- OpenSky Network (ADS-B) — needs account, free
- Roboflow drone detection datasets — ready to use
- Kaggle RF classification — ready to use
- MMAUD (multi-modal) — large, rich, may be complex

**Status:** ⏳ Pending — depends on D-002
**Owner:** whole team

---

### D-004 — Scope of trajectory prediction

**Question:** Do we predict trajectory (sequence-to-sequence), or only classify/score current behavior?

**Tradeoffs:**
- Prediction (GRU/LSTM) = more novel, harder, needs good trajectory data
- Classification only (XGBoost/IF) = simpler, more reliable, still useful

**Status:** ⏳ Pending

---

## Decided

*(Nothing decided yet — this will fill up as we align)*

| ID | Decision | Rationale | Date | Owner |
|---|---|---|---|---|
| | | | | |
