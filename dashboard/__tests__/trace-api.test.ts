/**
 * Sprint 4 — tests for the trace-related wrappers in lib/api.ts.
 *
 * Covers:
 *  - getTraces builds the right URL with each filter
 *  - getTrace encodes the orgId + traceDbId
 *  - createTraceStream returns an EventSource pointed at the
 *    org-scoped SSE endpoint
 */

import { getTraces, getTrace, createTraceStream, AUTH_TOKEN_KEY } from "@/lib/api";

describe("getTraces", () => {
  beforeEach(() => {
    (globalThis as any).fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
      })
    );
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(AUTH_TOKEN_KEY);
    }
  });

  it("hits the org-scoped path with no params", async () => {
    const fetchMock = globalThis.fetch as jest.Mock;
    await getTraces("org-1");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/orgs/org-1/traces"),
      expect.objectContaining({})
    );
    const url: string = fetchMock.mock.calls[0][0];
    expect(url).not.toContain("?");
  });

  it("serializes filters into the query string", async () => {
    const fetchMock = globalThis.fetch as jest.Mock;
    await getTraces("org-1", {
      workflow_id: "wf-1",
      status: "ok",
      limit: 25,
      since: "2026-06-20T12:00:00Z",
    });
    const url: string = fetchMock.mock.calls[0][0];
    expect(url).toContain("workflow_id=wf-1");
    expect(url).toContain("status=ok");
    expect(url).toContain("limit=25");
    expect(url).toContain("since=");
  });

  it("passes the status through to the server (filter happens server-side)", async () => {
    const fetchMock = globalThis.fetch as jest.Mock;
    await getTraces("org-1", { status: "all" as any });
    const url: string = fetchMock.mock.calls[0][0];
    // The wrapper doesn't try to be smart about "all"; it sends
    // every param. The server decides how to interpret it.
    expect(url).toContain("status=all");
  });

  it("attaches the bearer token from localStorage", async () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(AUTH_TOKEN_KEY, "tok-123");
    }
    const fetchMock = globalThis.fetch as jest.Mock;
    await getTraces("org-1");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok-123");
  });
});

describe("getTrace", () => {
  beforeEach(() => {
    (globalThis as any).fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      })
    );
  });

  it("encodes the orgId and traceDbId in the URL", async () => {
    const fetchMock = globalThis.fetch as jest.Mock;
    await getTrace("org-1", "trace-db-id");
    const url: string = fetchMock.mock.calls[0][0];
    expect(url).toContain("/api/orgs/org-1/traces/trace-db-id");
  });
});

describe("createTraceStream", () => {
  it("returns an EventSource pointed at the org's SSE endpoint", () => {
    // The jsdom polyfill doesn't always expose EventSource, so we
    // use a stub.
    const Real = (globalThis as any).EventSource;
    const stub = jest.fn(function () {
      return { url: "", withCredentials: false };
    });
    (globalThis as any).EventSource = stub;
    try {
      const es = createTraceStream("org-1") as any;
      expect(stub).toHaveBeenCalled();
      const arg = (stub.mock.calls as any[][])[0][0];
      expect(arg).toContain("/api/orgs/org-1/traces/stream");
      // With a real EventSource, the constructor stores the URL.
      void es;
    } finally {
      (globalThis as any).EventSource = Real;
    }
  });
});