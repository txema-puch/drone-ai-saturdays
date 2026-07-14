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
export type ModelState = "not_loaded" | "loading" | "failed" | "ready";

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
  evaluation_enabled?: boolean;
  model_state?: ModelState;
  model_retry_remaining?: number;
  release_id?: string;
  model_id?: string;
  schema_version?: number;
}

export interface FlightSummary {
  case_id: string;
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
  worst_case_id: string;
  worst_case_ref: string;
  worst_segment_id: string;
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
  behavioral_worst_case_id: string | null;
  behavioral_worst_case_ref: string | null;
  segments: FlightSummary[];
}

export type OperationQueueSegment = Pick<
  FlightSummary,
  "case_id" | "case_ref" | "segment_id" | "score" | "pct" | "label" | "anomalous" | "review_lane"
>;

export interface OperationQueueSummary extends Omit<OperationSummary, "segments"> {
  segments: OperationQueueSegment[];
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
  case_id: string;
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
  case_id: string;
  kind: string;
  intensity: number; // 0 = clean … 1 = the full §6 anomaly
  onset: number; // fraction of the scored segment where the anomaly begins
}

export interface SimulationResult {
  case_id: string;
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

export interface ApiFieldIssue {
  field: string;
  message: string;
  code?: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code = "request_failed",
    message = `Request failed (${status})`,
    public readonly fields: readonly ApiFieldIssue[] = [],
    public readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function hasApiStatus(error: unknown, status: number): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    (error as { status?: unknown }).status === status
  );
}

export function hasApiCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === code
  );
}

function retryAfterSeconds(response: Response): number | null {
  const value = response.headers?.get?.("Retry-After");
  if (!value) return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function asFieldIssues(value: unknown): ApiFieldIssue[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const field = "field" in item ? (item as { field?: unknown }).field : undefined;
    const message = "message" in item ? (item as { message?: unknown }).message : undefined;
    const code = "code" in item ? (item as { code?: unknown }).code : undefined;
    if (typeof field !== "string" || typeof message !== "string") return [];
    return [{ field, message, ...(typeof code === "string" ? { code } : {}) }];
  });
}

const MAX_ERROR_BODY_BYTES = 64 * 1024;

async function boundedErrorPayload(response: Response): Promise<unknown> {
  const declared = Number(response.headers?.get?.("Content-Length"));
  if (Number.isFinite(declared) && declared > MAX_ERROR_BODY_BYTES) {
    await response.body?.cancel().catch(() => undefined);
    return null;
  }
  const reader = response.body?.getReader?.();
  if (!reader) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_ERROR_BODY_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  } finally {
    reader.releaseLock();
  }
}

async function apiError(response: Response): Promise<ApiError> {
  const payload = await boundedErrorPayload(response);
  const root = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {};
  const detail = typeof root.detail === "object" && root.detail !== null
    ? root.detail as Record<string, unknown>
    : root;
  const code = typeof detail.code === "string" ? detail.code : "request_failed";
  const message = typeof detail.message === "string" && detail.message.trim()
    ? detail.message
    : `Request failed (${response.status})`;
  return new ApiError(
    response.status,
    code,
    message,
    asFieldIssues(detail.fields),
    retryAfterSeconds(response),
  );
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) throw await apiError(response);
  return response.json() as Promise<T>;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson(path, { signal });
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
): Promise<OperationQueueSummary[]> {
  return getJson(`/operations?limit=${limit}&order=${order}`, signal);
}

export function getOperation(
  operationRef: string,
  signal?: AbortSignal,
): Promise<OperationSummary> {
  return getJson(`/operations/${encodeURIComponent(operationRef)}`, signal);
}

export function getFlight(caseId: string, signal?: AbortSignal): Promise<FlightDetail> {
  return getJson(`/flights/${encodeURIComponent(caseId)}`, signal);
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
  return requestJson("/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
}

export interface ModelPreparation {
  model_state: ModelState;
  model_retry_remaining: number;
}

export interface EvaluationRejection {
  code: string;
  message: string;
  count: number;
}

/** Uploaded evidence is deliberately not a FlightDetail: it has no label, case,
 * operation, report, or neighboring-operation fields. */
export interface EvaluationResult {
  evaluation_ref: string;
  segment_id: string;
  model_status: "above_threshold" | "below_threshold";
  path: PathPoint[];
  reconstructed: PathPoint[];
  scores: number[];
  window_score: number;
  pct: number;
  threshold: number;
  step_threshold: number;
  valid_steps: number;
  n_steps: number;
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
  center: { lat: number; lon: number };
  step_seconds: number;
}

export interface EvaluationResponse {
  release_id: string;
  model_id: string;
  dataset_digest: string;
  upload_sha256: string;
  raw_rows: number;
  derived_rows: number;
  accepted_rows: number;
  accepted_segments: number;
  rejected_segments: number;
  duplicate_rows_collapsed: number;
  rejection_reasons: EvaluationRejection[];
  results: EvaluationResult[];
}

export function prepareModel(signal?: AbortSignal): Promise<ModelPreparation> {
  return requestJson("/model/prepare", { method: "POST", signal });
}

export function evaluateFile(file: File, signal?: AbortSignal): Promise<EvaluationResponse> {
  const body = new FormData();
  body.append("file", file);
  return requestJson("/evaluations", { method: "POST", body, signal });
}
