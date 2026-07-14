import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, evaluateFile, getFlight, getFlights, getHealth, getOperation, getOperations, prepareModel, simulate } from "../api";

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
    await getFlight("c_c2bwwjgaxbqg43kb");
    expect(seen).toBe("/api/flights/c_c2bwwjgaxbqg43kb");
  });

  it("throws with the status code on a non-ok response", async () => {
    mockFetch(() => ({ ok: false, status: 503, json: () => Promise.resolve({}) }));
    await expect(getHealth()).rejects.toThrow("503");
  });

  it("surfaces the 501 from the simulate stub", async () => {
    mockFetch(() => ({ ok: false, status: 501, json: () => Promise.resolve({}) }));
    const error = await simulate({ case_id: "c_c2bwwjgaxbqg43kb", kind: "speed_spike", intensity: 1, onset: 0.5 })
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
      { case_id: "c_c2bwwjgaxbqg43kb", kind: "speed_spike", intensity: 1, onset: 0.5 },
      controller.signal,
    );

    expect(seenSignal).toBe(controller.signal);
  });

  it.each([408, 429, 503])("retains structured errors for status %s", async (status) => {
    mockFetch(() => ({
      ok: false,
      status,
      headers: new Headers({ "Retry-After": "7" }),
      json: () => Promise.resolve({
        detail: {
          code: "bounded_failure",
          message: "The bounded request failed.",
          fields: [{ field: "time", message: "Use epoch seconds.", code: "invalid_unit" }],
        },
      }),
    }));

    const error = await prepareModel().catch((caught) => caught as ApiError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status,
      code: "bounded_failure",
      message: "The bounded request failed.",
      retryAfter: 7,
      fields: [{ field: "time", message: "Use epoch seconds.", code: "invalid_unit" }],
    });
  });

  it("uses a bounded fallback for malformed error bodies", async () => {
    mockFetch(() => ({
      ok: false,
      status: 422,
      headers: new Headers(),
      json: () => Promise.reject(new SyntaxError("bad json")),
    }));

    const error = await getHealth().catch((caught) => caught as ApiError);
    expect(error).toMatchObject({ status: 422, code: "request_failed", message: "Request failed (422)", fields: [] });
  });

  it("does not materialize oversized error bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("x".repeat(64 * 1024 + 1), { status: 422 }))),
    );

    const error = await getHealth().catch((caught) => caught as ApiError);
    expect(error).toMatchObject({ status: 422, code: "request_failed", message: "Request failed (422)", fields: [] });
  });

  it("posts one multipart file without setting a content-type boundary", async () => {
    let seenUrl = "";
    let seenInit: RequestInit | undefined;
    mockFetch((url, init) => {
      seenUrl = url;
      seenInit = init;
      return { ok: true, json: () => Promise.resolve({ results: [] }) };
    });
    const file = new File(["time,icao24\n"], "sample.csv", { type: "text/csv" });

    await evaluateFile(file);

    expect(seenUrl).toBe("/api/evaluations");
    expect(seenInit?.method).toBe("POST");
    expect(seenInit?.body).toBeInstanceOf(FormData);
    expect(seenInit?.headers).toBeUndefined();
    expect((seenInit?.body as FormData).get("file")).toBe(file);
  });
});
