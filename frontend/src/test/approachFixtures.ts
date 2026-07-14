import type {
  ApproachDetail,
  ApproachOperation,
  ApproachSummary,
  ApproachUploadResponse,
  Health,
} from "../api";

export const APPROACH_HEALTH: Health = {
  status: "ok",
  mode: "approach-screening",
  operations: 2,
  attempts: 2,
  evaluation_enabled: true,
  release_id: "approach-release-33",
  schema_version: 3,
  status_counts: { review_required: 1, partial_observation: 1 },
  reference: { status: "ready", artifact_sha256: "reference0123456789" },
};

export const REVIEW_ATTEMPT: ApproachSummary = {
  attempt_id: "att-op-1-01",
  operation_ref: "OP-LEMD-001",
  status: "review_required",
  direction: "32",
  runway: "32L",
  failed_criteria: ["observed_descent_rate"],
  outcome: "landing_observed",
  observed_samples: 48,
  coverage: { observed_fraction: 0.96 },
  start_time: 1_773_651_600,
  end_time: 1_773_651_900,
  reasons: [],
  quality_flags: [],
};

export const PARTIAL_ATTEMPT: ApproachSummary = {
  attempt_id: "att-op-2-01",
  operation_ref: "OP-LEMD-002",
  status: "partial_observation",
  direction: "18",
  runway: "18R",
  failed_criteria: [],
  outcome: "final_gate_observed",
  observed_samples: 31,
  coverage: { observed_fraction: 0.67 },
  start_time: 1_773_650_000,
  end_time: 1_773_650_240,
  reasons: [],
  quality_flags: ["barometric_altitude_unavailable"],
};

export const APPROACH_DETAIL: ApproachDetail = {
  ...REVIEW_ATTEMPT,
  schema_version: "approach_assessment_v1",
  engine_version: "prototype_v1",
  path: [
    { lat: 40.3, lon: -3.7, alt: 900, time: 1_773_651_600, along_track_m: 9_000, cross_track_m: 220 },
    { lat: 40.4, lon: -3.6, alt: 500, time: 1_773_651_750, along_track_m: 4_500, cross_track_m: 90 },
    { lat: 40.49, lon: -3.57, alt: 610, time: 1_773_651_900, along_track_m: 500, cross_track_m: 20 },
  ],
  criteria: [
    {
      name: "observed_descent_rate",
      status: "review_required",
      severity: "high",
      observed_samples: 46,
      reference_source: "empirical_train_envelope",
      evidence: [{
        start_time: 1_773_651_720,
        end_time: 1_773_651_780,
        worst_time: 1_773_651_750,
        value: -9.2,
        limit: -7.6,
        unit: "m/s",
      }],
    },
    {
      name: "barometric_path_proxy",
      status: "within_limit",
      observed_samples: 42,
      altitude_bias_source: "threshold_adjacent_proxy",
      evidence: [],
    },
  ],
  quality: { observed_samples: 48, maximum_gap_s: 10, fatal_reasons: [] },
  altitude_reference: { bias_m: 34.2, source: "threshold_adjacent_proxy" },
  maneuvers: [],
  provenance: {
    config_sha256: "config0123456789abcdef",
    reconstruction_policy_sha256: "reconstruction0123456789",
  },
  geometry: { artifact_sha256: "geometry0123456789" },
  reference: { artifact_sha256: "reference0123456789" },
  research_benchmark: {
    model_id: "historical-lstm-ae",
    segment_id: "legacy-segment-1",
    score: 0.42,
    coverage: "first 260 resampled steps",
  },
};

export const APPROACH_OPERATION: ApproachOperation = {
  operation_ref: "OP-LEMD-001",
  attempts: [REVIEW_ATTEMPT, { ...PARTIAL_ATTEMPT, operation_ref: "OP-LEMD-001" }],
};

export const APPROACH_UPLOAD: ApproachUploadResponse = {
  release_id: "approach-release-33",
  upload_sha256: "upload0123456789",
  raw_rows: 120,
  accepted_rows: 110,
  operation_count: 1,
  attempt_count: 1,
  rejected_operations: 1,
  rejection_reasons: [{ code: "terminal_gate_not_reached", message: "One record did not reach the final gate.", count: 1 }],
  attempts: [{ ...REVIEW_ATTEMPT, criteria: APPROACH_DETAIL.criteria }],
};
