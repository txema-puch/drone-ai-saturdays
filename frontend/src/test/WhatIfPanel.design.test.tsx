import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import WhatIfPanel, {
  SIMULATION_TIMEOUT_MS,
  SIMULATION_TIMEOUT_SECONDS,
} from "../components/WhatIfPanel";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, simulate: vi.fn() };
});

const RESULT = {
  id: 3638,
  segment_id: "segment#1",
  kind: "sustained_loiter",
  intensity: 1,
  onset: 0.5,
  onset_index: 1,
  path: [],
  channels: {},
  scores: [],
  window_score: 0.4,
  original_score: 0.2,
  pct: 90,
  band: "elevated",
  anomalous: true,
  threshold: 0.222,
  step_threshold: 0.1,
  valid_steps: 0,
  center: { lat: 40.49, lon: -3.57 },
  step_seconds: 10,
} satisfies api.SimulationResult;

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
    const signal = vi.mocked(api.simulate).mock.calls[0][1];
    expect(screen.getByRole("button", { name: "RE-SCORING…" })).toBeDisabled();
    expect(screen.getByText(/first run on a sleeping demo server/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(SIMULATION_TIMEOUT_MS);
      await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "RETRY RE-SCORE →" })).toBeEnabled();
    expect(signal?.aborted).toBe(true);
    expect(
      screen.getByText(
        new RegExp(`did not finish loading within ${SIMULATION_TIMEOUT_SECONDS} seconds`, "i"),
      ),
    ).toBeInTheDocument();
  });

  it("clears the deadline and returns a fast successful result", async () => {
    vi.useFakeTimers();
    const onResult = vi.fn();
    vi.mocked(api.simulate).mockResolvedValue(RESULT);

    render(
      <WhatIfPanel
        flightId={RESULT.id}
        active={false}
        onResult={onResult}
        onClear={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));

    await act(async () => {
      await Promise.resolve();
    });
    expect(onResult).toHaveBeenCalledWith(RESULT);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the deadline and exposes a recoverable service error", async () => {
    vi.useFakeTimers();
    vi.mocked(api.simulate).mockRejectedValue(new Error("request failed: 503"));

    render(
      <WhatIfPanel
        flightId={RESULT.id}
        active={false}
        onResult={vi.fn()}
        onClear={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText(/re-score request failed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RETRY RE-SCORE →" })).toBeEnabled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ignores a late result after changing to another case", async () => {
    let resolveSimulation: (result: api.SimulationResult) => void = () => {};
    vi.mocked(api.simulate).mockReturnValue(
      new Promise((resolve) => {
        resolveSimulation = resolve;
      }),
    );
    const onResult = vi.fn();
    const props = {
      active: false,
      onResult,
      onClear: vi.fn(),
    };
    const { rerender } = render(<WhatIfPanel {...props} flightId={RESULT.id} />);
    fireEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));

    rerender(<WhatIfPanel {...props} flightId={RESULT.id + 1} />);
    await act(async () => resolveSimulation(RESULT));

    expect(onResult).not.toHaveBeenCalled();
  });

  it("shows a specific busy state when another server simulation is active", async () => {
    vi.mocked(api.simulate).mockRejectedValue(new api.ApiError(409));

    render(
      <WhatIfPanel
        flightId={RESULT.id}
        active={false}
        onResult={vi.fn()}
        onClear={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));

    expect(await screen.findByText(/still running on the demo server/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RETRY RE-SCORE →" })).toBeEnabled();
  });

  it("clears a successful overlay when its parameters change", () => {
    const onClear = vi.fn();
    render(
      <WhatIfPanel
        flightId={RESULT.id}
        active
        onResult={vi.fn()}
        onClear={onClear}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Intensity/), { target: { value: "25" } });

    expect(onClear).toHaveBeenCalledOnce();
  });

  it("ignores an in-flight result after its parameters change", async () => {
    let resolveSimulation: (result: api.SimulationResult) => void = () => {};
    vi.mocked(api.simulate).mockReturnValue(
      new Promise((resolve) => {
        resolveSimulation = resolve;
      }),
    );
    const onResult = vi.fn();
    render(
      <WhatIfPanel
        flightId={RESULT.id}
        active={false}
        onResult={onResult}
        onClear={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /RE-SCORE PERTURBED SEGMENT/ }));
    fireEvent.change(screen.getByLabelText(/Intensity/), { target: { value: "25" } });

    await act(async () => resolveSimulation(RESULT));

    expect(onResult).not.toHaveBeenCalled();
    expect(vi.mocked(api.simulate).mock.calls[0][1]?.aborted).toBe(true);
  });
});
