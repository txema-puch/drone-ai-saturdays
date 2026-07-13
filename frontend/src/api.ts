/*
 * Typed client for the post-hoc audit serve layer (backend/serve/app.py on
 * :8077 in dev, proxied at /api). Response shapes extend SADAR's original
 * api.ts contract (FlightSummary / FlightDetail / PathPoint / MetricRow) with
 * the fields our serve adds: segment_id, label, pct, band, feature_attribution.
 */

const BASE = "/api";

export type Label = "normal" | "go_around" | "emergency";
export type AssessmentState = "reviewable" | "data_quality_conflict" | "insufficient_data" | "coverage_limited";
export type ReviewLane = "behavioral" | "data_quality" | "coverage";

export interface Health {
  status: string;
  mode: string;
  segments: number;
  operations: number;
  real_anomalies: number;
  anomalous_at_threshold: number;
  threshold: number;
  step_threshold: number;
  cases_available: number;
  reviewable: number;
  data_quality_conflicts: number;
  insufficient_data: number;
  coverage_limited: number;
}

export interface FlightSummary {
  id: number;
  case_ref: string;
  operation_ref: string;
  segment_id: string;
  score: number;
  pct: number;
  band: string;
  anomalous: boolean;
  label: Label;
  has_case: boolean;
  n_steps: number;
  truncated: boolean; // segment longer than the T=260 window → terminal phase not scored
  terminal_op: boolean; // genuine LEMD terminal operation (low+close in the scored window)
  assessment_state: AssessmentState;
  behavioral_verdict: "reviewable" | "not_assessable";
  review_lane: ReviewLane;
  data_quality_flags: readonly string[];
  valid_steps: number;
  observed_fraction: number;
  max_altitude_jump_m: number;
  max_implied_vertical_rate_mps: number;
  max_implied_ground_speed_mps: number;
}

export interface OperationSummary {
  operation_ref: string;
  segment_count: number;
  flagged_segment_count: number;
  worst_score: number;
  worst_pct: number;
  worst_band: string;
  worst_case_ref: string;
  worst_segment_id: string;
  worst_segment_id_num: number;
  worst_has_case: boolean;
  labels_seen: Label[];
  has_confirmed_event: boolean;
  has_model_flag_unlabeled: boolean;
  terminal_segment_count: number;
  truncated_segment_count: number;
  data_quality_summary: "mostly terminal" | "mixed" | "likely artifact";
  assessment_summary: "reviewable" | "mixed evidence" | "not assessable";
  behavioral_assessment: "reviewable" | "not_assessable";
  behavioral_flagged_segment_count: number;
  reviewable_segment_count: number;
  not_assessable_segment_count: number;
  data_quality_segment_count: number;
  coverage_limited_segment_count: number;
  behavioral_worst_score: number | null;
  behavioral_worst_pct: number | null;
  behavioral_worst_band: string | null;
  behavioral_worst_case_ref: string | null;
  behavioral_worst_segment_id_num: number | null;
  segments: FlightSummary[];
}

export interface PathPoint {
  lat: number;
  lon: number;
  alt: number;
  t?: number;
}

/** Per-step measured channels (physical units), keyed by feature name. */
export type Channels = Record<string, number[]>;

export interface FlightDetail {
  id: number;
  case_ref: string;
  operation_ref: string;
  segment_id: string;
  label: Label;
  path: PathPoint[];
  reconstructed: PathPoint[];
  context_path: { lat: number; lon: number }[]; // full trajectory (all sibling segments)
  n_siblings: number;
  scores: number[];
  window_score: number;
  pct: number;
  band: string;
  anomalous: boolean;
  threshold: number;
  step_threshold: number;
  valid_steps: number;
  n_steps: number;
  truncated: boolean;
  terminal_op: boolean;
  assessment_state: AssessmentState;
  behavioral_verdict: "reviewable" | "not_assessable";
  review_lane: ReviewLane;
  data_quality_flags: readonly string[];
  observed_fraction: number;
  max_altitude_jump_m: number;
  max_implied_vertical_rate_mps: number;
  max_implied_ground_speed_mps: number;
  feature_attribution: Record<string, number>;
  channels: Channels;
  report: string | null; // pre-generated LLM analysis (build-time), or null if not generated
  report_model: string | null;
  center: { lat: number; lon: number };
  step_seconds: number;
  operation_segments: FlightSummary[];
}

export interface MetricRow {
  model: string;
  real_roc_auc: number;
  real_pr_auc: number | null;
  synthetic_mean_roc_auc: number | null;
  synthetic_per_type: Record<string, number>;
}

export interface Metrics {
  selected_model: string | null;
  results: MetricRow[];
  notes?: Record<string, string>;
}

export type Order = "anomalous" | "normal" | "typical";

export interface SimulationRequest {
  id: number;
  kind: string;
  intensity: number; // 0 = clean … 1 = the full §6 anomaly
  onset: number; // fraction of the scored segment where the anomaly begins
}

export interface SimulationResult {
  id: number;
  segment_id: string;
  kind: string;
  intensity: number;
  onset: number;
  onset_index: number;
  path: PathPoint[];
  channels: Channels;
  scores: number[];
  window_score: number;
  original_score: number;
  pct: number;
  band: string;
  anomalous: boolean;
  threshold: number;
  step_threshold: number;
  valid_steps: number;
  center: { lat: number; lon: number };
  step_seconds: number;
}

export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(`request failed: ${status}`);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { signal });
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return getJson("/health", signal);
}

export function getFlights(
  limit = 80,
  order: Order = "anomalous",
  signal?: AbortSignal,
): Promise<FlightSummary[]> {
  return getJson(`/flights?limit=${limit}&order=${order}`, signal);
}

export function getOperations(
  limit = 5000,
  order: Order = "anomalous",
  signal?: AbortSignal,
): Promise<OperationSummary[]> {
  return getJson(`/operations?limit=${limit}&order=${order}`, signal);
}

export function getOperation(
  operationRef: string,
  signal?: AbortSignal,
): Promise<OperationSummary> {
  return getJson(`/operations/${encodeURIComponent(operationRef)}`, signal);
}

export function getFlight(id: number, signal?: AbortSignal): Promise<FlightDetail> {
  return getJson(`/flights/${id}`, signal);
}

export function getMetrics(signal?: AbortSignal): Promise<Metrics> {
  return getJson("/metrics", signal);
}

/** Analyst what-if: inject a synthetic anomaly into the real segment and re-score it
 *  against the same frozen model. Returns the perturbed segment for overlay. */
export async function simulate(
  request: SimulationRequest,
  signal?: AbortSignal,
): Promise<SimulationResult> {
  const response = await fetch(`${BASE}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw new ApiError(response.status);
  return response.json() as Promise<SimulationResult>;
}
