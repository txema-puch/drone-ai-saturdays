const BASE = "/api";
const MAX_ERROR_BODY_BYTES = 64 * 1024;

export type ApproachStatus =
  | "review_required"
  | "partial_observation"
  | "criteria_observed"
  | "not_assessable";

export type ApproachCriterionStatus = "review_required" | "within_limit" | "not_observed";

export interface Health {
  status: string;
  mode: string;
  release_id?: string;
  schema_version?: number | string;
  attempts?: number;
  operations?: number;
  demo_attempts?: number;
  demo_operations?: number;
  demo_data_origin?: "synthetic";
  research_data_origin?: "aggregate_real";
  evaluation_data_handling?: "ephemeral_not_retained";
  source_commit?: string;
  demo_status_counts?: Partial<Record<ApproachStatus, number>>;
  demo_outcome_counts?: Record<string, number>;
  evaluation_enabled?: boolean;
  context_enabled?: boolean;
  qualification?: string | null;
  allowed_role?: string | null;
  blocked_uses?: string[];
  status_counts?: Partial<Record<ApproachStatus, number>>;
  reference?: {
    status?: string;
    id?: string;
    artifact_sha256?: string;
  } | null;
}

export interface ApproachCoverage {
  observed_samples?: number;
  expected_samples?: number;
  observed_fraction?: number;
  [key: string]: number | string | boolean | null | undefined;
}

export interface ApproachEvidenceSpan {
  start_index?: number;
  end_index?: number;
  start_time: number;
  end_time: number;
  worst_index?: number;
  worst_time?: number;
  value?: number;
  limit?: number;
  unit?: string;
  along_track_m?: number;
  [key: string]: number | string | boolean | null | undefined;
}

export interface ApproachCriterion {
  name: string;
  status: ApproachCriterionStatus;
  severity?: "low" | "medium" | "high";
  observed_samples?: number;
  evidence: ApproachEvidenceSpan[];
  reason?: string;
  reference_source?: string;
  altitude_bias_source?: string;
}

export interface ApproachPathPoint {
  lat: number;
  lon: number;
  alt?: number;
  time?: number;
  along_track_m?: number;
  cross_track_m?: number;
  height_above_threshold_m?: number;
  ground_speed_mps?: number;
  vertical_rate_mps?: number;
  track_offset_deg?: number;
  observed?: boolean;
}

export interface ApproachSummary {
  attempt_id: string;
  operation_ref: string;
  data_origin: "synthetic";
  scenario_id: string;
  scenario_title: string;
  teaching_goal: string;
  status: ApproachStatus;
  direction?: string | null;
  runway?: string | null;
  geometry_runway?: string | null;
  runway_specificity?: string | null;
  runway_confidence?: number | null;
  runway_score_margin?: number | null;
  failed_criteria: string[];
  outcome?: string | null;
  landing_outcome?: {
    available: boolean;
    reason: string | null;
    evidence_end_along_track_m: number;
  };
  observed_samples?: number;
  coverage?: number | ApproachCoverage | null;
  start_time?: number | null;
  end_time?: number | null;
  reasons?: string[];
  quality_flags?: string[];
}

export interface ApproachResearchBenchmark {
  status?: string;
  model_id?: string;
  segment_id?: string;
  score?: number;
  percentile?: number;
  coverage?: string | ApproachCoverage;
  note?: string;
}

export interface ApproachDetail extends ApproachSummary {
  path: ApproachPathPoint[];
  criteria: ApproachCriterion[];
  quality?: Record<string, unknown> | null;
  altitude_reference?: Record<string, unknown> | null;
  maneuvers?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown> | null;
  geometry?: Record<string, unknown> | null;
  reference?: Record<string, unknown> | null;
  context?: {
    weather?: Record<string, unknown> | null;
    aircraft?: Record<string, unknown> | null;
    unavailable?: string[];
  } | null;
  schema_version?: string;
  engine_version?: string;
  demo_clock?: boolean;
  research_benchmark?: ApproachResearchBenchmark | null;
}

export interface ApproachOperation {
  operation_ref: string;
  data_origin: "synthetic";
  scenario_id: string;
  scenario_title: string;
  teaching_goal: string;
  attempts: ApproachSummary[];
}

export type AggregateCell = number | "<10" | "suppressed";

export interface ResearchCohort {
  cohort_id: string;
  period: string;
  role: string;
  rows: number | null;
  operations: number;
  operations_with_attempts: number | null;
  attempts: number;
  assessable_attempts: number;
  abstention_rate: number | null;
  review_rate_among_assessable: number | null;
  status_counts: Record<string, AggregateCell>;
  outcome_counts: Record<string, AggregateCell> | null;
  criterion_status_counts: Record<string, Record<string, AggregateCell>>;
  interpretation_limits: string[];
}

export interface ScreeningHoldoutFinding {
  cohort_id: string;
  policy: string;
  reason_counts: Record<string, AggregateCell>;
  criterion_status_counts: Record<string, Record<string, AggregateCell>>;
  interpretation_limits: string[];
}

export interface ContextValidationFinding {
  cohort_id: string;
  decision: string;
  base_review_rate_among_assessable: number | null;
  context_review_rate_among_assessable: number | null;
  base_status_counts: Record<string, AggregateCell>;
  context_status_counts: Record<string, AggregateCell>;
  base_criterion_status_counts: Record<string, Record<string, AggregateCell>>;
  context_criterion_status_counts: Record<string, Record<string, AggregateCell>>;
  review_overlap: Record<string, AggregateCell>;
  status_transition_counts: Record<string, AggregateCell>;
  context_coverage: Record<string, number | null>;
  interpretation_limits: string[];
}

export interface ResearchEvidence {
  schema_version: string;
  basis: "real_opensky_research_data";
  generated_at: string;
  qualification: string;
  allowed_role: string;
  blocked_uses: string[];
  limitations: string[];
  cohorts: ResearchCohort[];
  findings: {
    screening_holdout: ScreeningHoldoutFinding;
    context_validation: ContextValidationFinding;
  };
  data_access: {
    provider: string;
    access_url: string;
    terms_url: string;
    citation: string;
    publication_notice_status: string;
    publication_notice_date: string | null;
  };
}

export interface ApproachFilters {
  limit?: number;
  status?: string;
  direction?: string;
  criterion?: string;
  outcome?: string;
  quality?: string;
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
  return typeof error === "object" && error !== null && "status" in error
    && (error as { status?: unknown }).status === status;
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
  return new ApiError(
    response.status,
    typeof detail.code === "string" ? detail.code : "request_failed",
    typeof detail.message === "string" && detail.message.trim()
      ? detail.message
      : `Request failed (${response.status})`,
    asFieldIssues(detail.fields),
    retryAfterSeconds(response),
  );
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) throw await apiError(response);
  return response.json() as Promise<T>;
}

function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson(path, { signal });
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return getJson("/health", signal);
}

export function getEvidence(signal?: AbortSignal): Promise<ResearchEvidence> {
  return getJson("/evidence", signal);
}

function approachQuery(filters: ApproachFilters): string {
  const params = new URLSearchParams();
  params.set("limit", String(filters.limit ?? 500));
  for (const key of ["status", "direction", "criterion", "outcome"] as const) {
    const value = filters[key];
    if (value && value !== "all") params.set(key, value);
  }
  return params.toString();
}

export async function getApproaches(
  filters: ApproachFilters = {},
  signal?: AbortSignal,
): Promise<ApproachSummary[]> {
  const payload = await getJson<ApproachSummary[] | { items: ApproachSummary[] }>(
    `/approaches?${approachQuery(filters)}`,
    signal,
  );
  return Array.isArray(payload) ? payload : payload.items;
}

export function getApproach(attemptId: string, signal?: AbortSignal): Promise<ApproachDetail> {
  return getJson(`/approaches/${encodeURIComponent(attemptId)}`, signal);
}

export function getApproachOperation(
  operationRef: string,
  signal?: AbortSignal,
): Promise<ApproachOperation> {
  return getJson(`/approach-operations/${encodeURIComponent(operationRef)}`, signal);
}

export interface ApproachEvaluationRejection {
  code: string;
  message: string;
  count?: number;
  field?: string;
}

export interface ApproachUploadResponse {
  schema_version?: string;
  data_origin: "user_upload_ephemeral";
  reference_origin: "derived_from_aggregate_real_research";
  release_id: string;
  reference_sha256?: string;
  dataset_digest?: string;
  upload_sha256?: string;
  raw_rows?: number;
  canonical_rows?: number;
  accepted_rows?: number;
  duplicate_rows_collapsed?: number;
  operation_count?: number;
  attempt_count?: number;
  rejected_operations?: number;
  status_counts?: Partial<Record<ApproachStatus, number>>;
  rejection_reasons?: ApproachEvaluationRejection[];
  attempts: ApproachUploadAttempt[];
  native_response?: NativeApproachUploadResponse;
}

export interface ApproachUploadAttempt extends Omit<
  ApproachSummary,
  "data_origin" | "scenario_id" | "scenario_title" | "teaching_goal"
> {
  data_origin: "user_upload_ephemeral";
  criteria?: ApproachCriterion[];
  quality?: Record<string, unknown> | null;
  maneuvers?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown> | null;
  path?: ApproachPathPoint[];
  context?: {
    weather?: Record<string, unknown> | null;
    aircraft?: Record<string, unknown> | null;
    unavailable?: string[];
  } | null;
}

interface NativeApproachEvaluationResult {
  evaluation_ref: string;
  operation_id: string;
  attempt_index: number;
  status: ApproachStatus;
  attempt: {
    start_time?: number;
    end_time?: number;
    outcome?: string;
    observed_samples?: number;
    [key: string]: unknown;
  };
  runway?: {
    designator?: string;
    geometry_runway?: string;
    direction?: string;
    specificity?: string;
    confidence?: number;
  } | null;
  failed_criteria?: string[];
  reasons?: string[];
  criteria?: ApproachCriterion[];
  maneuvers?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown> | null;
  trajectory?: { points?: ApproachPathPoint[]; [key: string]: unknown } | null;
  channels?: Record<string, Array<number | boolean | null>>;
  quality?: {
    fatal_reasons?: string[];
    observed_samples?: number;
    [key: string]: unknown;
  } | null;
  context?: {
    weather?: Record<string, unknown> | null;
    aircraft?: Record<string, unknown> | null;
    unavailable?: string[];
  } | null;
}

export interface NativeApproachUploadResponse {
  schema_version?: string;
  data_origin: "user_upload_ephemeral";
  reference_origin: "derived_from_aggregate_real_research";
  release_id: string;
  reference_sha256?: string;
  dataset_digest?: string;
  upload_sha256?: string;
  raw_rows?: number;
  canonical_rows?: number;
  duplicate_rows_collapsed?: number;
  operations?: number;
  attempts?: number;
  status_counts?: Partial<Record<ApproachStatus, number>>;
  rejection_reasons?: ApproachEvaluationRejection[];
  results: NativeApproachEvaluationResult[];
}

export async function evaluateApproachFile(
  file: File,
  signal?: AbortSignal,
): Promise<ApproachUploadResponse> {
  const body = new FormData();
  body.append("file", file);
  const payload = await requestJson<NativeApproachUploadResponse>("/evaluations", {
    method: "POST",
    body,
    signal,
  });
  if (
    payload.data_origin !== "user_upload_ephemeral"
    || payload.reference_origin !== "derived_from_aggregate_real_research"
  ) {
    throw new ApiError(
      502,
      "invalid_response",
      "Evaluation response origin is invalid.",
    );
  }
  return {
    schema_version: payload.schema_version,
    data_origin: payload.data_origin,
    reference_origin: payload.reference_origin,
    release_id: payload.release_id,
    reference_sha256: payload.reference_sha256,
    dataset_digest: payload.dataset_digest,
    upload_sha256: payload.upload_sha256,
    raw_rows: payload.raw_rows,
    canonical_rows: payload.canonical_rows,
    accepted_rows: payload.canonical_rows,
    duplicate_rows_collapsed: payload.duplicate_rows_collapsed,
    operation_count: payload.operations,
    attempt_count: payload.attempts,
    status_counts: payload.status_counts,
    rejection_reasons: payload.rejection_reasons,
    native_response: payload,
    attempts: payload.results.map((result) => ({
      attempt_id: result.evaluation_ref,
      operation_ref: result.operation_id,
      data_origin: "user_upload_ephemeral",
      status: result.status,
      direction: result.runway?.direction ?? null,
      runway: result.runway?.designator ?? null,
      geometry_runway: result.runway?.geometry_runway ?? null,
      runway_specificity: result.runway?.specificity ?? null,
      runway_confidence: result.runway?.confidence ?? null,
      failed_criteria: result.failed_criteria ?? [],
      outcome: result.attempt.outcome ?? null,
      observed_samples: result.attempt.observed_samples ?? result.quality?.observed_samples,
      coverage: result.attempt.observed_samples == null ? null : {
        observed_samples: result.attempt.observed_samples,
      },
      start_time: result.attempt.start_time ?? null,
      end_time: result.attempt.end_time ?? null,
      reasons: result.reasons ?? [],
      quality_flags: result.quality?.fatal_reasons ?? [],
      criteria: result.criteria ?? [],
      quality: result.quality ?? null,
      maneuvers: result.maneuvers ?? [],
      provenance: result.provenance ?? null,
      path: result.trajectory?.points ?? [],
      context: result.context ?? null,
    })),
  };
}
