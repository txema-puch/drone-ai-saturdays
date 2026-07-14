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
  evaluation_enabled?: boolean;
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
  observed?: boolean;
}

export interface ApproachSummary {
  attempt_id: string;
  operation_ref: string;
  status: ApproachStatus;
  direction?: string | null;
  runway?: string | null;
  failed_criteria: string[];
  outcome?: string | null;
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
  schema_version?: string;
  engine_version?: string;
  research_benchmark?: ApproachResearchBenchmark | null;
}

export interface ApproachOperation {
  operation_ref: string;
  attempts: ApproachSummary[];
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
}

export interface ApproachUploadAttempt extends ApproachSummary {
  criteria?: ApproachCriterion[];
  quality?: Record<string, unknown> | null;
  maneuvers?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown> | null;
  path?: ApproachPathPoint[];
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
  runway?: { designator?: string; direction?: string } | null;
  failed_criteria?: string[];
  reasons?: string[];
  criteria?: ApproachCriterion[];
  maneuvers?: Array<Record<string, unknown>>;
  provenance?: Record<string, unknown> | null;
  trajectory?: { points?: ApproachPathPoint[]; [key: string]: unknown } | null;
  quality?: {
    fatal_reasons?: string[];
    observed_samples?: number;
    [key: string]: unknown;
  } | null;
}

interface NativeApproachUploadResponse {
  schema_version?: string;
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
  return {
    schema_version: payload.schema_version,
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
    attempts: payload.results.map((result) => ({
      attempt_id: result.evaluation_ref,
      operation_ref: result.operation_id,
      status: result.status,
      direction: result.runway?.direction ?? null,
      runway: result.runway?.designator ?? null,
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
    })),
  };
}
