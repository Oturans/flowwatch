"use client";

/**
 * Sprint 4 — trace timeline view.
 *
 * Renders each span as a horizontal bar positioned by its start
 * time. Useful for "what took how long" at a glance. The bars
 * are colored by status (reuse ``statusColor``) and the row
 * order is determined by ``topoSortSpans``.
 *
 * The component is purely presentational: it accepts the spans
 * and an optional ``onSelect`` handler.
 */

import { useMemo } from "react";
import type { TraceSpan } from "@/lib/api";
import {
  formatDuration,
  statusColor,
  topoSortSpans,
} from "@/lib/trace-dag";

export interface TraceTimelineProps {
  spans: TraceSpan[];
  onSelect?: (span: TraceSpan) => void;
  selectedSpanId?: string | null;
}

interface Row {
  span: TraceSpan;
  startMs: number;
  endMs: number;
}

export function TraceTimeline({
  spans,
  onSelect,
  selectedSpanId,
}: TraceTimelineProps) {
  const rows: Row[] = useMemo(() => {
    if (!spans || spans.length === 0) return [];
    // Compute a global t0 = min(started_at).
    let t0 = Infinity;
    let t1 = -Infinity;
    for (const s of spans) {
      const start = s.started_at ? new Date(s.started_at).getTime() : NaN;
      const end =
        s.ended_at != null
          ? new Date(s.ended_at).getTime()
          : typeof s.duration_ms === "number"
          ? (Number.isFinite(start) ? start : 0) + s.duration_ms
          : NaN;
      const sStart = Number.isFinite(start) ? start : 0;
      const sEnd = Number.isFinite(end) ? end : sStart;
      if (sStart < t0) t0 = sStart;
      if (sEnd > t1) t1 = sEnd;
    }
    if (!Number.isFinite(t0)) t0 = 0;
    if (!Number.isFinite(t1)) t1 = t0;
    if (t1 <= t0) t1 = t0 + 1; // avoid 0-width scale
    void t0; // used implicitly via offset below
    return topoSortSpans(spans).map((s) => {
      const start = s.started_at ? new Date(s.started_at).getTime() : t0;
      const end =
        s.ended_at != null
          ? new Date(s.ended_at).getTime()
          : typeof s.duration_ms === "number"
          ? start + s.duration_ms
          : start;
      return { span: s, startMs: start, endMs: end };
    });
  }, [spans]);

  if (!spans || spans.length === 0) {
    return (
      <div
        className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-500"
        data-testid="trace-timeline-empty"
      >
        No spans to render.
      </div>
    );
  }

  // Compute the global scale across rows.
  let minStart = Infinity;
  let maxEnd = -Infinity;
  for (const r of rows) {
    if (r.startMs < minStart) minStart = r.startMs;
    if (r.endMs > maxEnd) maxEnd = r.endMs;
  }
  if (maxEnd <= minStart) maxEnd = minStart + 1;
  const total = maxEnd - minStart;

  return (
    <div
      className="rounded-lg border border-gray-200 bg-white overflow-hidden"
      data-testid="trace-timeline"
    >
      <div className="px-4 py-2 border-b border-gray-200 bg-gray-50 text-xs text-gray-600">
        Timeline · {rows.length} spans · total{" "}
        {formatDuration(Math.round(total))}
      </div>
      <ul className="divide-y divide-gray-100">
        {rows.map((row) => {
          const left = ((row.startMs - minStart) / total) * 100;
          const width =
            Math.max(1, ((row.endMs - row.startMs) / total) * 100) || 0.5;
          const color = statusColor(row.span.status);
          const selected = row.span.span_id === selectedSpanId;
          return (
            <li
              key={row.span.span_id}
              className="flex items-center gap-3 px-4 py-2 hover:bg-gray-50"
              data-testid={`timeline-row-${row.span.span_id}`}
            >
              <div className="w-44 truncate text-xs text-gray-700 font-medium">
                {row.span.name}
              </div>
              <div className="flex-1 relative h-5 bg-gray-100 rounded">
                <button
                  type="button"
                  onClick={() => onSelect?.(row.span)}
                  className={`absolute h-5 rounded ${color.bg} ${color.border} border ${
                    selected ? "ring-2 ring-blue-500" : ""
                  }`}
                  style={{
                    left: `${left}%`,
                    width: `${width}%`,
                  }}
                  title={`${row.span.name} (${row.span.status ?? "—"}) — ${formatDuration(
                    row.span.duration_ms
                  )}`}
                  data-testid={`timeline-bar-${row.span.span_id}`}
                >
                  <span
                    className="absolute inset-0 flex items-center pl-2 text-[10px] truncate"
                    style={{ color: color.text }}
                  >
                    {row.span.status}
                  </span>
                </button>
              </div>
              <div className="w-20 text-right text-xs text-gray-500">
                {formatDuration(row.span.duration_ms)}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default TraceTimeline;