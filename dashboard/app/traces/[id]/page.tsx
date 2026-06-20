"use client";

/**
 * Sprint 4 — trace detail page.
 *
 * Renders:
 *  - Trace header (name, status, duration, span count)
 *  - DAG visualization (clickable to drill into a span)
 *  - Timeline view (bars on a time axis)
 *  - Span details panel (right column, populated by selection)
 *  - Trace attributes + error_message (below)
 *
 * The data fetch goes through React Query so navigation back to
 * the list reuses the cached entry.
 */

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useOrgId } from "@/components/auth/AuthContext";
import { getTrace, type Trace, type TraceSpan } from "@/lib/api";
import {
  TraceDag,
  TraceTimeline,
  SpanDetailsPanel,
} from "@/components/traces";
import { formatDistanceToNow } from "@/lib/utils";
import {
  computeSpanStats,
  formatDuration,
} from "@/lib/trace-dag";

export default function TraceDetailPage() {
  const params = useParams<{ id: string }>();
  const orgId = useOrgId();
  const traceId = params?.id ?? "";
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["trace", orgId, traceId],
    queryFn: () => getTrace(orgId as string, traceId),
    enabled: !!orgId && !!traceId,
  });

  if (!orgId) {
    return (
      <div className="p-6 max-w-7xl mx-auto text-sm text-gray-500">
        Loading workspace…
      </div>
    );
  }

  if (query.isLoading) {
    return (
      <div className="p-6 max-w-7xl mx-auto text-sm text-gray-500">
        Loading trace…
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 text-sm">
          Failed to load trace: {String(query.error ?? "not found")}
        </div>
        <Link
          href="/traces"
          className="inline-block mt-4 text-sm text-blue-600 hover:underline"
        >
          ← Back to traces
        </Link>
      </div>
    );
  }

  const trace: Trace = query.data;
  const spans = trace.spans ?? [];
  const stats = computeSpanStats(spans);
  const selectedSpan: TraceSpan | null =
    spans.find((s) => s.span_id === selectedSpanId) ?? null;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <Link
            href="/traces"
            className="text-sm text-blue-600 hover:underline"
          >
            ← All traces
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">
            {trace.name}
          </h1>
          <div className="text-sm text-gray-500 font-mono mt-1">
            {trace.trace_id}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            started {formatDistanceToNow(trace.started_at)} ·{" "}
            {trace.source ?? "no source"}
            {trace.workflow_id && (
              <>
                {" "}
                · workflow{" "}
                <span className="font-mono">{trace.workflow_id}</span>
              </>
            )}
          </div>
        </div>
        <div className="text-right">
          <div
            className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium border"
            data-testid="trace-status-pill"
            data-status={trace.status}
          >
            {trace.status}
          </div>
          <div className="mt-2 text-sm text-gray-700">
            {formatDuration(trace.duration_ms)}
          </div>
        </div>
      </header>

      {/* Stats strip */}
      <section
        className="grid grid-cols-2 md:grid-cols-6 gap-3"
        data-testid="trace-stats-strip"
      >
        <Stat label="Spans" value={stats.total} />
        <Stat label="OK" value={stats.ok} />
        <Stat label="Errors" value={stats.error} />
        <Stat label="Running" value={stats.running} />
        <Stat label="Max depth" value={stats.maxDepth} />
        <Stat label="Σ duration" value={formatDuration(stats.totalDurationMs)} />
      </section>

      {trace.error_message && (
        <div
          className="bg-red-50 border border-red-200 text-red-800 rounded-lg p-3 text-sm"
          data-testid="trace-error-banner"
        >
          <strong>Trace error:</strong> {trace.error_message}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <section data-testid="trace-dag-section">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">DAG</h2>
            <TraceDag
              spans={spans}
              selectedSpanId={selectedSpanId}
              onSelectSpan={(s) => setSelectedSpanId(s.span_id)}
            />
          </section>
          <section data-testid="trace-timeline-section">
            <h2 className="text-sm font-semibold text-gray-700 mb-2">
              Timeline
            </h2>
            <TraceTimeline
              spans={spans}
              selectedSpanId={selectedSpanId}
              onSelect={(s) => setSelectedSpanId(s.span_id)}
            />
          </section>
          {trace.attributes && Object.keys(trace.attributes).length > 0 && (
            <section data-testid="trace-attributes-section">
              <h2 className="text-sm font-semibold text-gray-700 mb-2">
                Attributes
              </h2>
              <pre className="text-xs text-gray-800 bg-gray-50 border border-gray-200 rounded p-3 whitespace-pre-wrap break-words">
                {JSON.stringify(trace.attributes, null, 2)}
              </pre>
            </section>
          )}
        </div>

        <aside className="space-y-4">
          <SpanDetailsPanel span={selectedSpan} />
          <div
            className="rounded-lg border border-gray-200 bg-white p-4"
            data-testid="trace-summary-card"
          >
            <h3 className="text-sm font-semibold text-gray-700 mb-2">
              Trace summary
            </h3>
            <dl className="space-y-1 text-xs">
              <div className="flex justify-between">
                <dt className="text-gray-500">ID</dt>
                <dd className="font-mono text-gray-800">{trace.id}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Created</dt>
                <dd className="text-gray-800">
                  {new Date(trace.created_at).toLocaleString()}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Ended</dt>
                <dd className="text-gray-800">
                  {trace.ended_at
                    ? new Date(trace.ended_at).toLocaleString()
                    : "—"}
                </dd>
              </div>
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-center">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-lg font-semibold text-gray-900">{value}</div>
    </div>
  );
}