/**
 * Sprint 4 — pure helpers in lib/trace-filters.ts.
 *
 * Covers filterTraces / sortTraces / applyTraceView / uniqueSources /
 * uniqueStatuses / countByStatus / filtersEqual.
 */

import type { Trace } from "@/lib/api";
import {
  filterTraces,
  sortTraces,
  applyTraceView,
  uniqueStatuses,
  uniqueSources,
  countByStatus,
  filtersEqual,
  EMPTY_FILTERS,
} from "@/lib/trace-filters";

const trace = (overrides: Partial<Trace>): Trace => ({
  id: overrides.id ?? "id-" + Math.random().toString(36).slice(2),
  org_id: "org-1",
  trace_id: overrides.trace_id ?? "trace",
  workflow_id: overrides.workflow_id ?? "wf",
  name: overrides.name ?? "name",
  source: overrides.source ?? "src",
  status: overrides.status ?? "ok",
  started_at: overrides.started_at ?? "2026-06-20T12:00:00Z",
  ended_at: overrides.ended_at ?? null,
  duration_ms:
    overrides.duration_ms === undefined
      ? 1000
      : overrides.duration_ms,
  attributes: overrides.attributes ?? null,
  error_message: overrides.error_message ?? null,
  spans: overrides.spans ?? [],
  created_at: overrides.created_at ?? "2026-06-20T12:00:00Z",
});

const sample = (): Trace[] => [
  trace({
    id: "1",
    trace_id: "trace-a",
    name: "alpha",
    source: "n8n",
    workflow_id: "wf-1",
    status: "ok",
    started_at: "2026-06-20T12:00:00Z",
    duration_ms: 1000,
  }),
  trace({
    id: "2",
    trace_id: "trace-b",
    name: "bravo",
    source: "n8n",
    workflow_id: "wf-2",
    status: "error",
    started_at: "2026-06-20T13:00:00Z",
    duration_ms: 5000,
  }),
  trace({
    id: "3",
    trace_id: "trace-c",
    name: "charlie",
    source: "github",
    workflow_id: "wf-1",
    status: "running",
    started_at: "2026-06-20T14:00:00Z",
    duration_ms: 500,
  }),
  trace({
    id: "4",
    trace_id: "trace-d",
    name: "delta",
    source: "github",
    workflow_id: "wf-3",
    status: "ok",
    started_at: "2026-06-20T15:00:00Z",
    duration_ms: 2000,
  }),
];

describe("filterTraces", () => {
  it("returns everything when filters are 'all' / empty", () => {
    const result = filterTraces(sample(), EMPTY_FILTERS);
    expect(result).toHaveLength(4);
  });

  it("filters by status", () => {
    const result = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      status: "ok",
    });
    expect(result.map((t) => t.id).sort()).toEqual(["1", "4"]);
  });

  it("'all' status skips the status filter", () => {
    const result = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      status: "all",
    });
    expect(result).toHaveLength(4);
  });

  it("filters by source", () => {
    const result = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      source: "github",
    });
    expect(result.map((t) => t.id).sort()).toEqual(["3", "4"]);
  });

  it("filters by workflow_id (exact match)", () => {
    const result = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      workflowId: "wf-1",
    });
    expect(result.map((t) => t.id).sort()).toEqual(["1", "3"]);
  });

  it("filters by since (lower bound on started_at)", () => {
    const result = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      since: "2026-06-20T13:30:00Z",
    });
    expect(result.map((t) => t.id).sort()).toEqual(["3", "4"]);
  });

  it("search is case-insensitive across multiple fields", () => {
    const byName = filterTraces(sample(), { ...EMPTY_FILTERS, search: "BRAVO" });
    expect(byName.map((t) => t.id)).toEqual(["2"]);

    const byWorkflow = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      search: "wf-2",
    });
    expect(byWorkflow.map((t) => t.id)).toEqual(["2"]);

    const byTraceId = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      search: "trace-c",
    });
    expect(byTraceId.map((t) => t.id)).toEqual(["3"]);

    const bySource = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      search: "github",
    });
    expect(bySource.map((t) => t.id).sort()).toEqual(["3", "4"]);
  });

  it("combines multiple filters (AND)", () => {
    const result = filterTraces(sample(), {
      ...EMPTY_FILTERS,
      source: "github",
      status: "ok",
    });
    expect(result.map((t) => t.id)).toEqual(["4"]);
  });
});

describe("sortTraces", () => {
  it("sorts by started_at desc (default)", () => {
    const result = sortTraces(sample(), { field: "started_at", dir: "desc" });
    expect(result.map((t) => t.id)).toEqual(["4", "3", "2", "1"]);
  });

  it("sorts by started_at asc", () => {
    const result = sortTraces(sample(), { field: "started_at", dir: "asc" });
    expect(result.map((t) => t.id)).toEqual(["1", "2", "3", "4"]);
  });

  it("sorts by duration_ms", () => {
    const result = sortTraces(sample(), { field: "duration_ms", dir: "asc" });
    expect(result.map((t) => t.id)).toEqual(["3", "1", "4", "2"]);
  });

  it("sorts by name", () => {
    const result = sortTraces(sample(), { field: "name", dir: "asc" });
    expect(result.map((t) => t.name)).toEqual(["alpha", "bravo", "charlie", "delta"]);
  });

  it("uses trace_id as a tie-breaker", () => {
    const ts = [
      trace({ id: "a", trace_id: "zzz", duration_ms: 100, name: "x" }),
      trace({ id: "b", trace_id: "aaa", duration_ms: 100, name: "x" }),
    ];
    const result = sortTraces(ts, { field: "duration_ms", dir: "asc" });
    expect(result.map((t) => t.id)).toEqual(["b", "a"]);
  });

  it("handles null duration_ms (treated as -1)", () => {
    const ts = [
      trace({ id: "a", duration_ms: null }),
      trace({ id: "b", duration_ms: 0 }),
    ];
    const result = sortTraces(ts, { field: "duration_ms", dir: "asc" });
    expect(result.map((t) => t.id)).toEqual(["a", "b"]);
  });

  it("does not mutate the input array", () => {
    const input = sample();
    const copy = input.slice();
    sortTraces(input, { field: "started_at", dir: "asc" });
    expect(input).toEqual(copy);
  });
});

describe("applyTraceView", () => {
  it("combines filter + sort", () => {
    const result = applyTraceView(
      sample(),
      { ...EMPTY_FILTERS, source: "github" },
      { field: "duration_ms", dir: "desc" }
    );
    expect(result.map((t) => t.id)).toEqual(["4", "3"]);
  });
});

describe("uniqueStatuses / uniqueSources", () => {
  it("returns distinct sorted statuses (lowercased)", () => {
    expect(uniqueStatuses(sample())).toEqual(["error", "ok", "running"]);
  });

  it("returns distinct sorted sources", () => {
    expect(uniqueSources(sample())).toEqual(["github", "n8n"]);
  });

  it("handles empty arrays", () => {
    expect(uniqueStatuses([])).toEqual([]);
    expect(uniqueSources([])).toEqual([]);
  });
});

describe("countByStatus", () => {
  it("counts every status bucket", () => {
    const c = countByStatus(sample());
    expect(c.all).toBe(4);
    expect(c.ok).toBe(2);
    expect(c.error).toBe(1);
    expect(c.running).toBe(1);
    expect(c.timeout).toBe(0);
    expect(c.cancelled).toBe(0);
    expect(c.other).toBe(0);
  });

  it("'failed' maps to error", () => {
    const c = countByStatus([trace({ id: "x", status: "failed" })]);
    expect(c.error).toBe(1);
    expect(c.other).toBe(0);
  });

  it("'success' maps to ok", () => {
    const c = countByStatus([trace({ id: "x", status: "success" })]);
    expect(c.ok).toBe(1);
  });

  it("unknown status goes to 'other'", () => {
    const c = countByStatus([trace({ id: "x", status: "weird" })]);
    expect(c.other).toBe(1);
  });
});

describe("filtersEqual", () => {
  it("returns true for identical filters", () => {
    expect(filtersEqual(EMPTY_FILTERS, EMPTY_FILTERS)).toBe(true);
  });
  it("returns false when any field differs", () => {
    expect(
      filtersEqual(EMPTY_FILTERS, { ...EMPTY_FILTERS, status: "ok" })
    ).toBe(false);
    expect(
      filtersEqual(EMPTY_FILTERS, { ...EMPTY_FILTERS, search: "x" })
    ).toBe(false);
  });
});