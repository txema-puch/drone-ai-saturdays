# 02 — Metrics explained

## The question

How do we know the model is good? "It seems to work" is not enough; "we got 92%" of *what* matters.

This file builds up the metric stack from first principles, the same way we worked through it in the design conversation. If you skim, the takeaway table is at the bottom.

## Step 1 — The four outcomes

Every prediction the model makes — once we threshold its anomaly score — is one of four things:

| | Model says "anomalous" | Model says "normal" |
|---|---|---|
| **Actually anomalous** | TP — caught it | FN — missed it |
| **Actually normal** | FP — false alarm | TN — silent, fine |

In our LEMD context:
- TP: a real hostile drone gets flagged → ATC alerted, intercepted
- FN: a real hostile drone slips through → potential incident
- FP: a regular Iberia flight gets flagged → ATC investigates, finds nothing, alert fatigue
- TN: a regular Iberia flight doesn't get flagged → silent, good

Every metric we use is a different summary of this 2×2 table.

## Step 2 — Why "accuracy" lies

A typical day at LEMD might have 1000 normal flights and 5 anomalies (real anomaly rate is even lower; we're being generous). A trivial model that says *"everything is normal, always"* gets:

- TP = 0, FN = 5, FP = 0, TN = 1000
- Accuracy = (TP + TN) / total = 1000 / 1005 = **99.5%**

Catches zero anomalies. Useless. But if we were optimizing for accuracy, the model would learn exactly this — predict the majority class always.

This is why anomaly detection (and any imbalanced classification) cannot use accuracy as a metric. The class imbalance — 1000:5 — makes accuracy meaningless. We need metrics that focus on the rare positive class.

## Step 3 — Precision and recall

Two metrics, two questions:

```
                TP                          "Of the flights I flagged,
precision  =  ────────                       how many were actually
              TP + FP                        anomalous?"

                TP                          "Of the anomalies that
recall     =  ────────                       happened, how many
              TP + FN                        did I catch?"
```

The trivial "always normal" model: precision = 0/0 (undefined), recall = 0/5 = 0%. Both bad.

The opposite extreme — flag everything (1005 alerts, 5 of them right): precision = 5/1005 ≈ 0.5%, recall = 5/5 = 100%. Recall perfect, precision terrible.

These two metrics pull against each other. **Where you set the threshold determines which one wins.**

## Step 4 — F-beta: collapsing precision and recall into one number

We need a single number for decisions. F1 is the standard:

```
                precision · recall
F1  =  2 · ─────────────────────────
              precision + recall
```

That's the **harmonic mean**, not the arithmetic mean. Crucially, F1 punishes imbalance. If either precision or recall is near zero, F1 is near zero — even if the other is perfect. The arithmetic mean would let a model "fake it" by maxing one and ignoring the other.

But F1 weights precision and recall equally. For our problem, they're not equal. Missing a hostile drone (FN) is operationally worse than annoying ATC (FP). The F-beta family generalizes:

```
                                 precision · recall
F_β  =  (1 + β²) · ─────────────────────────────────────
                    (β² · precision) + recall
```

| β | Name | Recall is weighted... | Use when... |
|---|---|---|---|
| 0.5 | F0.5 | half as much as precision | False alarms are the worse error (spam filters) |
| 1.0 | F1 | equally to precision | No strong asymmetry, balanced summary |
| **2.0** | **F2** | **twice as much as precision** | **Missing positives is worse (drone detection, fraud, cancer screening)** |

For us: F2.

## Step 5 — AUROC, the threshold-free metric

So far every metric we've discussed depends on the threshold. But the model produces a continuous score, and we can pick any threshold we want. How do we judge the model's *separating power* — its ability to rank anomalies higher than normals — without committing to a threshold?

ROC curve: plot True Positive Rate (recall) on the y-axis, False Positive Rate (`FP / (FP + TN)`) on the x-axis. Each threshold is one point. Sweep all thresholds → a curve.

```
TPR
1.0│           ┌─────────  ← perfect
   │         ┌─┘
   │       ┌─┘             ← good model
   │     ┌─┘
0.5│   ┌─┘    ╱╱╱           ← random
   │ ┌─┘  ╱╱╱
   │┌┘ ╱╱╱
0.0└─────────────────────  FPR
   0.0           1.0
```

**AUROC** is just the area under that curve. It has a beautiful interpretation:

> **AUROC is the probability that, if you pick a random anomaly and a random normal flight, the model gives the anomaly a higher score.**

So AUROC = 0.85 means: 85% of the time, anomalies score higher than normals. That's a property of the model's *ranking*, independent of where you put the threshold. Random model → 0.5. Perfect model → 1.0.

## Step 6 — Why we still report PR-AUC

AUROC has a known weakness on heavily imbalanced data. The `FP + TN` denominator in FPR gets dominated by `TN` when normals vastly outnumber anomalies, so FPR stays low even when precision is mediocre.

PR-AUC (area under the precision-recall curve) uses precision instead, which doesn't suffer that dilution. We compute it alongside AUROC as a sanity check. If AUROC and PR-AUC tell different stories, that's a finding worth investigating.

## Step 7 — The four-slot stack

Putting it all together, our metrics serve four different purposes:

| Slot | Metric | Question it answers |
|---|---|---|
| **Primary** | AUROC > 0.85 | Is the model good at separating anomalies from normals? |
| **Operational** | F2 at chosen threshold | Is it useful at the deployment operating point? |
| **Guardrail** | FPR ≤ 15% | Is the false-alarm rate acceptable? Hard fail if not. |
| **Sanity** | PR-AUC | Is the AUROC headline number being flattered by imbalance? |

The guardrail deserves a sentence. Without it, the other metrics can be gamed by a lax threshold — AUROC of 0.95 and F2 of 0.90 mean nothing if the model alerts on 30% of normal flights. The guardrail constrains the operating threshold; if FPR > 15% at our chosen threshold, the project does not ship, regardless of how good the headline numbers are.

All four metrics get computed twice: once for the LSTM Autoencoder (our primary model), once for the Isolation Forest baseline (the comparison floor). A 0.88 AUROC LSTM is meaningless if IF gets 0.87 — so we always report both.

## The takeaway

Picking a metric isn't a final-page detail. It's an upfront commitment that shapes everything: what we optimize, what we report, what we ship, what counts as success. The four-slot stack is honest about doing four different things — measuring quality (AUROC), measuring deployment (F2), constraining safety (FPR), and sanity-checking the headline (PR-AUC) — instead of pretending one number tells the whole story.

## Slide hooks

- "Accuracy on imbalanced data is a lie. Here's how it lies."
- "Our four metrics each answer a different question."
- "AUROC tells you the model can rank. F2 tells you it can deploy."
- "The 15% FPR cap is what makes the system shippable."
