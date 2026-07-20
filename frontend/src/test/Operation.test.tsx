import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import Operation from "../pages/Operation";
import { APPROACH_OPERATION } from "./approachFixtures";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getApproachOperation: vi.fn(),
}));

beforeEach(() => vi.mocked(api.getApproachOperation).mockResolvedValue(APPROACH_OPERATION));
afterEach(() => vi.clearAllMocks());

describe("operation context", () => {
  it("groups attempts without merging their assessments", async () => {
    render(<MemoryRouter initialEntries={["/approach-operations/OP-LEMD-001"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes><Route path="/approach-operations/:operationRef" element={<Operation />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Generated operation" })).toBeInTheDocument();
    expect(screen.getByText("att-op-1-01")).toBeInTheDocument();
    expect(screen.getByText("att-op-2-01")).toBeInTheDocument();
    expect(screen.getByText(/No recorded flight is represented/i)).toBeInTheDocument();
    expect(screen.getByText("Synthetic demonstration case", { selector: ".origin-badge" })).toBeInTheDocument();
  });

  it("provides a retry and queue escape when grouping fails", async () => {
    vi.mocked(api.getApproachOperation).mockRejectedValueOnce(new Error("offline"));
    render(<MemoryRouter initialEntries={["/approach-operations/OP-LEMD-001"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes><Route path="/approach-operations/:operationRef" element={<Operation />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Operation context unavailable");
    expect(screen.getByRole("link", { name: "Return to attempts" })).toHaveAttribute("href", "/");
  });
});
