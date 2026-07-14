import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Evaluate from "../pages/Evaluate";

const HEALTH: api.Health = {
  status: "ok",
  mode: "post-hoc-audit",
  segments: 4,
  operations: 2,
  real_anomalies: 0,
  anomalous_at_threshold: 1,
  threshold: 0.222,
  step_threshold: 0.9,
  cases_available: 2,
  reviewable: 2,
  data_quality_conflicts: 0,
  insufficient_data: 0,
  coverage_limited: 0,
  evaluation_enabled: true,
  model_state: "ready",
  model_retry_remaining: 1,
  release_id: "release-123",
  model_id: "lstm-ae",
};

function result(ref = "eval-one", segment = "a1b2c3_1773651600#1", score = 0.4): api.EvaluationResult {
  return {
    evaluation_ref: ref,
    segment_id: segment,
    model_status: score >= 0.222 ? "above_threshold" : "below_threshold",
    path: [{ lat: 40.5, lon: -3.6, alt: 1000 }, { lat: 40.49, lon: -3.57, alt: 900 }],
    reconstructed: [{ lat: 40.5, lon: -3.6, alt: 980 }, { lat: 40.49, lon: -3.57, alt: 910 }],
    scores: [0.1, score],
    window_score: score,
    pct: score >= 0.222 ? 91 : 30,
    threshold: 0.222,
    step_threshold: 0.9,
    valid_steps: 32,
    n_steps: 32,
    assessment_state: "reviewable",
    behavioral_verdict: "reviewable",
    review_lane: "behavioral",
    data_quality_flags: [],
    observed_fraction: 1,
    max_altitude_jump_m: 10,
    max_implied_vertical_rate_mps: 1,
    max_implied_ground_speed_mps: 80,
    feature_attribution: { velocity: 0.3, baroaltitude: 0.1 },
    channels: { baroaltitude: [1000, 900], velocity: [80, 70] },
    center: { lat: 40.4936, lon: -3.5668 },
    step_seconds: 10,
  };
}

function response(results = [result()]): api.EvaluationResponse {
  return {
    release_id: "release-123",
    model_id: "lstm-ae",
    dataset_digest: "abcdef0123456789abcdef0123456789",
    upload_sha256: "0123456789abcdef",
    raw_rows: 50,
    derived_rows: 48,
    accepted_rows: 40,
    accepted_segments: results.length,
    rejected_segments: 1,
    duplicate_rows_collapsed: 2,
    rejection_reasons: [{ code: "short", message: "One segment was too short.", count: 1 }],
    results,
  };
}

function renderEvaluate() {
  return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Evaluate /></MemoryRouter>);
}

async function uploadCsv(name = "sample.csv") {
  const input = await screen.findByLabelText("Select or drop CSV/Parquet");
  const file = new File(["time,icao24\n"], name, { type: "text/csv" });
  await userEvent.upload(input, file);
  return file;
}

beforeEach(() => {
  vi.spyOn(api, "getHealth").mockResolvedValue(HEALTH);
  vi.spyOn(api, "prepareModel").mockResolvedValue({ model_state: "loading", model_retry_remaining: 1 });
  vi.spyOn(api, "evaluateFile").mockResolvedValue(response());
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("evaluate data", () => {
  it("covers disabled, not-loaded, loading, failed, and ready capability states", async () => {
    vi.mocked(api.getHealth).mockResolvedValueOnce({ ...HEALTH, evaluation_enabled: false });
    const disabled = renderEvaluate();
    expect(await screen.findByText("Evaluation is not enabled")).toBeInTheDocument();
    disabled.unmount();

    vi.mocked(api.getHealth).mockResolvedValueOnce({ ...HEALTH, model_state: "not_loaded" });
    const notLoaded = renderEvaluate();
    expect(await screen.findByRole("button", { name: "Prepare model" })).toBeEnabled();
    notLoaded.unmount();

    vi.mocked(api.getHealth).mockResolvedValueOnce({ ...HEALTH, model_state: "loading" });
    const loading = renderEvaluate();
    expect(await screen.findByText("Preparing frozen model…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Select or drop CSV/Parquet")).not.toBeInTheDocument();
    loading.unmount();

    vi.mocked(api.getHealth).mockResolvedValueOnce({ ...HEALTH, model_state: "failed", model_retry_remaining: 1 });
    const failed = renderEvaluate();
    expect(await screen.findByRole("button", { name: "Retry preparation" })).toBeEnabled();
    failed.unmount();

    renderEvaluate();
    expect(await screen.findByLabelText("Select or drop CSV/Parquet")).toBeEnabled();
    expect(screen.getByRole("link", { name: "Download schema template" })).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Download synthetic sample" })).toHaveAttribute("download");
  });

  it("starts model preparation and refreshes readiness before enabling upload", async () => {
    vi.mocked(api.getHealth)
      .mockResolvedValueOnce({ ...HEALTH, model_state: "not_loaded" })
      .mockResolvedValueOnce(HEALTH);
    renderEvaluate();
    await userEvent.click(await screen.findByRole("button", { name: "Prepare model" }));
    expect(api.prepareModel).toHaveBeenCalledOnce();
    expect(await screen.findByLabelText("Select or drop CSV/Parquet")).toBeEnabled();
  });

  it("shows a bounded prepare-request failure without leaking the raw error", async () => {
    vi.mocked(api.getHealth)
      .mockResolvedValueOnce({ ...HEALTH, model_state: "not_loaded" })
      .mockResolvedValueOnce({ ...HEALTH, model_state: "not_loaded" });
    vi.mocked(api.prepareModel).mockRejectedValueOnce(new Error("secret model loader path"));
    renderEvaluate();

    await userEvent.click(await screen.findByRole("button", { name: "Prepare model" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/preparation request could not be completed/i);
    expect(screen.queryByText(/secret model loader path/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare model" })).toBeEnabled();
  });

  it("polls an indeterminate loading state until the model is ready", async () => {
    vi.useFakeTimers();
    vi.mocked(api.getHealth)
      .mockResolvedValueOnce({ ...HEALTH, model_state: "loading" })
      .mockResolvedValueOnce(HEALTH);
    renderEvaluate();
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("Preparing frozen model…")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByLabelText("Select or drop CSV/Parquet")).toBeEnabled();
  });

  it.each([
    [422, "invalid_schema", "Columns are invalid.", "File could not be evaluated"],
    [408, "upload_timeout", "The upload exceeded its deadline.", "Upload timed out"],
    [429, "analysis_busy", "Another analysis owns the slot.", "Analysis is busy"],
    [503, "model_not_ready", "Prepare the model first.", "File could not be evaluated"],
  ] as const)("shows structured status %s failures without echoing raw data", async (status, code, message, heading) => {
    vi.mocked(api.evaluateFile).mockRejectedValueOnce(new api.ApiError(status, code, message, [{ field: "time", message: "Use epoch seconds." }], status === 429 ? 6 : null));
    renderEvaluate();
    await uploadCsv("analyst-data.csv");
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByText(/Use epoch seconds/)).toBeInTheDocument();
    if (status === 429) expect(screen.getByText(/6 seconds/)).toBeInTheDocument();
  });

  it("falls back safely when a non-API failure reaches the page", async () => {
    vi.mocked(api.evaluateFile).mockRejectedValueOnce(new Error("secret raw payload"));
    renderEvaluate();
    await uploadCsv();
    expect(await screen.findByText("The evaluation service could not be reached.")).toBeInTheDocument();
    expect(screen.queryByText(/secret raw payload/)).not.toBeInTheDocument();
  });

  it("allows selecting the same file after Replace file", async () => {
    renderEvaluate();
    const input = await screen.findByLabelText("Select or drop CSV/Parquet");
    const file = new File(["time,icao24\n"], "same.csv", { type: "text/csv" });
    await userEvent.upload(input, file);
    await screen.findByRole("heading", { name: "a1b2c3_1773651600#1" });
    await userEvent.click(screen.getByRole("button", { name: "Replace file" }));
    await userEvent.upload(input, file);
    expect(api.evaluateFile).toHaveBeenCalledTimes(2);
  });

  it("ignores a late result after a replacement wins the request race", async () => {
    let resolveFirst!: (value: api.EvaluationResponse) => void;
    const first = new Promise<api.EvaluationResponse>((resolve) => { resolveFirst = resolve; });
    vi.mocked(api.evaluateFile)
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(response([result("eval-two", "d4e5f6_1773651700#1", 0.1)]));
    renderEvaluate();
    await uploadCsv("first.csv");
    const drop = screen.getByText("Select or drop CSV/Parquet").parentElement!;
    const second = new File(["time,icao24\n"], "second.csv", { type: "text/csv" });
    fireEvent.drop(drop, { dataTransfer: { files: [second] } });
    expect(await screen.findByRole("heading", { name: "d4e5f6_1773651700#1" })).toBeInTheDocument();

    resolveFirst(response([result("eval-stale", "stale_1773651800#1", 0.8)]));
    await Promise.resolve();
    expect(screen.queryByText("stale_1773651800#1")).not.toBeInTheDocument();
  });

  it("renders quality-first neutral evidence and switches accepted segments", async () => {
    vi.mocked(api.evaluateFile).mockResolvedValueOnce(response([
      result("eval-one", "a1b2c3_1773651600#1", 0.4),
      result("eval-two", "d4e5f6_1773651700#1", 0.1),
    ]));
    renderEvaluate();
    await uploadCsv();
    expect(await screen.findByRole("heading", { name: "Assessability and data quality" })).toBeInTheDocument();
    expect(screen.getByText("above threshold")).toBeInTheDocument();
    expect(screen.getByText(/not a safety or operational verdict/i)).toBeInTheDocument();
    expect(screen.getByText(/No generated narrative for uploaded data\./)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Accepted segment"), "eval-two");
    expect(screen.getByRole("heading", { name: "d4e5f6_1773651700#1" })).toBeInTheDocument();
    expect(screen.getByText("below threshold")).toBeInTheDocument();
  });

  it("exports locally, clears explicitly, and starts empty after remount", async () => {
    const createObjectURL = vi.fn(() => "blob:evaluation");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const view = renderEvaluate();
    await uploadCsv();
    await screen.findByText("Dataset summary");

    await userEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:evaluation");

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("Dataset summary")).not.toBeInTheDocument();
    view.unmount();
    renderEvaluate();
    expect(await screen.findByLabelText("Select or drop CSV/Parquet")).toBeEnabled();
    expect(screen.queryByText("Dataset summary")).not.toBeInTheDocument();
  });

  it("cancels with the keyboard and exposes the desktop-only guard", async () => {
    vi.mocked(api.evaluateFile).mockReturnValueOnce(new Promise(() => undefined));
    const view = renderEvaluate();
    await uploadCsv();
    const cancel = await screen.findByRole("button", { name: "Cancel" });
    cancel.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByLabelText("Select or drop CSV/Parquet")).toBeEnabled();
    view.unmount();

    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderEvaluate();
    expect(await screen.findByText("Desktop workspace required")).toBeInTheDocument();
    expect(screen.queryByLabelText("Select or drop CSV/Parquet")).not.toBeInTheDocument();
  });

  it("shows a warm zero-accepted state", async () => {
    vi.mocked(api.evaluateFile).mockResolvedValueOnce(response([]));
    renderEvaluate();
    await uploadCsv();
    expect(await screen.findByText("No assessable LEMD-engaging segments")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeEnabled();
  });
});
