"use client";

/**
 * Sprint 4 — span detail panel.
 *
 * Shows the metadata + attributes + error_message for a single
 * span. Used both inside the trace detail page (right column)
 * and as a popover when the user clicks a DAG node.
 */

import type { TraceSpan } from "@/lib/api";
import { formatDuration, statusColor } from "@/lib/trace-dag";

export interface SpanDetailsPanelProps {
  span: TraceSpan | null;
  /** Optional: a title override (e.g. "Trace summary"). */
  title?: string;
  className?: string;
}

export function SpanDetailsPanel({
  span,
  title,
  className,
}: SpanDetailsPanelProps) {
  const classes =
    "rounded-lg border border-gray-200 bg-white p-4 " + (className ?? "");

  if (!span) {
    return (
      <div className={classes} data-testid="span-details-empty">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">
          {title ?? "Span details"}
        </h3>
        <p className="text-xs text-gray-500">
          Select a span in the DAG or timeline to see its metadata here.
        </p>
      </div>
    );
  }

  const color = statusColor(span.status);
  return (
    <div className={classes} data-testid="span-details">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        {title ?? "Span details"}
      </h3>
      <div className="space-y-2">
        <div>
          <div className="text-xs text-gray-500">Name</div>
          <div className="text-sm font-medium text-gray-900 break-words">
            {span.name}
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Status</div>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${color.bg} ${color.text}`}
          >
            {span.status ?? "—"}
          </span>
        </div>
        <div>
          <div className="text-xs text-gray-500">Span ID</div>
          <div className="text-xs font-mono text-gray-700 break-all">
            {span.span_id}
          </div>
        </div>
        {span.parent_id && (
          <div>
            <div className="text-xs text-gray-500">Parent ID</div>
            <div className="text-xs font-mono text-gray-700 break-all">
              {span.parent_id}
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-xs text-gray-500">Started</div>
            <div className="text-xs text-gray-700">
              {span.started_at
                ? new Date(span.started_at).toLocaleString()
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Ended</div>
            <div className="text-xs text-gray-700">
              {span.ended_at
                ? new Date(span.ended_at).toLocaleString()
                : "—"}
            </div>
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Duration</div>
          <div className="text-xs text-gray-700">
            {formatDuration(span.duration_ms)}
          </div>
        </div>
        {span.error_message && (
          <div>
            <div className="text-xs text-gray-500">Error</div>
            <pre className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2 whitespace-pre-wrap break-words">
              {span.error_message}
            </pre>
          </div>
        )}
        {span.attributes && Object.keys(span.attributes).length > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">Attributes</div>
            <pre className="text-xs text-gray-800 bg-gray-50 border border-gray-200 rounded p-2 whitespace-pre-wrap break-words">
              {JSON.stringify(span.attributes, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default SpanDetailsPanel;