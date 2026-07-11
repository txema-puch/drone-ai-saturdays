/*
 * Pure presentation helpers — severity colors, bands, score formatting, the
 * segment-id → timestamp parse. Kept dependency-free and side-effect-free so
 * they're trivially unit-testable (the one place subtle bugs hide).
 */

import type { Label } from "../api";

/** Operating threshold (frozen, never retuned). Served by the backend too;
 *  this is the fallback for offline/sample render. */
export const THRESHOLD = 0.222;
export const SCORE_MAX = 2.0; // sparkbar full-scale

/** Trajectory/score color by raw RE: high (≥1) → red, flagged (≥thr) → amber,
 *  else green. Mirrors the prototype's col(). */
export function scoreColor(score: number, threshold = THRESHOLD): string {
  if (score >= 1.0) return "var(--red)";
  if (score >= threshold) return "var(--amber)";
  return "var(--green)";
}

/** Percentile band color (DESIGN.md severity bands). */
export function pctColor(pct: number): string {
  if (pct >= 95) return "var(--red)";
  if (pct >= 80) return "var(--amber)";
  if (pct >= 50) return "var(--accent)";
  return "var(--green)";
}

/** Plain-language severity band from percentile (DESIGN.md). */
export function band(pct: number): string {
  if (pct >= 95) return "highly anomalous";
  if (pct >= 80) return "elevated";
  if (pct >= 50) return "upper-normal";
  return "normal range";
}

/** Sparkbar fill width as a clamped percentage of full-scale. */
export function sparkWidth(score: number, max = SCORE_MAX): number {
  return Math.min(100, Math.max(0, (score / max) * 100));
}

/** Segment ids look like `502ce6_1543855510#1` — the middle field is a unix
 *  epoch (seconds). Returns "YYYY-MM-DD HH:MM UTC" or "" if unparseable. */
export function parseEpoch(segmentId: string): string {
  const m = segmentId.match(/_(\d+)#/);
  if (!m) return "";
  const d = new Date(Number(m[1]) * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** The 6-hex aircraft prefix of a segment id. */
export function aircraftOf(segmentId: string): string {
  return segmentId.slice(0, 6);
}

/** Display label for a category stamp (go_around → "go-around"). */
export function labelText(label: Label): string {
  return label.replace("_", "-");
}

/** The measured channels the temporal panel can trace over time. `key` matches the
 *  backend `channels` dict; altitude is the default (the map's missing third axis). */
export interface ChannelMeta {
  key: string;
  label: string;
  unit: string;
}
export const CHANNELS: ChannelMeta[] = [
  { key: "baroaltitude", label: "Altitude", unit: "m" },
  { key: "velocity", label: "Ground speed", unit: "m/s" },
  { key: "vertrate", label: "Vert rate", unit: "m/s" },
  { key: "dist_to_runway_m", label: "Dist to runway", unit: "m" },
];
