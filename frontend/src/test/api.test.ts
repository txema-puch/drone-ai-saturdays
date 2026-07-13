import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getFlight, getFlights, getHealth, getOperation, getOperations, simulate } from "../api";

afterEach(() => vi.unstubAllGlobals());

function mockFetch(impl: (url: string, init?: RequestInit) => Partial<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => Promise.resolve(impl(url, init) as Response)),
  );
}

describe("api client", () => {
  it("requests the ranked queue with limit + order", async () => {
    let seen = "";
    mockFetch((url) => {
      seen = url;
      return { ok: true, json: () => Promise.resolve([]) };
    });
    await getFlights(80, "anomalous");
    expect(seen).toBe("/api/flights?limit=80&order=anomalous");
  });

  it("requests operation summaries with limit + order", async () => {
    let seen = "";
    mockFetch((url) => {
      seen = url;
      return { ok: true, json: () => Promise.resolve([]) };
    });
    await getOperations(200, "typical");
    expect(seen).toBe("/api/operations?limit=200&order=typical");
  });

  it("encodes the operation reference for the dossier endpoint", async () => {
    let seen = "";
    mockFetch((url) => {
      seen = url;
      return { ok: true, json: () => Promise.resolve({}) };
    });
    await getOperation("OP-502CE6-1543855510");
    expect(seen).toBe("/api/operations/OP-502CE6-1543855510");
    await getFlight(4238);
    expect(seen).toBe("/api/flights/4238");
  });

  it("throws with the status code on a non-ok response", async () => {
    mockFetch(() => ({ ok: false, status: 503, json: () => Promise.resolve({}) }));
    await expect(getHealth()).rejects.toThrow("503");
  });

  it("surfaces the 501 from the simulate stub", async () => {
    mockFetch(() => ({ ok: false, status: 501, json: () => Promise.resolve({}) }));
    const error = await simulate({ id: 1, kind: "speed_spike", intensity: 1, onset: 0.5 })
      .catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(501);
  });

  it("passes cancellation through to the simulation request", async () => {
    let seenSignal: AbortSignal | null | undefined;
    mockFetch((_url, init) => {
      seenSignal = init?.signal;
      return { ok: true, json: () => Promise.resolve({}) };
    });
    const controller = new AbortController();

    await simulate(
      { id: 1, kind: "speed_spike", intensity: 1, onset: 0.5 },
      controller.signal,
    );

    expect(seenSignal).toBe(controller.signal);
  });
});
