"use client";

/**
 * Sprint 4 — Traces page.
 *
 * Composes:
 *  - React Query: initial fetch via getTraces(orgId, { limit })
 *  - SSE: subscribe to /api/orgs/{orgId}/traces/stream; when a new
 *    trace arrives, prepend it to the local buffer and invalidate
 *    the query so the underlying data is fresh on next navigation.
 *  - Filter / sort controls (TraceFilterBar)
 *  - Status chip strip (counts)
 *  - The table itself with TraceRow
 *
 * The page is deliberately a single file to keep the data flow
 * obvious. Sub-components are split out into their own files so
 * each can be unit-tested in isolation.
 */

import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useOrgId } from "@/components/auth/AuthContext";
import { getTraces, type Trace } from "@/lib/api";
import { useTraceStream } from "@/lib/use-trace-stream";
import { TraceDag, TraceFilterBar, TraceRow } from "@/components/traces";
import {
  EMPTY_FILTERS,
  applyTraceView,
  countByStatus,
  filtersEqual,
  type TraceFilters,
  type TraceSort,
  uniqueSources,
} from "@/lib/trace-filters";
import { formatDistanceToNow } from "@/lib/utils";

export default function TracesPage() {
  const orgId = useOrgId();
  const queryClient = useQueryClient();

  const [filters, setFilters] = useState<TraceFilters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<TraceSort>({
    field: "started_at",
    dir: "desc",
  });
  const [realtime, setRealtime] = useState<Trace[]>([]);
  const [showDag, setShowDag] = useState(false);

  const query = useQuery({
    queryKey: ["traces", orgId],
    queryFn: () => getTraces(orgId as string, { limit: 200 }),
    enabled: !!orgId,
  });

  const onTrace = useCallback(
    (trace: Trace) => {
      setRealtime((prev) => {
        // De-dup by trace.id — the server could echo a trace
        // we already received via the REST fetch.
        const exists = prev.some((t) => t.id === trace.id);
        if (exists) return prev;
        const next = [trace, ...prev];
        // Keep the buffer bounded — 200 entries is plenty.
        return next.slice(0, 200);
      });
      // Also invalidate the React Query cache so a refresh
      // shows the server-of-record data.
      queryClient.invalidateQueries({ queryKey: ["traces", orgId] });
    },
    [queryClient, orgId]
  );

  useTraceStream(orgId, onTrace, { enabled: !!orgId });

  const traces = useMemo<Trace[]>(() => {
    const fromQuery = query.data ?? [];
    // Merge: realtime buffer takes precedence (fresher).
    const byId = new Map<string, Trace>();
    for (const t of fromQuery) byId.set(t.id, t);
    for (const t of realtime) byId.set(t.id, t);
    return Array.from(byId.values());
  }, [query.data, realtime]);

  const sources = useMemo(() => uniqueSources(traces), [traces]);
  const counts = useMemo(() => countByStatus(traces), [traces]);
  const visible = useMemo(
    () => applyTraceView(traces, filters, sort),
    [traces, filters, sort]
  );

  if (!orgId) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="text-gray-500 text-sm">Loading workspace…</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Traces</h1>
          <p className="text-gray-600 mt-1">
            Real-time execution traces for your AI workflows
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowDag((s) => !s)}
          className="px-4 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
          data-testid="toggle-dag"
        >
          {showDag ? "Hide" : "Show"} DAG preview
        </button>
      </header>

      {/* Status chips */}
      <div
        className="flex flex-wrap gap-2"
        data-testid="trace-status-chips"
      >
        {(
          [
            { key: "all", label: "All", count: counts.all },
            { key: "ok", label: "Success", count: counts.ok },
            { key: "error", label: "Failure", count: counts.error },
            { key: "running", label: "Running", count: counts.running },
            { key: "timeout", label: "Timeout", count: counts.timeout },
            { key: "cancelled", label: "Cancelled", count: counts.cancelled },
          ] as const
        ).map((c) => {
          const active =
            (filters.status ?? "all") === c.key ||
            (c.key === "all" && (filters.status ?? "all") === "all");
          return (
            <button
              key={c.key}
              type="button"
              onClick={() =>
                setFilters((f) => ({
                  ...f,
                  status: c.key === "all" ? "all" : (c.key as TraceFilters["status"]),
                }))
              }
              className={`px-3 py-1.5 rounded-full text-xs font-medium border ${
                active
                  ? "bg-blue-50 border-blue-300 text-blue-700"
                  : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50"
              }`}
              data-testid={`status-chip-${c.key}`}
            >
              {c.label} · {c.count}
            </button>
          );
        })}
      </div>

      <TraceFilterBar
        filters={filters}
        sort={sort}
        onChange={(f) => {
          if (!filtersEqual(f, filters)) setFilters(f);
        }}
        onSortChange={setSort}
        sources={sources}
      />

      {showDag && visible.length > 0 && (
        <section
          className="bg-white border border-gray-200 rounded-lg p-4"
          data-testid="trace-dag-section"
        >
          <h2 className="text-sm font-semibold text-gray-700 mb-2">
            DAG preview — {visible[0].name}
          </h2>
          <TraceDag
            spans={visible[0].spans ?? []}
          />
        </section>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {query.isLoading ? (
          <div className="p-12 text-center text-gray-500">Loading traces…</div>
        ) : query.error ? (
          <div className="p-6 bg-red-50 border border-red-200 text-red-700 text-sm rounded-none">
            Failed to load traces: {String(query.error)}
          </div>
        ) : visible.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            {traces.length === 0
              ? "No traces recorded yet. Push a trace via the WebSocket to see it here."
              : "No traces match your filters."}
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Workflow
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Source
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Duration
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Spans
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Started
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200" data-testid="trace-tbody">
              {visible.map((t) => (
                <TraceRow key={t.id} trace={t} orgId={orgId} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <footer className="text-xs text-gray-500" data-testid="trace-footer">
        Showing {visible.length} of {traces.length} traces · updated{" "}
        {formatDistanceToNow(new Date().toISOString())}
      </footer>
    </div>
  );
}