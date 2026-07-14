import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Queue from "../pages/Queue";

vi.mock("../api");

const HEALTH: api.Health = {
  status: "ok",
  mode: "post-hoc-audit",
  segments: 4,
  operations: 3,
  real_anomalies: 1,
  anomalous_at_threshold: 2,
  threshold: 0.222,
  step_threshold: 0.9,
  cases_available: 2,
  reviewable: 3,
  data_quality_conflicts: 0,
  insufficient_data: 0,
  coverage_limited: 1,
};

const REVIEWABLE = { assessment_state: "reviewable", behavioral_verdict: "reviewable", review_lane: "behavioral", data_quality_flags: [], valid_steps: 100, observed_fraction: 1, max_altitude_jump_m: 100, max_implied_vertical_rate_mps: 10, max_implied_ground_speed_mps: 100 } as const;
const COVERAGE = { assessment_state: "coverage_limited", behavioral_verdict: "not_assessable", review_lane: "coverage", data_quality_flags: ["terminal_phase_not_scored"], valid_steps: 260, observed_fraction: 1, max_altitude_jump_m: 100, max_implied_vertical_rate_mps: 10, max_implied_ground_speed_mps: 100 } as const;

const FLIGHTS: api.FlightSummary[] = [
  { ...COVERAGE, id: 1754, case_ref: "CASE-1754", operation_ref: "OP-345051-1580731490", segment_id: "345051_1580731490#1", score: 1.79, pct: 100, band: "highly anomalous", anomalous: true, label: "normal", has_case: true, n_steps: 402, truncated: true, terminal_op: false },
  { ...REVIEWABLE, id: 4238, case_ref: "CASE-4238", operation_ref: "OP-502CE6-1543855510", segment_id: "502ce6_1543855510#1", score: 1.5, pct: 99, band: "highly anomalous", anomalous: true, label: "go_around", has_case: true, n_steps: 238, truncated: false, terminal_op: true },
  { ...REVIEWABLE, id: 4239, case_ref: "CASE-4239", operation_ref: "OP-502CE6-1543855510", segment_id: "502ce6_1543855510#2", score: 0.12, pct: 40, band: "normal range", anomalous: false, label: "normal", has_case: false, n_steps: 80, truncated: false, terminal_op: true },
  { ...REVIEWABLE, id: 99, case_ref: "CASE-0099", operation_ref: "OP-ABCDEF-1580731000", segment_id: "abcdef_1580731000#1", score: 0.05, pct: 12, band: "normal range", anomalous: false, label: "normal", has_case: false, n_steps: 120, truncated: false, terminal_op: true },
];

const OPERATIONS: api.OperationSummary[] = [
  {
    operation_ref: "OP-345051-1580731490", segment_count: 1, flagged_segment_count: 1,
    worst_score: 1.79, worst_pct: 100, worst_band: "highly anomalous", worst_case_ref: "CASE-1754",
    worst_segment_id: FLIGHTS[0].segment_id, worst_segment_id_num: 1754, worst_has_case: true,
    labels_seen: ["normal"], has_confirmed_event: false, has_model_flag_unlabeled: true,
    terminal_segment_count: 0, truncated_segment_count: 1, data_quality_summary: "likely artifact",
    assessment_summary: "not assessable", behavioral_assessment: "not_assessable", behavioral_flagged_segment_count: 0, reviewable_segment_count: 0, not_assessable_segment_count: 1, data_quality_segment_count: 0, coverage_limited_segment_count: 1, behavioral_worst_score: null, behavioral_worst_pct: null, behavioral_worst_band: null, behavioral_worst_case_ref: null, behavioral_worst_segment_id_num: null,
    segments: [FLIGHTS[0]],
  },
  {
    operation_ref: "OP-502CE6-1543855510", segment_count: 2, flagged_segment_count: 1,
    worst_score: 1.5, worst_pct: 99, worst_band: "highly anomalous", worst_case_ref: "CASE-4238",
    worst_segment_id: FLIGHTS[1].segment_id, worst_segment_id_num: 4238, worst_has_case: true,
    labels_seen: ["go_around", "normal"], has_confirmed_event: true, has_model_flag_unlabeled: false,
    terminal_segment_count: 2, truncated_segment_count: 0, data_quality_summary: "mostly terminal",
    assessment_summary: "reviewable", behavioral_assessment: "reviewable", behavioral_flagged_segment_count: 1, reviewable_segment_count: 2, not_assessable_segment_count: 0, data_quality_segment_count: 0, coverage_limited_segment_count: 0, behavioral_worst_score: 1.5, behavioral_worst_pct: 99, behavioral_worst_band: "highly anomalous", behavioral_worst_case_ref: "CASE-4238", behavioral_worst_segment_id_num: 4238,
    segments: [FLIGHTS[1], FLIGHTS[2]],
  },
  {
    operation_ref: "OP-ABCDEF-1580731000", segment_count: 1, flagged_segment_count: 0,
    worst_score: 0.05, worst_pct: 12, worst_band: "normal range", worst_case_ref: "CASE-0099",
    worst_segment_id: FLIGHTS[3].segment_id, worst_segment_id_num: 99, worst_has_case: false,
    labels_seen: ["normal"], has_confirmed_event: false, has_model_flag_unlabeled: false,
    terminal_segment_count: 1, truncated_segment_count: 0, data_quality_summary: "mostly terminal",
    assessment_summary: "reviewable", behavioral_assessment: "reviewable", behavioral_flagged_segment_count: 0, reviewable_segment_count: 1, not_assessable_segment_count: 0, data_quality_segment_count: 0, coverage_limited_segment_count: 0, behavioral_worst_score: 0.05, behavioral_worst_pct: 12, behavioral_worst_band: "normal range", behavioral_worst_case_ref: "CASE-0099", behavioral_worst_segment_id_num: 99,
    segments: [FLIGHTS[3]],
  },
];

beforeEach(() => {
  vi.mocked(api.getHealth).mockResolvedValue(HEALTH);
  vi.mocked(api.getFlights).mockResolvedValue(FLIGHTS);
  vi.mocked(api.getOperations).mockResolvedValue(OPERATIONS);
});
afterEach(() => vi.clearAllMocks());

function renderQueue() {
  return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Queue /></MemoryRouter>);
}

describe("Queue", () => {
  it("defaults to operation triage with honest worst-segment evidence", async () => {
    renderQueue();
    expect(await screen.findByText("OP-502CE6-1543855510")).toBeInTheDocument();
    expect(screen.getByText("1 flagged segment in this behavioral lane")).toBeInTheDocument();
    expect(screen.getByText(/Lane evidence: CASE-4238 · Labels: go_around, normal · Assessment: reviewable/)).toBeInTheDocument();
    expect(screen.queryByText("OP-345051-1580731490")).not.toBeInTheDocument();
  });

  it("switches to segment evidence and uses stable backend case refs", async () => {
    renderQueue();
    await screen.findByText("OP-502CE6-1543855510");
    await userEvent.click(screen.getByRole("button", { name: "Segments" }));
    expect(await screen.findByText("502ce6_1543855510#1")).toBeInTheDocument();
    expect(screen.getByText("CASE-4238")).toBeInTheDocument();
  });

  it("reveals coverage-limited operations in their review lane", async () => {
    renderQueue();
    await screen.findByText("OP-502CE6-1543855510");
    await userEvent.click(screen.getByRole("button", { name: "Coverage limited" }));
    expect(screen.getByText("OP-345051-1580731490")).toBeInTheDocument();
  });

  it("searches operations through their segment ids", async () => {
    renderQueue();
    await screen.findByText("OP-502CE6-1543855510");
    await userEvent.type(screen.getByLabelText("Search queue"), "abcdef_1580731000#1");
    expect(screen.getByText("OP-ABCDEF-1580731000")).toBeInTheDocument();
    expect(screen.queryByText("OP-502CE6-1543855510")).not.toBeInTheDocument();
  });

  it("only fetches the active queue level with the chosen order", async () => {
    renderQueue();
    await screen.findByText("OP-502CE6-1543855510");
    await userEvent.click(screen.getByRole("button", { name: "Typical" }));
    await waitFor(() => expect(vi.mocked(api.getOperations)).toHaveBeenCalledWith(5000, "typical", expect.anything()));
    expect(vi.mocked(api.getFlights)).not.toHaveBeenCalled();
  });

  it("opens every operation independently of baked case availability", async () => {
    renderQueue();
    await screen.findByText("OP-502CE6-1543855510");
    expect(screen.getByRole("button", { name: "Open operation OP-502CE6-1543855510" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open operation OP-ABCDEF-1580731000" })).toBeInTheDocument();
  });

  it("retries and recovers after a failed queue request", async () => {
    vi.mocked(api.getHealth).mockRejectedValueOnce(new Error("503")).mockResolvedValue(HEALTH);
    renderQueue();
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("OP-502CE6-1543855510")).toBeInTheDocument();
    expect(api.getHealth).toHaveBeenCalledTimes(2);
  });
});
