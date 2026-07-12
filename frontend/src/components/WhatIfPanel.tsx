import { useState } from "react";

import { simulate, type SimulationResult } from "../api";

/** Our inject vocabulary (D-012). zone_violation is out-of-remit for the shipped
 *  detector but remains a valid sandbox injectable. */
const KINDS = [
  "sustained_loiter",
  "altitude_high",
  "final_approach_intercept",
  "speed_spike",
  "zone_violation",
] as const;

type Status = "idle" | "pending" | "error";

interface Props {
  flightId: number;
  active: boolean;
  onResult: (r: SimulationResult) => void;
  onClear: () => void;
}

/** Analyst what-if (deliberately demoted — secondary to the case evidence). Injects one
 *  §6 anomaly into the real segment and re-scores it against the same frozen model;
 *  intensity interpolates clean → the full calibrated anomaly. Reframed from SADAR's
 *  "detection latency" to "where in the segment does it diverge." A sandbox — the result
 *  overlays on the charts and never edits the stored case. */
export default function WhatIfPanel({ flightId, active, onResult, onClear }: Props) {
  const [kind, setKind] = useState<string>(KINDS[0]);
  const [intensity, setIntensity] = useState(100);
  const [onset, setOnset] = useState(50);
  const [status, setStatus] = useState<Status>("idle");

  async function run() {
    setStatus("pending");
    try {
      const r = await simulate({ id: flightId, kind, intensity: intensity / 100, onset: onset / 100 });
      setStatus("idle");
      onResult(r);
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="sans" style={{ display: "flex", flexDirection: "column", gap: 11, fontSize: 14, color: "var(--mut)" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ color: "var(--ink)" }}>Anomaly type</span>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          style={{
            background: "var(--panel2)",
            color: "var(--ink)",
            border: "1px solid var(--edge)",
            borderRadius: 7,
            padding: "7px 9px",
            fontFamily: "inherit",
          }}
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ display: "flex", justifyContent: "space-between", color: "var(--ink)" }}>
          <span>Intensity</span>
          <span className="mono">{intensity}%</span>
        </span>
        <input type="range" min={0} max={100} value={intensity} onChange={(e) => setIntensity(Number(e.target.value))} style={{ width: "100%", accentColor: "var(--accent)" }} />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ display: "flex", justifyContent: "space-between", color: "var(--ink)" }}>
          <span>Onset</span>
          <span className="mono">{onset}%</span>
        </span>
        <input type="range" min={0} max={100} value={onset} onChange={(e) => setOnset(Number(e.target.value))} style={{ width: "100%", accentColor: "var(--accent)" }} />
      </label>

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={run}
          disabled={status === "pending"}
          style={{ flex: 1, background: "transparent", border: "1px solid var(--accent)", color: "var(--accent)", borderRadius: 7, padding: 9, letterSpacing: "0.06em" }}
        >
          {status === "pending" ? "RE-SCORING…" : "RE-SCORE PERTURBED SEGMENT →"}
        </button>
        {active && (
          <button
            onClick={onClear}
            style={{ background: "transparent", border: "1px solid var(--edge)", color: "var(--mut)", borderRadius: 7, padding: "9px 14px", letterSpacing: "0.06em" }}
          >
            CLEAR
          </button>
        )}
      </div>

      <p style={{ fontSize: 13, lineHeight: 1.5, margin: 0 }}>
        {status === "error"
          ? "Could not reach the re-score endpoint."
          : "What-if only. Injects a synthetic anomaly into this real segment and re-scores it against the same frozen model — the perturbed track + error overlay the charts above (magenta). For understanding the detector, not a live alert."}
      </p>
    </div>
  );
}
