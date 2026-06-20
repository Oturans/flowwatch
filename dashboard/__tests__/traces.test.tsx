/**
 * Sprint 4 — React component tests for the trace visualization
 * surface.
 *
 * Covers:
 *  - TraceDag: empty state, single span, multi-span tree, click
 *    handler, keyboard activation, custom layout seam, selection
 *    highlight, warning banner.
 *  - TraceFilterBar: render, controlled state (status, source,
 *    workflow, since, search, sort), reset button.
 *  - TraceRow: link to detail page, status pill color, error
 *    message rendering.
 *  - SpanDetailsPanel: empty + populated.
 *  - useTraceStream hook: opens EventSource, parses messages,
 *    tears down on unmount.
 */

import React, { ReactNode } from "react";
import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TraceDag, TraceFilterBar, TraceRow, SpanDetailsPanel, TraceTimeline } from "@/components/traces";
import type { Trace, TraceSpan } from "@/lib/api";
import { layoutTraceDag } from "@/lib/trace-dag";
import { useTraceStream, isTracePayload } from "@/lib/use-trace-stream";

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

// Build the mock factory as a stable, top-level const so jest.mock()
// can reference it from its hoisted scope without running into
// "Cannot access before initialization" errors.
const mockCreateTraceStream = jest.fn();
const mockGetTraces = jest.fn();
const mockGetTrace = jest.fn();

jest.mock("@/lib/api", () => ({
  __esModule: true,
  getTraces: (...args: any[]) => mockGetTraces(...args),
  getTrace: (...args: any[]) => mockGetTrace(...args),
  createTraceStream: (...args: any[]) => mockCreateTraceStream(...args),
  getSources: jest.fn(),
  getStoredToken: jest.fn(() => null),
  getStoredUser: jest.fn(() => null),
  storeAuth: jest.fn(),
  clearAuth: jest.fn(),
  fetchMe: jest.fn(),
  login: jest.fn(),
  register: jest.fn(),
  refresh: jest.fn(),
}));

// next/navigation is already mocked globally by jest.setup.js.

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const span = (overrides: Partial<TraceSpan>): TraceSpan => ({
  span_id: overrides.span_id ?? "x",
  parent_id: overrides.parent_id ?? null,
  name: overrides.name ?? "step",
  status: overrides.status ?? "ok",
  duration_ms: overrides.duration_ms ?? 100,
});

const traceFixture = (overrides: Partial<Trace> = {}): Trace => ({
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

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

function withQuery(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// TraceDag
// ---------------------------------------------------------------------------

describe("TraceDag", () => {
  it("renders an empty state for empty spans", () => {
    render(<TraceDag spans={[]} />);
    expect(screen.getByTestId("trace-dag-empty")).toBeTruthy();
  });

  it("renders an SVG with one node per span", () => {
    const spans = [
      span({ span_id: "a", name: "root" }),
      span({ span_id: "b", parent_id: "a", name: "child" }),
    ];
    render(<TraceDag spans={spans} />);
    expect(screen.getByTestId("trace-dag")).toBeTruthy();
    expect(screen.getByTestId("dag-node-a")).toBeTruthy();
    expect(screen.getByTestId("dag-node-b")).toBeTruthy();
    // Edge should be present.
    const edge = screen.getByTestId("dag-edge-a-b");
    expect(edge).toBeTruthy();
    // "d" attribute starts with M (move-to).
    expect(edge.getAttribute("d")).toMatch(/^M /);
  });

  it("calls onSelectSpan when a node is clicked", () => {
    const onSelect = jest.fn();
    const spans = [span({ span_id: "a" })];
    render(<TraceDag spans={spans} onSelectSpan={onSelect} />);
    fireEvent.click(screen.getByTestId("dag-node-a"));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ span_id: "a" })
    );
  });

  it("activates a node on Enter key", () => {
    const onSelect = jest.fn();
    const spans = [span({ span_id: "a" })];
    render(<TraceDag spans={spans} onSelectSpan={onSelect} />);
    fireEvent.keyDown(screen.getByTestId("dag-node-a"), { key: "Enter" });
    expect(onSelect).toHaveBeenCalled();
  });

  it("does not throw when onSelectSpan is not provided", () => {
    const spans = [span({ span_id: "a" })];
    render(<TraceDag spans={spans} />);
    expect(() =>
      fireEvent.click(screen.getByTestId("dag-node-a"))
    ).not.toThrow();
  });

  it("highlights the selected node", () => {
    const spans = [
      span({ span_id: "a" }),
      span({ span_id: "b", parent_id: "a" }),
    ];
    render(<TraceDag spans={spans} selectedSpanId="b" />);
    const b = screen.getByTestId("dag-node-b");
    expect(b.getAttribute("data-selected")).toBe("true");
    const a = screen.getByTestId("dag-node-a");
    expect(a.getAttribute("data-selected")).toBe("false");
  });

  it("shows a warning banner when the layout has warnings", () => {
    // Force warnings by passing an explicit layout.
    const layout = layoutTraceDag([]);
    layout.warnings.push("test warning");
    const spans = [span({ span_id: "a" })];
    render(<TraceDag spans={spans} layout={layout} />);
    expect(screen.getByTestId("trace-dag-warnings")).toBeTruthy();
  });

  it("respects a custom layout passed via prop", () => {
    const spans = [span({ span_id: "a" })];
    const layout = layoutTraceDag(spans, { nodeWidth: 333 });
    render(<TraceDag spans={spans} layout={layout} />);
    // SVG width should reflect the custom nodeWidth.
    const svg = screen.getByTestId("trace-dag").querySelector("svg");
    expect(svg).toBeTruthy();
    expect(Number(svg!.getAttribute("width"))).toBeGreaterThan(333);
  });
});

// ---------------------------------------------------------------------------
// TraceFilterBar
// ---------------------------------------------------------------------------

describe("TraceFilterBar", () => {
  const baseFilters = {
    status: "all" as const,
    source: "all" as const,
    workflowId: "",
    since: null,
    search: "",
  };
  const baseSort = { field: "started_at" as const, dir: "desc" as const };

  it("renders every control", () => {
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={() => {}}
        onSortChange={() => {}}
        sources={["n8n", "github"]}
      />
    );
    expect(screen.getByTestId("trace-filter-search")).toBeTruthy();
    expect(screen.getByTestId("trace-filter-status")).toBeTruthy();
    expect(screen.getByTestId("trace-filter-source")).toBeTruthy();
    expect(screen.getByTestId("trace-filter-workflow")).toBeTruthy();
    expect(screen.getByTestId("trace-filter-since")).toBeTruthy();
    expect(screen.getByTestId("trace-sort-field")).toBeTruthy();
    expect(screen.getByTestId("trace-sort-dir")).toBeTruthy();
  });

  it("emits onChange when the search field is typed into", () => {
    const onChange = jest.fn();
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={onChange}
        onSortChange={() => {}}
        sources={[]}
      />
    );
    fireEvent.change(screen.getByTestId("trace-filter-search"), {
      target: { value: "hello" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ search: "hello" })
    );
  });

  it("emits onChange when the status dropdown is changed", () => {
    const onChange = jest.fn();
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={onChange}
        onSortChange={() => {}}
        sources={[]}
      />
    );
    fireEvent.change(screen.getByTestId("trace-filter-status"), {
      target: { value: "ok" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ status: "ok" })
    );
  });

  it("emits onChange when the source dropdown is changed", () => {
    const onChange = jest.fn();
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={onChange}
        onSortChange={() => {}}
        sources={["a", "b"]}
      />
    );
    fireEvent.change(screen.getByTestId("trace-filter-source"), {
      target: { value: "a" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ source: "a" })
    );
  });

  it("emits onChange for workflow id and since inputs", () => {
    const onChange = jest.fn();
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={onChange}
        onSortChange={() => {}}
        sources={[]}
      />
    );
    fireEvent.change(screen.getByTestId("trace-filter-workflow"), {
      target: { value: "wf-99" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ workflowId: "wf-99" })
    );
    fireEvent.change(screen.getByTestId("trace-filter-since"), {
      target: { value: "2026-06-20T12:30" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ since: "2026-06-20T12:30" })
    );
  });

  it("emits onSortChange when sort field is changed", () => {
    const onSortChange = jest.fn();
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={() => {}}
        onSortChange={onSortChange}
        sources={[]}
      />
    );
    fireEvent.change(screen.getByTestId("trace-sort-field"), {
      target: { value: "duration_ms" },
    });
    expect(onSortChange).toHaveBeenCalledWith(
      expect.objectContaining({ field: "duration_ms" })
    );
  });

  it("emits onSortChange when sort direction is changed", () => {
    const onSortChange = jest.fn();
    render(
      <TraceFilterBar
        filters={baseFilters}
        sort={baseSort}
        onChange={() => {}}
        onSortChange={onSortChange}
        sources={[]}
      />
    );
    fireEvent.change(screen.getByTestId("trace-sort-dir"), {
      target: { value: "asc" },
    });
    expect(onSortChange).toHaveBeenCalledWith(
      expect.objectContaining({ dir: "asc" })
    );
  });

  it("reset button clears every filter", () => {
    const onChange = jest.fn();
    render(
      <TraceFilterBar
        filters={{
          status: "error",
          source: "github",
          workflowId: "wf",
          since: "2026-06-20T12:00",
          search: "q",
        }}
        sort={baseSort}
        onChange={onChange}
        onSortChange={() => {}}
        sources={[]}
      />
    );
    fireEvent.click(screen.getByTestId("trace-filter-reset"));
    expect(onChange).toHaveBeenCalledWith({
      status: "all",
      source: "all",
      workflowId: "",
      since: null,
      search: "",
    });
  });
});

// ---------------------------------------------------------------------------
// TraceRow
// ---------------------------------------------------------------------------

describe("TraceRow", () => {
  it("renders the trace name and links to the detail page", () => {
    const t = traceFixture({ id: "row-1", name: "row-name" });
    render(
      <table>
        <tbody>
          <TraceRow trace={t} orgId="org-1" />
        </tbody>
      </table>
    );
    const link = screen.getByTestId("trace-row-link-row-1");
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/traces/row-1");
    expect(link.textContent).toContain("row-name");
  });

  it("renders an error message when present", () => {
    const t = traceFixture({
      id: "row-2",
      error_message: "kaboom",
    });
    const { container } = render(
      <table>
        <tbody>
          <TraceRow trace={t} orgId="org-1" />
        </tbody>
      </table>
    );
    expect(container.textContent).toContain("kaboom");
  });

  it("uses the correct status pill color for 'error'", () => {
    const t = traceFixture({ id: "row-3", status: "error" });
    const { container } = render(
      <table>
        <tbody>
          <TraceRow trace={t} orgId="org-1" />
        </tbody>
      </table>
    );
    const row = screen.getByTestId("trace-row-row-3");
    expect(row.getAttribute("data-status")).toBe("error");
    // Tailwind class for the error pill is bg-red-100.
    expect(container.innerHTML).toContain("bg-red-100");
  });

  it("shows the span count", () => {
    const t = traceFixture({
      id: "row-4",
      spans: [span({}), span({}), span({})],
    });
    render(
      <table>
        <tbody>
          <TraceRow trace={t} orgId="org-1" />
        </tbody>
      </table>
    );
    // 3 spans; the row should contain the digit.
    expect(screen.getByTestId("trace-row-row-4").textContent).toContain("3");
  });
});

// ---------------------------------------------------------------------------
// SpanDetailsPanel
// ---------------------------------------------------------------------------

describe("SpanDetailsPanel", () => {
  it("renders an empty state when no span is provided", () => {
    render(<SpanDetailsPanel span={null} />);
    expect(screen.getByTestId("span-details-empty")).toBeTruthy();
  });

  it("renders all the span fields when a span is provided", () => {
    const s: TraceSpan = {
      span_id: "span-1",
      parent_id: "parent-1",
      name: "my.span",
      status: "error",
      duration_ms: 1234,
      started_at: "2026-06-20T12:00:00Z",
      ended_at: "2026-06-20T12:00:01Z",
      error_message: "boom",
      attributes: { model: "gpt-4", tokens: 1234 },
    };
    render(<SpanDetailsPanel span={s} />);
    const el = screen.getByTestId("span-details");
    expect(el.textContent).toContain("my.span");
    expect(el.textContent).toContain("span-1");
    expect(el.textContent).toContain("parent-1");
    expect(el.textContent).toContain("error");
    expect(el.textContent).toContain("1.23s");
    expect(el.textContent).toContain("boom");
    expect(el.textContent).toContain("gpt-4");
  });
});

// ---------------------------------------------------------------------------
// TraceTimeline
// ---------------------------------------------------------------------------

describe("TraceTimeline", () => {
  it("renders an empty state when there are no spans", () => {
    render(<TraceTimeline spans={[]} />);
    expect(screen.getByTestId("trace-timeline-empty")).toBeTruthy();
  });

  it("renders a row per span with status text", () => {
    const spans = [
      span({
        span_id: "a",
        name: "root",
        status: "ok",
        started_at: "2026-06-20T12:00:00Z",
        ended_at: "2026-06-20T12:00:01Z",
        duration_ms: 1000,
      }),
      span({
        span_id: "b",
        name: "child",
        status: "error",
        started_at: "2026-06-20T12:00:01Z",
        ended_at: "2026-06-20T12:00:03Z",
        duration_ms: 2000,
      }),
    ];
    render(<TraceTimeline spans={spans} />);
    expect(screen.getByTestId("trace-timeline")).toBeTruthy();
    expect(screen.getByTestId("timeline-row-a")).toBeTruthy();
    expect(screen.getByTestId("timeline-row-b")).toBeTruthy();
    expect(screen.getByTestId("timeline-bar-a")).toBeTruthy();
    expect(screen.getByTestId("timeline-bar-b")).toBeTruthy();
  });

  it("invokes onSelect when a bar is clicked", () => {
    const onSelect = jest.fn();
    const spans = [
      span({
        span_id: "a",
        name: "root",
        status: "ok",
        started_at: "2026-06-20T12:00:00Z",
        ended_at: "2026-06-20T12:00:01Z",
      }),
    ];
    render(<TraceTimeline spans={spans} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("timeline-bar-a"));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ span_id: "a" })
    );
  });

  it("marks the selected row", () => {
    const spans = [
      span({
        span_id: "a",
        name: "root",
        status: "ok",
        started_at: "2026-06-20T12:00:00Z",
        ended_at: "2026-06-20T12:00:01Z",
      }),
    ];
    render(<TraceTimeline spans={spans} selectedSpanId="a" />);
    const bar = screen.getByTestId("timeline-bar-a");
    expect(bar.className).toContain("ring-blue-500");
  });

  it("handles spans without explicit started_at / ended_at", () => {
    const spans = [span({ span_id: "a", name: "x", status: "ok" })];
    render(<TraceTimeline spans={spans} />);
    // Should not throw; renders a row.
    expect(screen.getByTestId("timeline-row-a")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// useTraceStream + isTracePayload
// ---------------------------------------------------------------------------

describe("isTracePayload", () => {
  it("returns true for a valid object with id + status", () => {
    expect(
      isTracePayload({ id: "x", status: "ok", name: "n" })
    ).toBe(true);
  });

  it("returns false for null / non-objects", () => {
    expect(isTracePayload(null)).toBe(false);
    expect(isTracePayload(undefined)).toBe(false);
    expect(isTracePayload("string")).toBe(false);
    expect(isTracePayload(42)).toBe(false);
  });

  it("returns false when id or status is missing", () => {
    expect(isTracePayload({ status: "ok" })).toBe(false);
    expect(isTracePayload({ id: "x" })).toBe(false);
  });

  it("returns false when id / status are not strings", () => {
    expect(isTracePayload({ id: 1, status: "ok" })).toBe(false);
    expect(isTracePayload({ id: "x", status: 1 })).toBe(false);
  });
});

describe("useTraceStream", () => {
  /** Build a fake EventSource. */
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
      // Test helper: simulate a message from the server.
      emit(payload: unknown) {
        const handler =
          this.onmessage ?? listeners["message"]?.[0];
        if (handler) handler({ data: JSON.stringify(payload) });
      },
      emitRaw(text: string) {
        const handler =
          this.onmessage ?? listeners["message"]?.[0];
        if (handler) handler({ data: text });
      },
    };
  }

  function HookProbe({ orgId, onTrace }: { orgId: string | null; onTrace: (t: Trace) => void }) {
    useTraceStream(orgId, onTrace);
    return null;
  }

  beforeEach(() => {
    mockCreateTraceStream.mockReset();
  });

  it("opens an EventSource scoped to the org", () => {
    const fake = makeFakeEventSource();
    mockCreateTraceStream.mockReturnValue(fake);
    render(<HookProbe orgId="org-42" onTrace={jest.fn()} />);
    expect(mockCreateTraceStream).toHaveBeenCalledWith("org-42");
  });

  it("does nothing when orgId is null", () => {
    const fake = makeFakeEventSource();
    mockCreateTraceStream.mockReturnValue(fake);
    render(<HookProbe orgId={null} onTrace={jest.fn()} />);
    expect(mockCreateTraceStream).not.toHaveBeenCalled();
  });

  it("parses messages and forwards valid trace payloads", () => {
    const fake = makeFakeEventSource();
    mockCreateTraceStream.mockReturnValue(fake);
    const onTrace = jest.fn();
    render(<HookProbe orgId="org-1" onTrace={onTrace} />);
    act(() => {
      fake.emit({ id: "t-1", status: "ok", name: "demo" });
    });
    expect(onTrace).toHaveBeenCalledWith(
      expect.objectContaining({ id: "t-1", status: "ok" })
    );
  });

  it("ignores invalid JSON", () => {
    const fake = makeFakeEventSource();
    mockCreateTraceStream.mockReturnValue(fake);
    const onTrace = jest.fn();
    render(<HookProbe orgId="org-1" onTrace={onTrace} />);
    act(() => {
      fake.emitRaw("{not json");
    });
    expect(onTrace).not.toHaveBeenCalled();
  });

  it("ignores payloads that don't match the trace shape", () => {
    const fake = makeFakeEventSource();
    mockCreateTraceStream.mockReturnValue(fake);
    const onTrace = jest.fn();
    render(<HookProbe orgId="org-1" onTrace={onTrace} />);
    act(() => {
      fake.emit({ foo: "bar" });
    });
    expect(onTrace).not.toHaveBeenCalled();
  });

  it("closes the EventSource on unmount", () => {
    const fake = makeFakeEventSource();
    mockCreateTraceStream.mockReturnValue(fake);
    const { unmount } = render(
      <HookProbe orgId="org-1" onTrace={jest.fn()} />
    );
    unmount();
    expect(fake.closed).toBe(true);
  });

  it("re-subscribes when orgId changes", () => {
    const fake1 = makeFakeEventSource();
    const fake2 = makeFakeEventSource();
    mockCreateTraceStream
      .mockReturnValueOnce(fake1)
      .mockReturnValueOnce(fake2);
    const onTrace = jest.fn();
    const { rerender } = render(
      <HookProbe orgId="org-1" onTrace={onTrace} />
    );
    rerender(<HookProbe orgId="org-2" onTrace={onTrace} />);
    expect(fake1.closed).toBe(true);
    expect(mockCreateTraceStream).toHaveBeenCalledTimes(2);
    expect(mockCreateTraceStream).toHaveBeenNthCalledWith(2, "org-2");
  });
});