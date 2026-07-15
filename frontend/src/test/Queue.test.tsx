import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Queue from "../pages/Queue";
import { APPROACH_HEALTH, PARTIAL_ATTEMPT, REVIEW_ATTEMPT } from "./approachFixtures";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getApproaches: vi.fn(),
  getHealth: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(api.getApproaches).mockResolvedValue([PARTIAL_ATTEMPT, REVIEW_ATTEMPT]);
  vi.mocked(api.getHealth).mockResolvedValue(APPROACH_HEALTH);
});
afterEach(() => vi.clearAllMocks());

function renderQueue(entry = "/") {
  return render(<MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Queue /></MemoryRouter>);
}

describe("attempt queue", () => {
  it("leads with review status, evidence, coverage and cohort scope", async () => {
    renderQueue();
    const links = await screen.findAllByRole("link", { name: /Open approach attempt/ });
    expect(links[0]).toHaveAccessibleName(/att-op-1-01: Review Required, runway 32L/i);
    expect(screen.getByText("Observed Descent Rate")).toBeInTheDocument();
    expect(screen.getByText("96% observed")).toBeInTheDocument();
    expect(screen.getByText("release approach-release-33")).toBeInTheDocument();
    expect(screen.getByText(/does not detect emergencies/i)).toBeInTheDocument();
  });

  it("persists server filters in the URL contract", async () => {
    renderQueue("/?status=partial_observation&direction=18");
    await screen.findByText("att-op-2-01");
    await waitFor(() => expect(api.getApproaches).toHaveBeenCalledWith(
      expect.objectContaining({ status: "partial_observation", direction: "18" }),
      expect.any(AbortSignal),
    ));
    expect(screen.getByLabelText("Status")).toHaveValue("partial_observation");
  });

  it("keeps filters on error and recovers through the bounded retry", async () => {
    vi.mocked(api.getApproaches).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([REVIEW_ATTEMPT]);
    renderQueue("/?status=review_required");
    await userEvent.click(await screen.findByRole("button", { name: "Retry with these filters" }));
    expect(await screen.findByText("att-op-1-01")).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toHaveValue("review_required");
  });
});
