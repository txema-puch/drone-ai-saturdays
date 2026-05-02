# Week 5 — Writeup + Presentation

**Status:** Not started
**Must ship by end of week:** v1.0 tag on GitHub, demo rehearsed twice, each person has their writeup section done

---

## Objective

No new features. No new model runs. This week is entirely about communicating
what you built clearly enough that someone who wasn't in the room can understand it.

The demo must be rehearsed at least twice — once midweek (Wednesday), once before presentation.

---

## Rule for Week 5

**If you find a bug during Week 5:**
- Minor (cosmetic, wrong label): fix it
- Major (model gives wrong results, crashes): flag in Discord immediately
  - Decision: is it worth fixing or do we note it as a limitation? Team decides together.

**Do not** start new experiments, tune hyperparameters, or change model architecture.

---

## Tasks

### Writeup

The writeup structure (adapt to course format):

| Section | What it covers |
|---------|----------------|
| Introduction & Problem | Why drone detection matters, the LEMD use case, what the system does in plain language |
| Data | OpenSky, what we queried, how many tracks, distributions, filtering choices |
| Model | Isolation Forest baseline, LSTM Autoencoder architecture, training setup, why these choices |
| Evaluation & Results | Metrics table, PR curve, ablation, success criteria, honest limitations |

- [ ] Each person drafts their section and posts it in Discord by Wednesday
- [ ] Every other person reads each section and leaves one comment
  - Is the logic clear? Is there a claim that needs a number or citation?
- [ ] Integrate feedback before Friday
- [ ] All four sections integrated into one document

**What makes a good writeup section:**
- State what you did, why you did it, and what you found
- Include one concrete number per paragraph
- Acknowledge what didn't work or what you'd do differently
- No filler. No "this project was a great learning experience."

### Demo rehearsal 1 — Wednesday
- [ ] Run the full demo from scratch (cold start: open Streamlit, mount Drive if on Colab)
- [ ] Time it: does it run in under 3 minutes for the core flow?
  - Core flow: show normal trajectory → show anomalous trajectory → explain the score difference → show identity gate status
- [ ] What breaks? Write it down. Fix before rehearsal 2.

### Demo rehearsal 2 — Before presentation
- [ ] Run again — everything from rehearsal 1 must be fixed
- [ ] Designate one person to talk, one person to drive (mouse/keyboard)
  - The driver does not speak. The speaker does not touch the keyboard.
  - This prevents "let me just quickly show you..." tangents
- [ ] Practice answering: "Why not just use a camera?" and "How would this work with real illegal drones?"

### Repo cleanup
- [ ] `README.md` at the repo root: write or update it so a new person understands the project in 2 minutes
  - What it does, how to run the demo, where the data lives, link to the writeup
- [ ] Remove any debug print statements or commented-out code from notebooks
- [ ] Verify all four notebooks run clean end-to-end with a fresh Colab session
  - Do this by actually running them in a new Colab tab — not just "I think it should work"
- [ ] Push model weights link to README (Hugging Face Hub or Google Drive public link)
- [ ] Tag v1.0: `git tag v1.0 && git push origin v1.0`

---

## Done when

- [ ] All four writeup sections integrated into one document
- [ ] Demo rehearsed twice, timing under 3 minutes for core flow
- [ ] `README.md` explains the project clearly
- [ ] v1.0 tag pushed to GitHub
- [ ] Model weights accessible via public link in README
