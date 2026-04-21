# Use Cases

We identified 8 scenarios. **Decision made (2026-04-11, D-001):** Use Case 1 — Airports, anchored to LEMD.

The original Scenario 8 framing (three-class intent classification) was rejected — no labeled hostile dataset exists. Reframed as anomaly detection: learn what normal authorized flight looks like near LEMD, flag deviations. See [decisions/README.md](../decisions/README.md) for full rationale.

---

## Comparison at a glance

| # | Scenario | Core problem | Detection window needed | Data availability |
|---|---|---|---|---|
| 1 | Airports | Unauthorized drone forces runway closure | 5-15 min | Good (OpenSky, ADS-B) |
| 2 | Critical infrastructure | Drone as recon/attack vector on energy/ports | 10-30 min | Medium |
| 3 | Prisons | Contraband delivery by drone | 3-5 min (anticipate drop zone) | Limited |
| 4 | Borders & coast | Persistent surveillance of trafficking routes | Ongoing | Medium |
| 5 | Mass events | Drone risk in dense, temporary environments | 2-5 min | Limited |
| 6 | Military / gov buildings | Hostile drone recon or attack | 10-20 min | Limited |
| 7 | Natural reserves | Anti-poaching, remote area monitoring | Ongoing | Limited |
| 8 | Urban environments | Distinguishing authorized from unauthorized drones | Real-time | Good (visual datasets) |

---

## Use Case Detail

### 1. Airports

**The problem:** A drone doesn't need to hit a plane to cause damage — its presence alone can halt operations. A single unconfirmed sighting can close a runway for 30+ minutes ($50k+/hour in losses). The decision to close falls on ATC with very little information.

**What the system adds:** Trajectory prediction gives ATC 5-15 minutes of lead time and a confidence score, turning "drone sighted somewhere nearby" into "drone projected to enter runway zone in 8 minutes, 74% confidence."

**Data:** OpenSky ADS-B covers cooperative drones well over airports. Illegal drones won't appear, but their *absence* from ADS-B is itself a signal when combined with visual or RF.

**Best suited for:** ADS-B trajectory approach, or ADS-B + visual fusion.

---

### 2. Critical Infrastructure

**The problem:** Energy plants, ports, telecom nodes, water systems face a new low-cost threat surface. A drone can perform reconnaissance or deliver a payload. A single isolated signal is rarely enough to distinguish threat from false alarm.

**What the system adds:** Multi-signal fusion to reduce false positives and provide intent classification (is it circling? approaching? hovering?).

**Best suited for:** Multi-modal fusion (RF + visual). Harder to get real data.

---

### 3. Prisons

**The problem:** Drones are used to deliver drugs, phones, and weapons over prison walls. The challenge is not just detecting the flight but anticipating the drop point early enough to intercept.

**What the system adds:** Trajectory prediction to estimate where the drone will descend, giving guards time to position.

**Best suited for:** RF signal detection + trajectory prediction. Very concrete, demonstrable use case.

---

### 4. Borders & Coast

**The problem:** Vast areas, limited personnel. Drones support trafficking routes (recon, small payload drops). The challenge is separating relevant signals from high operational noise.

**Best suited for:** Long-range radar / ADS-B + anomaly detection over time. Harder to prototype.

---

### 5. Mass Events

**The problem:** Concerts, stadiums, institutional events — dense, temporary, and with mixed drone authorization (press drones, official drones, illegal drones all in the same airspace). Need fast classification, not just detection.

**What the system adds:** Real-time classification of cooperative vs. unauthorized vs. suspicious.

**Best suited for:** Visual detection + ADS-B cross-check.

---

### 6. Military / Government Buildings

**The problem:** Perimeter defense against non-cooperative drones that may be conducting surveillance or testing vulnerabilities. Higher stakes than most scenarios.

**Best suited for:** Multi-modal. Hard to get real data; sensitive.

---

### 7. Natural Reserves / Anti-poaching

**The problem:** Remote areas, few resources. A drone or suspicious aerial activity may indicate poaching or illegal intrusion, especially at night.

**Best suited for:** Thermal/IR visual detection. Niche but well-defined problem.

---

### 8. Urban Environments

**The problem:** Not all drones are illegal — urban airspace is increasingly busy. The hard part is distinguishing cooperative (authorized, broadcasting), negligent (no transponder, not hostile), and hostile drones in a noisy environment.

**What the system adds:** Layered classification using registration status, flight behavior, and proximity to restricted zones.

**Best suited for:** ADS-B + visual + geofencing. Good data availability. Most general case.

---

## Team decision

**Selected: Use Case 1 — Airports (LEMD)** — decided 2026-04-11, whole team. Logged as D-001 in [decisions/README.md](../decisions/README.md).
