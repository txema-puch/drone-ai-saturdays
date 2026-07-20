import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import * as api from "../api";
import { APPROACH_DETAIL, APPROACH_HEALTH, APPROACH_OPERATION, REVIEW_ATTEMPT } from "./approachFixtures";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getApproaches: vi.fn(),
  getHealth: vi.fn(),
  getEvidence: vi.fn(),
  getApproach: vi.fn(),
  getApproachOperation: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(api.getApproaches).mockResolvedValue([REVIEW_ATTEMPT]);
  vi.mocked(api.getHealth).mockResolvedValue(APPROACH_HEALTH);
  vi.mocked(api.getApproach).mockResolvedValue(APPROACH_DETAIL);
  vi.mocked(api.getApproachOperation).mockResolvedValue(APPROACH_OPERATION);
  vi.mocked(api.getEvidence).mockResolvedValue({
    schema_version: "approach_aggregate_results_v1",
    basis: "real_opensky_research_data",
    generated_at: "2026-07-18",
    qualification: "not_qualified_no_independent_labels_or_fresh_holdout",
    allowed_role: "research_and_evidence_labeling_demonstrator",
    blocked_uses: [], limitations: [], cohorts: [],
    data_access: { provider: "OpenSky Network", access_url: "https://opensky-network.org/data/data-access", terms_url: "https://opensky-network.org/about/terms-of-use", citation: "Citation", publication_notice_status: "pending", publication_notice_date: null },
  });
});
afterEach(() => vi.clearAllMocks());

describe("attempt-first navigation", () => {
  it("moves from queue to canonical dossier and operation context", async () => {
    render(<MemoryRouter initialEntries={["/"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><App /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("link", { name: /Open synthetic scenario Lower-than-reference speed/i }));
    expect(await screen.findByRole("heading", { name: "Review required", level: 1 })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "OP-LEMD-001" }));
    expect(await screen.findByRole("heading", { name: "Generated operation" })).toBeInTheDocument();
  });

  it("keeps the data-origin boundary visible on every workflow route", async () => {
    const routes = ["/", "/approaches/att-op-1-01", "/approach-operations/OP-LEMD-001", "/evaluate", "/evidence"];
    for (const route of routes) {
      const view = render(<MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><App /></MemoryRouter>);
      expect(await screen.findByText("Synthetic demo cases · Real research results shown only in aggregate.")).toBeVisible();
      expect(screen.getByRole("link", { name: "Research evidence" })).toHaveAttribute("href", "/evidence");
      view.unmount();
    }
  });

  it("keeps upload navigation visible as a first-class workflow", async () => {
    render(<MemoryRouter initialEntries={["/"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><App /></MemoryRouter>);
    await userEvent.click(screen.getByRole("link", { name: "Evaluate data" }));
    expect(await screen.findByRole("heading", { name: "Evaluate operational data" })).toBeInTheDocument();
  });
});
