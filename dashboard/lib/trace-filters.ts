/**
 * Sprint 4 — pure helpers for the traces list page.
 *
 * Filtering, sorting and bucketing logic for traces. The React
 * page just wires up the form state to these functions so the
 * rules can be unit-tested without rendering anything.
 */

import type { Trace, TraceStatus } from "@/lib/api";

export type SortField = "started_at" | "duration_ms" | "name";
export type SortDir = "asc" | "desc";

export interface TraceFilters {
  status?: TraceStatus | "all";
  source?: string | "all";
  workflowId?: string | "";
  /** Lower bound on started_at (ISO string). */
  since?: string | null;
  /** Free-text search across workflow_id / name / trace_id. */
  search?: string;
}

export interface TraceSort {
  field: SortField;
  dir: SortDir;
}

/** Default filter shape used by the page when nothing is set. */
export const EMPTY_FILTERS: TraceFilters = {
  status: "all",
  source: "all",
  workflowId: "",
  since: null,
  search: "",
};

/**
 * Return the subset of traces matching the filters.
 *
 * Status / source / workflowId / since: exact match (or "all" to
 * skip). Search: case-insensitive substring against ``name``,
 * ``workflow_id``, ``trace_id`` and ``source``.
 */
export function filterTraces(
  traces: Trace[],
  filters: TraceFilters
): Trace[] {
  const search = (filters.search ?? "").trim().toLowerCase();
  const status = filters.status && filters.status !== "all" ? filters.status : null;
  const source = filters.source && filters.source !== "all" ? filters.source : null;
  const workflow = (filters.workflowId ?? "").trim();
  const since = filters.since ? new Date(filters.since).getTime() : null;

  return traces.filter((t) => {
    if (status && t.status !== status) return false;
    if (source && t.source !== source) return false;
    if (workflow && t.workflow_id !== workflow) return false;
    if (since != null) {
      const t0 = new Date(t.started_at).getTime();
      if (Number.isFinite(t0) && t0 < since) return false;
    }
    if (search) {
      const hay = [
        t.name,
        t.workflow_id ?? "",
        t.trace_id,
        t.source ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });
}

/**
 * Return a new array sorted according to ``sort``. Stable — falls
 * back to ``trace_id`` as a tie-breaker so two equal durations
 * always render in the same order.
 */
export function sortTraces(traces: Trace[], sort: TraceSort): Trace[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  const field = sort.field;
  return traces.slice().sort((a, b) => {
    let cmp = 0;
    if (field === "started_at") {
      const av = new Date(a.started_at).getTime() || 0;
      const bv = new Date(b.started_at).getTime() || 0;
      cmp = av - bv;
    } else if (field === "duration_ms") {
      const av = a.duration_ms ?? -1;
      const bv = b.duration_ms ?? -1;
      cmp = av - bv;
    } else {
      cmp = a.name.localeCompare(b.name);
    }
    if (cmp !== 0) return cmp * dir;
    return a.trace_id.localeCompare(b.trace_id);
  });
}

/**
 * Combine filter + sort. Convenience so callers don't have to
 * thread two functions through.
 */
export function applyTraceView(
  traces: Trace[],
  filters: TraceFilters,
  sort: TraceSort
): Trace[] {
  return sortTraces(filterTraces(traces, filters), sort);
}

/** Distinct status values seen in the input. Stable order, lowercase. */
export function uniqueStatuses(traces: Trace[]): string[] {
  const set = new Set<string>();
  for (const t of traces) {
    if (t.status) set.add(t.status.toLowerCase());
  }
  return Array.from(set).sort();
}

/** Distinct source values (excluding nulls). Stable order. */
export function uniqueSources(traces: Trace[]): string[] {
  const set = new Set<string>();
  for (const t of traces) {
    if (t.source) set.add(t.source);
  }
  return Array.from(set).sort();
}

/** Bucket counts for the status chips at the top of the page. */
export interface StatusCounts {
  all: number;
  ok: number;
  error: number;
  running: number;
  timeout: number;
  cancelled: number;
  other: number;
}

export function countByStatus(traces: Trace[]): StatusCounts {
  const counts: StatusCounts = {
    all: traces.length,
    ok: 0,
    error: 0,
    running: 0,
    timeout: 0,
    cancelled: 0,
    other: 0,
  };
  for (const t of traces) {
    const s = (t.status ?? "").toLowerCase();
    if (s === "ok" || s === "success") counts.ok += 1;
    else if (s === "error" || s === "failed") counts.error += 1;
    else if (s === "running") counts.running += 1;
    else if (s === "timeout") counts.timeout += 1;
    else if (s === "cancelled") counts.cancelled += 1;
    else counts.other += 1;
  }
  return counts;
}

/** Compare two filter objects for equality (used by the page to
 *  decide whether to push new state into the URL). */
export function filtersEqual(a: TraceFilters, b: TraceFilters): boolean {
  return (
    (a.status ?? "all") === (b.status ?? "all") &&
    (a.source ?? "all") === (b.source ?? "all") &&
    (a.workflowId ?? "") === (b.workflowId ?? "") &&
    (a.since ?? null) === (b.since ?? null) &&
    (a.search ?? "") === (b.search ?? "")
  );
}