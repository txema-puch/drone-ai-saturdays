import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Evidence from "../pages/Evidence";
import type { ResearchEvidence } from "../api";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getEvidence: vi.fn(),
}));

const CITATION = "Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic, and Matthias Wilhelm. Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research. IPSN 2014.";

const EVIDENCE: ResearchEvidence = {
  schema_version: "approach_aggregate_results_v1",
  basis: "real_opensky_research_data",
  generated_at: "2026-07-18",
  qualification: "not_qualified_no_independent_labels_or_fresh_holdout",
  allowed_role: "research_and_evidence_labeling_demonstrator",
  blocked_uses: ["operational_monitoring"],
  limitations: ["No independent human review labels are present."],
  cohorts: [{
    cohort_id: "2026_holdout", period: "March 2026", role: "single_burn_holdout",
    rows: 1_774_859, operations: 1_426, operations_with_attempts: 613,
    attempts: 613, assessable_attempts: 387, abstention_rate: null,
    review_rate_among_assessable: 0.2119,
    status_counts: { review_required: 82, partial_observation: 288 },
    outcome_counts: { go_around: "<10", final_gate_observed: "suppressed" },
    criterion_status_counts: {
      observed_descent_rate: { review_required: "<10", within_limit: "suppressed" },
    },
    interpretation_limits: ["Descriptive only."],
  }],
  data_access: {
    provider: "OpenSky Network",
    access_url: "https://opensky-network.org/data/data-access",
    terms_url: "https://opensky-network.org/about/terms-of-use",
    citation: CITATION,
    publication_notice_status: "pending",
    publication_notice_date: null,
  },
};

beforeEach(() => vi.mocked(api.getEvidence).mockResolvedValue(EVIDENCE));
afterEach(() => vi.clearAllMocks());

describe("aggregate research evidence", () => {
  it("renders the frozen sections in order with suppression-safe cells", async () => {
    render(<Evidence />);
    expect(await screen.findByRole("heading", { name: "Research evidence", level: 1 })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual([
      "What is real here", "Cohorts", "What findings mean", "What is missing",
      "How to access source data", "Citation and publication notice", "How demo cases differ",
    ]);
    expect(screen.getAllByText("Fewer than 10 (suppressed)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Suppressed to protect a small companion cell").length).toBeGreaterThan(0);
    expect(screen.getByText("Not published because its numerator or denominator is suppressed")).toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it("states limits, direct source access, exact citation, and notice fields", async () => {
    render(<Evidence />);
    expect(await screen.findByText(/No individual trajectory or source record is published/i)).toBeInTheDocument();
    expect(screen.getByText(/precision and recall are not available/i)).toBeInTheDocument();
    expect(screen.getByText(/does not support a safety claim, emergency-detection claim or operational qualification/i)).toBeInTheDocument();
    expect(screen.getByText(CITATION)).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "P" && element.textContent === "Publication notice is pending. No notice date is recorded.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "OpenSky data access" })).toMatchObject({ target: "_blank", rel: "noreferrer" });
    expect(screen.getByRole("link", { name: "OpenSky terms of use" })).toHaveAttribute("href", EVIDENCE.data_access.terms_url);
    expect(screen.getByText(/scenario mix is curated for learning and must not be interpreted as prevalence/i)).toBeInTheDocument();
  });

  it("shows a stable loading state and retries a bounded error", async () => {
    let resolveEvidence: ((value: ResearchEvidence) => void) | undefined;
    vi.mocked(api.getEvidence).mockReturnValueOnce(new Promise((resolve) => { resolveEvidence = resolve; }));
    const view = render(<Evidence />);
    expect(screen.getByLabelText("Loading research evidence")).toHaveAttribute("aria-busy", "true");
    resolveEvidence?.(EVIDENCE);
    expect(await screen.findByRole("heading", { name: "Research evidence", level: 1 })).toBeInTheDocument();
    view.unmount();

    vi.mocked(api.getEvidence).mockClear();
    vi.mocked(api.getEvidence).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(EVIDENCE);
    render(<Evidence />);
    await userEvent.click(await screen.findByRole("button", { name: "Retry research evidence" }));
    await waitFor(() => expect(api.getEvidence).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("heading", { name: "Research evidence", level: 1 })).toBeInTheDocument();
  });
});
