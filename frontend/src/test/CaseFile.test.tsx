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
    expect(screen.getByRole("img", { name: /relative to runway 32L/i })).toBeInTheDocument();
    expect(screen.getByText("-9.2 m/s · limit -7.6", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("config012345")).toBeInTheDocument();
    expect(screen.getByText("1003 hPa")).toBeInTheDocument();
    expect(screen.getByText("A320")).toBeInTheDocument();
    expect(screen.getByText(/Actual mass.*ATC clearance.*remain unavailable/i)).toBeInTheDocument();
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

  it("explains abstention without creating a normal verdict", async () => {
    vi.mocked(api.getApproach).mockResolvedValueOnce({ ...APPROACH_DETAIL, status: "not_assessable", reasons: ["approach_coverage_gap"] });
    renderCase();
    expect(await screen.findByText("Assessment withheld.")).toBeInTheDocument();
    expect(screen.getByText(/No normal or abnormal verdict is inferred/i)).toBeInTheDocument();
  });
});
