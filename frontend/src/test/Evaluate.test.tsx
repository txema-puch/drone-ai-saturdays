import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Evaluate from "../pages/Evaluate";
import { APPROACH_HEALTH, APPROACH_UPLOAD } from "./approachFixtures";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getHealth: vi.fn(),
  evaluateApproachFile: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(api.getHealth).mockResolvedValue(APPROACH_HEALTH);
  vi.mocked(api.evaluateApproachFile).mockResolvedValue(APPROACH_UPLOAD);
});
afterEach(() => vi.clearAllMocks());

function renderEvaluate() {
  return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Evaluate /></MemoryRouter>);
}

describe("rules-first upload", () => {
  it("offers evaluation without preparing a model", async () => {
    renderEvaluate();
    const input = await screen.findByLabelText("Choose operational record");
    expect(input).toBeEnabled();
    expect(screen.queryByText(/prepare model/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Missing channels abstain/i)).toBeInTheDocument();
    expect(screen.getByText("qnh_hpa")).toBeInTheDocument();
    expect(screen.getByText(/not qualified no independent labels or fresh holdout/i)).toBeInTheDocument();
    expect(screen.getByText(/third, separate lane/i)).toBeInTheDocument();
    expect(screen.getByText(/responsible for permission/i)).toBeInTheDocument();
  });

  it("retains the selected filename and returns attempt vocabulary", async () => {
    renderEvaluate();
    const input = await screen.findByLabelText("Choose operational record");
    await userEvent.upload(input, new File(["time,lat,lon\n"], "approaches.csv", { type: "text/csv" }));
    expect(screen.getByText("approaches.csv")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Evaluate approach attempts" }));
    expect(await screen.findByRole("heading", { name: "1 approach attempts" })).toBeInTheDocument();
    expect(screen.getByText(/Origin: User upload · processed ephemerally · not retained/i)).toBeInTheDocument();
    expect(screen.getByText("Review required")).toBeInTheDocument();
    expect(screen.getByText(/partial evidence retained/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Inspect criterion evidence"));
    expect(screen.getByText(/46 observed rows/i)).toBeInTheDocument();
    expect(screen.getByText(/QNH 1003.0 hPa/i)).toBeInTheDocument();
    expect(screen.getByText(/type ZZZZ · unknown reference fallback/i)).toBeInTheDocument();
  });

  it("focuses bounded field errors and keeps the file for retry", async () => {
    vi.mocked(api.evaluateApproachFile).mockRejectedValueOnce(new api.ApiError(422, "invalid_schema", "Required fields are missing.", [{ field: "time", message: "Use epoch seconds." }]));
    renderEvaluate();
    await userEvent.upload(await screen.findByLabelText("Choose operational record"), new File(["bad"], "bad.csv", { type: "text/csv" }));
    await userEvent.click(screen.getByRole("button", { name: "Evaluate approach attempts" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveFocus();
    expect(alert).toHaveTextContent("Use epoch seconds");
    expect(alert).not.toHaveTextContent("bad");
    expect(screen.getByText("bad.csv")).toBeInTheDocument();
  });

  it("offers the precomputed cohort when upload is disabled", async () => {
    vi.mocked(api.getHealth).mockResolvedValueOnce({ ...APPROACH_HEALTH, evaluation_enabled: false });
    renderEvaluate();
    expect(await screen.findByText(/not enabled in this release/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open approach attempts" })).toHaveAttribute("href", "/");
  });
});
