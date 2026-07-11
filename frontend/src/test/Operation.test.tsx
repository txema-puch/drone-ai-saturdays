import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Operation from "../pages/Operation";

vi.mock("../api");

const SEGMENTS: api.FlightSummary[] = [
  { id: 4238, case_ref: "CASE-4238", operation_ref: "OP-502CE6-1543855510", segment_id: "502ce6_1543855510#1", score: 1.5, pct: 99, band: "highly anomalous", anomalous: true, label: "go_around", has_case: true, n_steps: 238, truncated: false, terminal_op: true, assessment_state: "reviewable", behavioral_verdict: "reviewable", review_lane: "behavioral", data_quality_flags: [], valid_steps: 238, observed_fraction: 1, max_altitude_jump_m: 100, max_implied_vertical_rate_mps: 10, max_implied_ground_speed_mps: 100 },
  { id: 4239, case_ref: "CASE-4239", operation_ref: "OP-502CE6-1543855510", segment_id: "502ce6_1543855510#2", score: 0.12, pct: 40, band: "normal range", anomalous: false, label: "normal", has_case: false, n_steps: 80, truncated: true, terminal_op: false, assessment_state: "coverage_limited", behavioral_verdict: "not_assessable", review_lane: "coverage", data_quality_flags: ["terminal_phase_not_scored"], valid_steps: 80, observed_fraction: 1, max_altitude_jump_m: 100, max_implied_vertical_rate_mps: 10, max_implied_ground_speed_mps: 100 },
];

const OPERATION: api.OperationSummary = {
  operation_ref: "OP-502CE6-1543855510", segment_count: 2, flagged_segment_count: 1,
  worst_score: 1.5, worst_pct: 99, worst_band: "highly anomalous", worst_case_ref: "CASE-4238",
  worst_segment_id: SEGMENTS[0].segment_id, worst_segment_id_num: 4238, worst_has_case: true,
  labels_seen: ["go_around", "normal"], has_confirmed_event: true, has_model_flag_unlabeled: false,
  terminal_segment_count: 1, truncated_segment_count: 1, data_quality_summary: "mixed",
  assessment_summary: "mixed evidence", behavioral_assessment: "reviewable",
  behavioral_flagged_segment_count: 1, reviewable_segment_count: 1,
  not_assessable_segment_count: 1, data_quality_segment_count: 0,
  coverage_limited_segment_count: 1, behavioral_worst_score: 1.5,
  behavioral_worst_pct: 99, behavioral_worst_band: "highly anomalous",
  behavioral_worst_case_ref: "CASE-4238", behavioral_worst_segment_id_num: 4238,
  segments: SEGMENTS,
};

beforeEach(() => vi.mocked(api.getOperation).mockResolvedValue(OPERATION));
afterEach(() => vi.clearAllMocks());

function renderOperation() {
  return render(
    <MemoryRouter initialEntries={["/operation/OP-502CE6-1543855510"]}>
      <Routes>
        <Route path="/" element={<div>QUEUE LANDING</div>} />
        <Route path="/case/:id" element={<div>CASE LANDING</div>} />
        <Route path="/operation/:operationRef" element={<Operation />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Operation", () => {
  it("renders operation-level summary and independent segment evidence", async () => {
    renderOperation();
    expect(await screen.findByText("Operation review")).toBeInTheDocument();
    expect(screen.getByText("OP-502CE6-1543855510")).toBeInTheDocument();
    expect(screen.getByText(/segment scores are never added together/)).toBeInTheDocument();
    expect(screen.getByText("CASE-4238")).toBeInTheDocument();
    expect(screen.getByText("CASE-4239")).toBeInTheDocument();
    expect(screen.getByText("Evidence only")).toBeInTheDocument();
  });

  it("only offers case navigation for segments with baked detail", async () => {
    renderOperation();
    expect(await screen.findByRole("button", { name: "Open CASE-4238 segment case file" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open CASE-4239 segment case file" })).not.toBeInTheDocument();
  });

  it("returns to the queue on Escape", async () => {
    renderOperation();
    await screen.findByText("Operation review");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(await screen.findByText("QUEUE LANDING")).toBeInTheDocument();
  });

  it("shows a missing-operation state", async () => {
    vi.mocked(api.getOperation).mockRejectedValueOnce(new Error("request failed: 404"));
    renderOperation();
    expect(await screen.findByText("Operation not found")).toBeInTheDocument();
  });
});
