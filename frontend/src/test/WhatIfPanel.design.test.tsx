import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import WhatIfPanel, { SIMULATION_TIMEOUT_MS } from "../components/WhatIfPanel";

vi.mock("../api");

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("WhatIfPanel design recovery", () => {
  it("turns an unbounded cold-model wait into a specific retry state", async () => {
    vi.useFakeTimers();
    vi.mocked(api.simulate).mockReturnValue(new Promise(() => {}));

    render(
      <WhatIfPanel
        flightId={3638}
        active={false}
        onResult={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "RE-SCORE PERTURBED SEGMENT →" }));
    expect(screen.getByRole("button", { name: "RE-SCORING…" })).toBeDisabled();
    expect(screen.getByText(/first run on a sleeping demo server/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(SIMULATION_TIMEOUT_MS);
      await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "RETRY RE-SCORE →" })).toBeEnabled();
    expect(screen.getByText(/did not finish loading within 45 seconds/i)).toBeInTheDocument();
  });
});
