import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import * as api from "../api";

vi.mock("../api");

const HEALTH: api.Health = {
  status: "ok",
  mode: "post-hoc-audit",
  segments: 4480,
  operations: 3200,
  real_anomalies: 195,
  anomalous_at_threshold: 430,
  threshold: 0.222,
  step_threshold: 0.9,
  cases_available: 250,
  reviewable: 4300,
  data_quality_conflicts: 20,
  insufficient_data: 10,
  coverage_limited: 150,
};

const FLIGHT: api.FlightSummary = {
  case_id: "c_c2bwwjgaxbqg43kb",
  case_ref: "CASE-C2BWWJGAXBQG4",
  operation_ref: "OP-502CE6-1543855510",
  segment_id: "502ce6_1543855510#1",
  score: 1.94,
  pct: 100,
  band: "highly anomalous",
  anomalous: true,
  label: "go_around",
  has_case: true,
  n_steps: 200,
  truncated: false,
  terminal_op: true,
  assessment_state: "reviewable",
  behavioral_verdict: "reviewable",
  review_lane: "behavioral",
  data_quality_flags: [],
  valid_steps: 200,
  observed_fraction: 1,
  max_altitude_jump_m: 100,
  max_implied_vertical_rate_mps: 10,
  max_implied_ground_speed_mps: 100,
};

const OPERATION: api.OperationSummary = {
  operation_ref: FLIGHT.operation_ref,
  segment_count: 1,
  flagged_segment_count: 1,
  worst_score: FLIGHT.score,
  worst_pct: FLIGHT.pct,
  worst_band: FLIGHT.band,
  worst_case_id: FLIGHT.case_id,
  worst_case_ref: FLIGHT.case_ref,
  worst_segment_id: FLIGHT.segment_id,
  worst_has_case: true,
  labels_seen: [FLIGHT.label],
  has_confirmed_event: true,
  has_model_flag_unlabeled: false,
  terminal_segment_count: 1,
  truncated_segment_count: 0,
  data_quality_summary: "mostly terminal",
  assessment_summary: "reviewable",
  behavioral_assessment: "reviewable",
  behavioral_flagged_segment_count: 1,
  reviewable_segment_count: 1,
  not_assessable_segment_count: 0,
  data_quality_segment_count: 0,
  coverage_limited_segment_count: 0,
  behavioral_worst_score: FLIGHT.score,
  behavioral_worst_pct: FLIGHT.pct,
  behavioral_worst_band: FLIGHT.band,
  behavioral_worst_case_id: FLIGHT.case_id,
  behavioral_worst_case_ref: FLIGHT.case_ref,
  segments: [FLIGHT],
};

const DETAIL: api.FlightDetail = {
  case_id: FLIGHT.case_id,
  case_ref: FLIGHT.case_ref,
  operation_ref: FLIGHT.operation_ref,
  segment_id: "502ce6_1543855510#1",
  label: "go_around",
  path: [
    { lat: 40.49, lon: -3.59, alt: 1200, t: 0 },
    { lat: 40.45, lon: -3.57, alt: 600, t: 10 },
  ],
  reconstructed: [
    { lat: 40.49, lon: -3.59, alt: 1200 },
    { lat: 40.46, lon: -3.58, alt: 700 },
  ],
  context_path: [
    { lat: 40.49, lon: -3.59 },
    { lat: 40.45, lon: -3.57 },
  ],
  n_siblings: 1,
  scores: [0.1, 1.2],
  window_score: 1.94,
  pct: 100,
  band: "highly anomalous",
  anomalous: true,
  threshold: 0.222,
  step_threshold: 0.9,
  valid_steps: 2,
  n_steps: 2,
  truncated: false,
  terminal_op: true,
  assessment_state: "reviewable",
  behavioral_verdict: "reviewable",
  review_lane: "behavioral",
  data_quality_flags: [],
  observed_fraction: 1,
  max_altitude_jump_m: 100,
  max_implied_vertical_rate_mps: 10,
  max_implied_ground_speed_mps: 100,
  report: null,
  report_model: null,
  feature_attribution: { velocity: 5.3 },
  channels: {
    baroaltitude: [1200, 600],
    velocity: [80, 40],
    vertrate: [-5, -8],
    dist_to_runway_m: [4000, 1200],
  },
  center: { lat: 40.4936, lon: -3.5668 },
  step_seconds: 10,
  operation_segments: [FLIGHT],
};

beforeEach(() => {
  vi.mocked(api.getHealth).mockResolvedValue(HEALTH);
  vi.mocked(api.getFlights).mockResolvedValue([FLIGHT]);
  vi.mocked(api.getOperations).mockResolvedValue([OPERATION]);
  vi.mocked(api.getOperation).mockResolvedValue(OPERATION);
  vi.mocked(api.getFlight).mockResolvedValue(DETAIL);
});
afterEach(() => vi.clearAllMocks());

function renderApp() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
}

describe("queue → operation → case flow", () => {
  it("shows persistent evaluation navigation only when the deployment enables it", async () => {
    vi.mocked(api.getHealth).mockResolvedValue({
      ...HEALTH,
      evaluation_enabled: true,
      model_state: "ready",
      model_retry_remaining: 1,
      release_id: "release-123",
      model_id: "lstm-ae",
    });
    renderApp();
    expect(screen.getByRole("link", { name: "SADAR / ANALYST CONSOLE" })).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "Evaluate data" });
    await userEvent.click(link);
    expect(await screen.findByRole("heading", { name: "Evaluate new data" })).toBeInTheDocument();
  });

  it("opens the operation before drilling into its segment case", async () => {
    renderApp();
    const row = await screen.findByRole("button", { name: "Open operation OP-502CE6-1543855510" });
    await userEvent.click(row);
    expect(await screen.findByText("Operation review")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open CASE-C2BWWJGAXBQG4 segment case file" }));
    expect(await screen.findByText("Segment conformance review")).toBeInTheDocument();
    expect(screen.getByText(/100th percentile/)).toBeInTheDocument();
  });

  it("opens an operation on Enter", async () => {
    renderApp();
    const row = await screen.findByRole("button", { name: "Open operation OP-502CE6-1543855510" });
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Operation review")).toBeInTheDocument();
  });
});
