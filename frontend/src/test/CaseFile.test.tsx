import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import CaseFile from "../pages/CaseFile";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, getFlight: vi.fn(), simulate: vi.fn() };
});

const DETAIL: api.FlightDetail = {
  id: 4238,
  case_ref: "CASE-4238",
  operation_ref: "OP-502CE6-1543855510",
  segment_id: "502ce6_1543855510#1",
  label: "go_around",
  path: [
    { lat: 40.49, lon: -3.59, alt: 1200, t: 0 },
    { lat: 40.45, lon: -3.57, alt: 600, t: 10 },
    { lat: 40.52, lon: -3.61, alt: 2000, t: 20 },
  ],
  reconstructed: [
    { lat: 40.49, lon: -3.59, alt: 1200 },
    { lat: 40.46, lon: -3.58, alt: 700 },
    { lat: 40.5, lon: -3.6, alt: 1800 },
  ],
  context_path: [
    { lat: 40.49, lon: -3.59 },
    { lat: 40.45, lon: -3.57 },
    { lat: 40.52, lon: -3.61 },
  ],
  n_siblings: 1,
  scores: [0.1, 0.5, 1.2],
  window_score: 1.2,
  pct: 99,
  band: "highly anomalous",
  anomalous: true,
  threshold: 0.222,
  step_threshold: 0.9,
  valid_steps: 3,
  n_steps: 3,
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
  feature_attribution: { velocity: 5.3, dist_to_runway_m: 4.1, lat: 2.1 },
  channels: {
    baroaltitude: [1200, 600, 2000],
    velocity: [80, 40, 95],
    vertrate: [-5, -8, 6],
    dist_to_runway_m: [4000, 1200, 6000],
  },
  center: { lat: 40.4936, lon: -3.5668 },
  step_seconds: 10,
  operation_segments: [
    { id: 4238, case_ref: "CASE-4238", operation_ref: "OP-502CE6-1543855510", segment_id: "502ce6_1543855510#1", score: 1.2, pct: 99, band: "highly anomalous", anomalous: true, label: "go_around", has_case: true, n_steps: 3, truncated: false, terminal_op: true, assessment_state: "reviewable", behavioral_verdict: "reviewable", review_lane: "behavioral", data_quality_flags: [], valid_steps: 3, observed_fraction: 1, max_altitude_jump_m: 100, max_implied_vertical_rate_mps: 10, max_implied_ground_speed_mps: 100 },
    { id: 4239, case_ref: "CASE-4239", operation_ref: "OP-502CE6-1543855510", segment_id: "502ce6_1543855510#2", score: 0.18, pct: 70, band: "upper-normal", anomalous: false, label: "normal", has_case: true, n_steps: 3, truncated: false, terminal_op: true, assessment_state: "reviewable", behavioral_verdict: "reviewable", review_lane: "behavioral", data_quality_flags: [], valid_steps: 3, observed_fraction: 1, max_altitude_jump_m: 100, max_implied_vertical_rate_mps: 10, max_implied_ground_speed_mps: 100 },
  ],
};

const SIM: api.SimulationResult = {
  id: 4238,
  segment_id: "502ce6_1543855510#1",
  kind: "sustained_loiter",
  intensity: 1,
  onset: 0.5,
  onset_index: 1,
  path: [
    { lat: 40.49, lon: -3.59, alt: 1200, t: 0 },
    { lat: 40.49, lon: -3.59, alt: 1200, t: 10 },
    { lat: 40.49, lon: -3.59, alt: 1200, t: 20 },
  ],
  channels: {
    baroaltitude: [1200, 1200, 1200],
    velocity: [80, 1, 1],
    vertrate: [-5, 0, 0],
    dist_to_runway_m: [4000, 4000, 4000],
  },
  scores: [0.1, 0.9, 1.4],
  window_score: 0.9,
  original_score: 1.2,
  pct: 99.6,
  band: "highly anomalous",
  anomalous: true,
  threshold: 0.222,
  step_threshold: 0.9,
  valid_steps: 3,
  center: { lat: 40.4936, lon: -3.5668 },
  step_seconds: 10,
};

beforeEach(() => vi.mocked(api.getFlight).mockResolvedValue(DETAIL));
afterEach(() => vi.clearAllMocks());

function renderCase() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/case/4238"]}>
      <Routes>
        <Route path="/" element={<div>QUEUE LANDING</div>} />
        <Route path="/case/:id" element={<CaseFile />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CaseFile", () => {
  it("renders the verdict, percentile band, and attribution", async () => {
    renderCase();
    expect(await screen.findByText("1.20")).toBeInTheDocument();
    expect(screen.getByText(/99th percentile · highly anomalous/)).toBeInTheDocument();
    expect(screen.getByText("velocity")).toBeInTheDocument();
    expect(screen.getByText("dist_to_runway_m")).toBeInTheDocument();
  });

  it("shows neighboring scored segments from the same operation", async () => {
    renderCase();
    expect(await screen.findByText(/Operation context · OP-502CE6-1543855510/)).toBeInTheDocument();
    expect(screen.getByText("CASE-4238")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /CASE-4239/ })).toBeInTheDocument();
    expect(screen.getByText(/Each score remains independent/)).toBeInTheDocument();
  });

  it("scrubs the temporal chart with arrow keys and updates the readout", async () => {
    renderCase();
    const chart = await screen.findByRole("img", { name: /ALTITUDE \(m\) and reconstruction-error/ });
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByText(/step 1 ·/)).toBeInTheDocument();
  });

  it("exposes a screen-reader data table for the chart", async () => {
    renderCase();
    await screen.findByText("1.20");
    expect(
      screen.getByRole("table", { name: /Per-step channel value and reconstruction error/ }),
    ).toBeInTheDocument();
  });

  it("switches the temporal channel via the selector", async () => {
    renderCase();
    await screen.findByText("1.20");
    // default chart is altitude
    expect(screen.getByRole("img", { name: /ALTITUDE \(m\) and reconstruction-error/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ground speed" }));
    expect(screen.getByRole("img", { name: /GROUND SPEED \(m\/s\) and reconstruction-error/ })).toBeInTheDocument();
  });

  it("runs a what-if, overlays it, shows the score delta, and clears it", async () => {
    vi.mocked(api.simulate).mockResolvedValue(SIM);
    renderCase();
    await screen.findByText("1.20");
    await userEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));
    // score delta appears (overlay active)
    expect(await screen.findByText(/what-if sustained loiter:/)).toBeInTheDocument();
    // undo
    await userEvent.click(screen.getByRole("button", { name: "CLEAR" }));
    expect(screen.queryByText(/what-if sustained loiter:/)).not.toBeInTheDocument();
  });

  it("clears a completed what-if when navigating to another case", async () => {
    vi.mocked(api.simulate).mockResolvedValue(SIM);
    vi.mocked(api.getFlight).mockImplementation((id) => Promise.resolve(
      id === 4239
        ? {
            ...DETAIL,
            id: 4239,
            case_ref: "CASE-4239",
            segment_id: "502ce6_1543855510#2",
            window_score: 0.18,
          }
        : DETAIL,
    ));
    renderCase();
    await screen.findByText("1.20");
    await userEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));
    expect(await screen.findByText(/what-if sustained loiter:/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /CASE-4239/ }));

    await waitFor(() => expect(api.getFlight).toHaveBeenLastCalledWith(4239, expect.any(AbortSignal)));
    await waitFor(() => expect(screen.queryByText(/what-if sustained loiter:/)).not.toBeInTheDocument());
  });

  it("shows the truncation banner for a long arrival", async () => {
    vi.mocked(api.getFlight).mockResolvedValueOnce({ ...DETAIL, n_steps: 402, valid_steps: 254, truncated: true, terminal_op: false, assessment_state: "coverage_limited", behavioral_verdict: "not_assessable", review_lane: "coverage", data_quality_flags: ["terminal_phase_not_scored"], observed_fraction: 0.98 });
    renderCase();
    expect(await screen.findByText(/Window truncated/)).toBeInTheDocument();
    expect(screen.getByText(/not scored/)).toBeInTheDocument();
  });

  it("shows an abstention banner for a non-terminal non-truncated case", async () => {
    vi.mocked(api.getFlight).mockResolvedValueOnce({ ...DETAIL, truncated: false, terminal_op: false, assessment_state: "coverage_limited", behavioral_verdict: "not_assessable", review_lane: "coverage", data_quality_flags: ["nonterminal_window"] });
    renderCase();
    expect(await screen.findByText(/Terminal coverage absent/)).toBeInTheDocument();
    expect(screen.getByText(/does not assign a cause/)).toBeInTheDocument();
  });

  it("separates a data-quality conflict from the raw model flag", async () => {
    vi.mocked(api.getFlight).mockResolvedValueOnce({ ...DETAIL, assessment_state: "data_quality_conflict", behavioral_verdict: "not_assessable", review_lane: "data_quality", data_quality_flags: ["altitude_rate_conflict"], max_altitude_jump_m: 10934, max_implied_vertical_rate_mps: 1093.4 });
    renderCase();
    expect(await screen.findByText(/Data-quality conflict/)).toBeInTheDocument();
    expect(screen.getByText(/behavioral conformance is/)).toBeInTheDocument();
    expect(screen.getByText(/does not assign/)).toBeInTheDocument();
  });

  it("reveals a pre-generated analysis report on click", async () => {
    vi.mocked(api.getFlight).mockResolvedValueOnce({
      ...DETAIL,
      report: "Velocity and distance-to-runway dominate the reconstruction error.",
      report_model: "claude-sonnet-4-6",
    });
    renderCase();
    const btn = await screen.findByRole("button", { name: /Analyse what drove the score/ });
    await userEvent.click(btn);
    expect(screen.getByText(/Velocity and distance-to-runway dominate/)).toBeInTheDocument();
    expect(screen.getByText(/explanatory analysis, not a model score/)).toBeInTheDocument();
  });

  it("shows the empty state when no report was generated", async () => {
    renderCase();
    expect(await screen.findByText(/No analysis report was baked for this case/)).toBeInTheDocument();
  });

  it("returns to the queue on Escape", async () => {
    renderCase();
    await screen.findByText("1.20");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(await screen.findByText("QUEUE LANDING")).toBeInTheDocument();
  });

  it("shows a graceful missing-case state on 404", async () => {
    vi.mocked(api.getFlight).mockRejectedValueOnce(new api.ApiError(404));
    renderCase();
    expect(await screen.findByText("No case file for this segment")).toBeInTheDocument();
  });
});
