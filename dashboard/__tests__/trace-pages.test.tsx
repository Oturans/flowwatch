/**
 * Sprint 4 — integration tests for the trace pages.
 *
 * Mount the TracesPage and TraceDetailPage with a mocked
 * AuthContext so we can exercise their data fetching, the
 * real-time SSE wiring, and the filter/sort UI without
 * needing a real backend.
 */

import React, { ReactNode } from "react";
import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import TracesPage from "@/app/traces/page";
import TraceDetailPage from "@/app/traces/[id]/page";

// Mock next/navigation (jest.setup.js already does this globally
// but we override useParams here for the detail page).
const mockParams = { id: "trace-1" };
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
  useParams: () => mockParams,
  usePathname: () => "/traces",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock the auth context to return a known org id.
const mockUseOrgId = jest.fn(() => "org-1");
jest.mock("@/components/auth/AuthContext", () => ({
  useOrgId: () => mockUseOrgId(),
  useAuth: () => ({
    user: { id: "u-1", email: "a@b", org_id: "org-1", role: "owner", is_active: true },
    tenant: { id: "org-1", name: "T", slug: "t", plan: "free", is_active: true },
    token: "tok",
    status: "authenticated",
    login: jest.fn(),
    register: jest.fn(),
    logout: jest.fn(),
    refresh: jest.fn(),
    hasToken: true,
  }),
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  AuthGuard: ({ children }: { children: ReactNode }) => children,
}));

// Mock the lib/api module with controllable responses.
const mockGetTraces = jest.fn();
const mockGetTrace = jest.fn();

const traceFixture = (overrides: any = {}) => ({
  id: overrides.id ?? "t-1",
  org_id: "org-1",
  trace_id: overrides.trace_id ?? "trace-1",
  workflow_id: overrides.workflow_id ?? "wf-1",
  name: overrides.name ?? "demo",
  source: overrides.source ?? "n8n",
  status: overrides.status ?? "ok",
  started_at: overrides.started_at ?? "2026-06-20T12:00:00Z",
  ended_at: overrides.ended_at ?? "2026-06-20T12:00:01Z",
  duration_ms: overrides.duration_ms ?? 1000,
  attributes: overrides.attributes ?? null,
  error_message: overrides.error_message ?? null,
  spans: overrides.spans ?? [],
  created_at: overrides.created_at ?? "2026-06-20T12:00:00Z",
});

jest.mock("@/lib/api", () => ({
  __esModule: true,
  getTraces: (...args: any[]) => mockGetTraces(...args),
  getTrace: (...args: any[]) => mockGetTrace(...args),
  createTraceStream: (...args: any[]) => {
    const fake = makeFakeEventSource();
    latestFake = fake;
    return fake;
  },
  getSources: jest.fn(() => Promise.resolve([])),
  getStoredToken: jest.fn(() => null),
  getStoredUser: jest.fn(() => null),
  storeAuth: jest.fn(),
  clearAuth: jest.fn(),
  fetchMe: jest.fn(),
  login: jest.fn(),
  register: jest.fn(),
  refresh: jest.fn(),
  createEventSource: jest.fn(),
}));

function makeFakeEventSource() {
  const listeners: Record<string, Array<(ev: any) => void>> = {};
  return {
    onmessage: null as null | ((ev: any) => void),
    onerror: null as null | ((ev: any) => void),
    closed: false,
    addEventListener(name: string, cb: (ev: any) => void) {
      (listeners[name] ??= []).push(cb);
    },
    close() {
      this.closed = true;
    },
    emit(payload: unknown) {
      const handler = this.onmessage ?? listeners["message"]?.[0];
      if (handler) handler({ data: JSON.stringify(payload) });
    },
  };
}

let latestFake: ReturnType<typeof makeFakeEventSource> | null = null;

function withQuery(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>
  );
}

beforeEach(() => {
  mockGetTraces.mockReset();
  mockGetTrace.mockReset();
  mockUseOrgId.mockReturnValue("org-1");
  mockParams.id = "trace-1";
  latestFake = null;
});

describe("TracesPage", () => {
  it("shows a loading state while the query is in-flight", () => {
    mockGetTraces.mockReturnValue(new Promise(() => {}));
    withQuery(<TracesPage />);
    expect(screen.getByText(/Loading traces/i)).toBeTruthy();
  });

  it("renders the empty state when there are no traces", async () => {
    mockGetTraces.mockResolvedValue([]);
    withQuery(<TracesPage />);
    await waitFor(() => {
      expect(screen.getByText(/No traces recorded yet/i)).toBeTruthy();
    });
  });

  it("renders one row per trace", async () => {
    mockGetTraces.mockResolvedValue([
      traceFixture({ id: "1", name: "alpha", status: "ok" }),
      traceFixture({ id: "2", name: "bravo", status: "error" }),
    ]);
    withQuery(<TracesPage />);
    await waitFor(() => {
      expect(screen.getByTestId("trace-row-1")).toBeTruthy();
      expect(screen.getByTestId("trace-row-2")).toBeTruthy();
    });
  });

  it("filters the table when the search field is typed into", async () => {
    mockGetTraces.mockResolvedValue([
      traceFixture({ id: "1", name: "alpha" }),
      traceFixture({ id: "2", name: "bravo" }),
    ]);
    withQuery(<TracesPage />);
    await waitFor(() => screen.getByTestId("trace-row-1"));
    const search = screen.getByTestId("trace-filter-search");
    fireEvent.change(search, { target: { value: "bravo" } });
    await waitFor(() => {
      expect(screen.queryByTestId("trace-row-1")).toBeNull();
      expect(screen.getByTestId("trace-row-2")).toBeTruthy();
    });
  });

  it("filters by status chip click", async () => {
    mockGetTraces.mockResolvedValue([
      traceFixture({ id: "1", status: "ok" }),
      traceFixture({ id: "2", status: "error" }),
    ]);
    withQuery(<TracesPage />);
    await waitFor(() => screen.getByTestId("trace-row-1"));
    fireEvent.click(screen.getByTestId("status-chip-error"));
    await waitFor(() => {
      expect(screen.queryByTestId("trace-row-1")).toBeNull();
      expect(screen.getByTestId("trace-row-2")).toBeTruthy();
    });
  });

  it("shows an error message when the fetch fails", async () => {
    mockGetTraces.mockRejectedValue(new Error("boom"));
    withQuery(<TracesPage />);
    await waitFor(() => {
      expect(screen.getByText(/Failed to load traces/i)).toBeTruthy();
    });
  });

  it("subscribes to the SSE stream on mount", async () => {
    mockGetTraces.mockResolvedValue([]);
    withQuery(<TracesPage />);
    await waitFor(() => screen.getByText(/No traces recorded yet/i));
    expect(latestFake).not.toBeNull();
  });

  it("prepends new traces received via SSE", async () => {
    mockGetTraces.mockResolvedValue([
      traceFixture({ id: "1", name: "old" }),
    ]);
    withQuery(<TracesPage />);
    await waitFor(() => screen.getByTestId("trace-row-1"));
    expect(latestFake).not.toBeNull();
    act(() => {
      latestFake!.emit(traceFixture({ id: "2", name: "new", status: "ok" }));
    });
    await waitFor(() => {
      expect(screen.getByTestId("trace-row-2")).toBeTruthy();
    });
  });

  it("toggles the DAG preview", async () => {
    mockGetTraces.mockResolvedValue([
      traceFixture({
        id: "1",
        name: "with-dag",
        spans: [
          { span_id: "a", name: "root", status: "ok" },
          { span_id: "b", parent_id: "a", name: "child", status: "ok" },
        ],
      }),
    ]);
    withQuery(<TracesPage />);
    await waitFor(() => screen.getByTestId("trace-row-1"));
    expect(screen.queryByTestId("trace-dag-section")).toBeNull();
    fireEvent.click(screen.getByTestId("toggle-dag"));
    expect(screen.getByTestId("trace-dag-section")).toBeTruthy();
  });
});

describe("TraceDetailPage", () => {
  it("shows a loading state while the query is in-flight", () => {
    mockGetTrace.mockReturnValue(new Promise(() => {}));
    withQuery(<TraceDetailPage />);
    expect(screen.getByText(/Loading trace/i)).toBeTruthy();
  });

  it("renders the trace name and a DAG", async () => {
    mockGetTrace.mockResolvedValue(
      traceFixture({
        id: "trace-1",
        name: "shown",
        spans: [
          { span_id: "a", name: "root", status: "ok" },
          { span_id: "b", parent_id: "a", name: "child", status: "ok" },
        ],
      })
    );
    withQuery(<TraceDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("shown")).toBeTruthy();
      expect(screen.getByTestId("trace-dag-section")).toBeTruthy();
      expect(screen.getByTestId("trace-timeline-section")).toBeTruthy();
    });
  });

  it("shows a 404 message when the trace is missing", async () => {
    mockGetTrace.mockResolvedValue(null);
    withQuery(<TraceDetailPage />);
    await waitFor(() => {
      expect(screen.getByText(/Failed to load trace/i)).toBeTruthy();
    });
  });

  it("shows the error banner when the trace has an error_message", async () => {
    mockGetTrace.mockResolvedValue(
      traceFixture({
        id: "trace-1",
        name: "err",
        error_message: "kaboom",
      })
    );
    withQuery(<TraceDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("trace-error-banner")).toBeTruthy();
    });
  });

  it("selects a span when a DAG node is clicked", async () => {
    mockGetTrace.mockResolvedValue(
      traceFixture({
        id: "trace-1",
        name: "click",
        spans: [
          { span_id: "a", name: "root", status: "ok" },
          { span_id: "b", parent_id: "a", name: "child", status: "error" },
        ],
      })
    );
    withQuery(<TraceDetailPage />);
    await waitFor(() => screen.getByTestId("dag-node-b"));
    fireEvent.click(screen.getByTestId("dag-node-b"));
    await waitFor(() => {
      // Span details panel now shows the selected span's id.
      const details = screen.getByTestId("span-details");
      expect(details.textContent).toContain("child");
    });
  });
});