import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  evaluateApproachFile,
  getApproach,
  getApproaches,
  getApproachOperation,
  getEvidence,
  getHealth,
} from "../api";

afterEach(() => vi.unstubAllGlobals());

function mockFetch(impl: (url: string, init?: RequestInit) => Partial<Response>) {
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => Promise.resolve(impl(url, init) as Response)));
}

describe("approach API client", () => {
  it("uses same-origin endpoints and omits all-valued filters", async () => {
    const seen: string[] = [];
    mockFetch((url) => {
      seen.push(url);
      return { ok: true, json: () => Promise.resolve(url.includes("/approaches?") ? { items: [] } : {}) };
    });
    await getApproaches({ limit: 25, status: "review_required", direction: "all" });
    await getApproach("att/one");
    await getApproachOperation("OP one");
    await getEvidence();
    expect(seen).toEqual([
      "/api/approaches?limit=25&status=review_required",
      "/api/approaches/att%2Fone",
      "/api/approach-operations/OP%20one",
      "/api/evidence",
    ]);
  });

  it("normalizes native evaluation DTOs into ephemeral attempt summaries", async () => {
    let seenInit: RequestInit | undefined;
    mockFetch((_url, init) => {
      seenInit = init;
      return {
        ok: true,
        json: () => Promise.resolve({
          schema_version: "approach_evaluation_v1",
          data_origin: "user_upload_ephemeral",
          reference_origin: "derived_from_aggregate_real_research",
          release_id: "release-33",
          reference_sha256: "ref123",
          dataset_digest: "data123",
          upload_sha256: "upload123",
          raw_rows: 20,
          canonical_rows: 18,
          duplicate_rows_collapsed: 2,
          operations: 1,
          attempts: 1,
          status_counts: { partial_observation: 1 },
          results: [{
            evaluation_ref: "eval-01",
            operation_id: "op-01",
            attempt_index: 1,
            status: "partial_observation",
            attempt: { start_time: 100, end_time: 200, outcome: "final_gate_observed", observed_samples: 11 },
            runway: { designator: "32L", direction: "32", specificity: "exact", confidence: 0.91 },
            failed_criteria: [],
            reasons: [],
            criteria: [{ name: "late_track_correction", status: "within_limit", observed_samples: 9, evidence: [] }],
            trajectory: {
              observed_points: 11,
              returned_points: 1,
              sampling: "evenly_spaced_v1",
              points: [{ time: 100, lat: 40.4, lon: -3.6 }],
            },
            channels: { time: [100], ground_speed_mps: [71.2] },
            quality: { fatal_reasons: ["altitude_unavailable"], observed_samples: 11 },
          }],
        }),
      };
    });
    const file = new File(["rows"], "sample.csv");
    const response = await evaluateApproachFile(file);
    expect(seenInit?.method).toBe("POST");
    expect((seenInit?.body as FormData).get("file")).toBe(file);
    expect(response).toMatchObject({
      release_id: "release-33",
      data_origin: "user_upload_ephemeral",
      reference_origin: "derived_from_aggregate_real_research",
      accepted_rows: 18,
      operation_count: 1,
      attempt_count: 1,
      attempts: [{
        attempt_id: "eval-01",
        operation_ref: "op-01",
        data_origin: "user_upload_ephemeral",
        status: "partial_observation",
        runway: "32L",
        direction: "32",
        observed_samples: 11,
        quality_flags: ["altitude_unavailable"],
        criteria: [{ name: "late_track_correction", status: "within_limit" }],
        path: [{ time: 100, lat: 40.4, lon: -3.6 }],
      }],
    });
    expect(response.native_response?.results[0]).toMatchObject({
      attempt_index: 1,
      runway: { specificity: "exact", confidence: 0.91 },
      trajectory: { sampling: "evenly_spaced_v1", observed_points: 11 },
      channels: { time: [100], ground_speed_mps: [71.2] },
    });
  });

  it("rejects evaluation responses without the promised origin boundary", async () => {
    mockFetch(() => ({
      ok: true,
      json: () => Promise.resolve({
        release_id: "release-33",
        data_origin: "synthetic",
        reference_origin: "derived_from_aggregate_real_research",
        results: [],
      }),
    }));
    const error = await evaluateApproachFile(new File(["rows"], "sample.csv"))
      .catch((caught) => caught as ApiError);
    expect(error).toMatchObject({
      status: 502,
      code: "invalid_response",
      message: "Evaluation response origin is invalid.",
    });
  });

  it("keeps structured bounded errors and retry metadata", async () => {
    mockFetch(() => ({
      ok: false,
      status: 422,
      headers: new Headers({ "Retry-After": "7" }),
      json: () => Promise.resolve({
        detail: {
          code: "invalid_schema",
          message: "Required fields are missing.",
          fields: [{ field: "time", message: "Use epoch seconds." }],
        },
      }),
    }));
    const error = await getHealth().catch((caught) => caught as ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: "invalid_schema",
      message: "Required fields are missing.",
      retryAfter: 7,
      fields: [{ field: "time", message: "Use epoch seconds." }],
    });
  });

  it("does not materialize oversized error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("x".repeat(64 * 1024 + 1), { status: 422 }))));
    const error = await getHealth().catch((caught) => caught as ApiError);
    expect(error).toMatchObject({ status: 422, code: "request_failed", fields: [] });
  });
});
