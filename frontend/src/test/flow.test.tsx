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
  getApproach: vi.fn(),
  getApproachOperation: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(api.getApproaches).mockResolvedValue([REVIEW_ATTEMPT]);
  vi.mocked(api.getHealth).mockResolvedValue(APPROACH_HEALTH);
  vi.mocked(api.getApproach).mockResolvedValue(APPROACH_DETAIL);
  vi.mocked(api.getApproachOperation).mockResolvedValue(APPROACH_OPERATION);
});
afterEach(() => vi.clearAllMocks());

describe("attempt-first navigation", () => {
  it("moves from queue to canonical dossier and operation context", async () => {
    render(<MemoryRouter initialEntries={["/"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><App /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("link", { name: /Open approach attempt att-op-1-01/i }));
    expect(await screen.findByRole("heading", { name: "Review required", level: 1 })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "OP-LEMD-001" }));
    expect(await screen.findByRole("heading", { name: "Observed operation" })).toBeInTheDocument();
  });

  it("keeps upload navigation visible as a first-class workflow", async () => {
    render(<MemoryRouter initialEntries={["/"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><App /></MemoryRouter>);
    await userEvent.click(screen.getByRole("link", { name: "Evaluate data" }));
    expect(await screen.findByRole("heading", { name: "Evaluate operational data" })).toBeInTheDocument();
  });
});
