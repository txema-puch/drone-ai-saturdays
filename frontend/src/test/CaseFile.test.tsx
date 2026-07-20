import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import CaseFile from "../pages/CaseFile";
import { APPROACH_DETAIL } from "./approachFixtures";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getApproach: vi.fn(),
}));

beforeEach(() => vi.mocked(api.getApproach).mockResolvedValue(APPROACH_DETAIL));
afterEach(() => vi.clearAllMocks());

function renderCase() {
  return render(
    <MemoryRouter initialEntries={["/approaches/att-op-1-01"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes><Route path="/approaches/:attemptId" element={<CaseFile />} /></Routes>
    </MemoryRouter>,
  );
}

describe("attempt dossier", () => {
  it("renders plain status, direct evidence, quality and provenance", async () => {
    renderCase();
    expect(await screen.findByRole("heading", { name: "Review required", level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/One or more observed approach criteria crossed/i)).toHaveLength(2);
    expect(screen.getByRole("img", { name: "Synchronized generated signal profiles" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /relative to runway 32L/i })).toBeInTheDocument();
    expect(screen.getByText("-9.2 m/s · limit -7.6", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("config012345")).toBeInTheDocument();
    expect(screen.getByText("1003 hPa")).toBeInTheDocument();
    expect(screen.getByText("A320")).toBeInTheDocument();
    expect(screen.getByText(/Actual mass.*ATC clearance.*remain unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("Synthetic demonstration case", { selector: ".origin-badge" })).toBeInTheDocument();
    expect(screen.getByText(/Lower-than-reference speed/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Generated evidence" })).toBeInTheDocument();
    expect(screen.getByText(/No recorded flight is represented/i)).toBeInTheDocument();
  });

  it("keeps the historical model collapsed and explicitly outside the verdict", async () => {
    renderCase();
    const disclosure = await screen.findByText("Research benchmark", { exact: false });
    expect(disclosure.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(/Does not determine this assessment/i)).toBeInTheDocument();
  });

  it("synchronizes the scrubber with the live evidence readout", async () => {
    renderCase();
    const scrubber = await screen.findByLabelText("Scrub synchronized map and evidence timeline");
    fireEvent.change(scrubber, { target: { value: "1773651750" } });
    expect(screen.getByText(/4.5 km from threshold/i)).toBeInTheDocument();
  });

  it("explains a selected ground-speed crossing in operational units", async () => {
    renderCase();
    const crossing = await screen.findByRole("button", {
      name: /Observed ground speed envelope evidence from/i,
    });
    fireEvent.click(crossing);

    expect(screen.getByRole("heading", {
      name: "Lower-than-reference ground speed",
    })).toBeInTheDocument();
    expect(screen.getByText("143 kt")).toBeInTheDocument();
    expect(screen.getByText("153 kt")).toBeInTheDocument();
    expect(screen.getByText("−10 kt")).toBeInTheDocument();
    expect(screen.getByText("30 seconds")).toBeInTheDocument();
    expect(screen.getByText("10.1 km before RWY 32L")).toBeInTheDocument();
    expect(screen.getByText(/statistical comparison, not a safety-limit violation/i)).toBeInTheDocument();
  });

  it("states where evidence ends when the runway threshold was not observed", async () => {
    vi.mocked(api.getApproach).mockResolvedValueOnce({
      ...APPROACH_DETAIL,
      outcome: "final_gate_observed",
    });
    renderCase();
    expect(await screen.findByText(
      "Evidence ends here — 0.5 km before the runway. Landing outcome unavailable.",
    )).toBeInTheDocument();
  });

  it("explains abstention without creating a normal verdict", async () => {
    vi.mocked(api.getApproach).mockResolvedValueOnce({ ...APPROACH_DETAIL, status: "not_assessable", reasons: ["approach_coverage_gap"] });
    renderCase();
    expect(await screen.findByText("Assessment withheld.")).toBeInTheDocument();
    expect(screen.getByText(/No normal or abnormal verdict is inferred/i)).toBeInTheDocument();
  });

  it("separates pair-level inference from the provisional geometry anchor", async () => {
    vi.mocked(api.getApproach).mockResolvedValueOnce({
      ...APPROACH_DETAIL,
      runway: "18_pair",
      direction: "18",
      geometry_runway: "18L",
      runway_specificity: "direction",
    });
    renderCase();
    expect(await screen.findByText(/18_pair · pair-level/i)).toBeInTheDocument();
    expect(screen.getByText(/18L · provisional computation only/i)).toBeInTheDocument();
    expect(screen.getByText(/not a claim that the aircraft used that exact runway/i)).toBeInTheDocument();
  });
});
