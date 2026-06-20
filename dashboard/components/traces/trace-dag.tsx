"use client";

/**
 * Sprint 4 — DAG visualization for trace spans.
 *
 * Renders the trace's execution tree as an SVG. Each node shows
 * the span name + status; edges connect parent to child. The
 * layout comes from the pure helper in ``lib/trace-dag`` so the
 * React component is mostly a dumb renderer.
 *
 * The component is interactive: clicking a node fires
 * ``onSelectSpan`` so the parent page can show details (timeline,
 * attributes, error). Keyboard navigation (Tab + Enter) is
 * supported via ``role="button"`` + ``tabIndex``.
 */

import { useMemo } from "react";
import type { TraceSpan } from "@/lib/api";
import {
  layoutTraceDag,
  statusColor,
  formatDuration,
  type DagLayout,
} from "@/lib/trace-dag";

export interface TraceDagProps {
  spans: TraceSpan[];
  /** Optional selected span id (highlighted). */
  selectedSpanId?: string | null;
  /** Called when the user clicks a node. */
  onSelectSpan?: (span: TraceSpan) => void;
  /** Optional className applied to the wrapper div. */
  className?: string;
  /** Test seam: pass a custom layout to bypass the default one. */
  layout?: DagLayout;
}

export function TraceDag({
  spans,
  selectedSpanId,
  onSelectSpan,
  className,
  layout,
}: TraceDagProps) {
  const computed: DagLayout = useMemo(
    () => layout ?? layoutTraceDag(spans),
    [spans, layout]
  );

  if (!spans || spans.length === 0) {
    return (
      <div
        className={
          "rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-sm text-gray-500 " +
          (className ?? "")
        }
        data-testid="trace-dag-empty"
      >
        No spans in this trace.
      </div>
    );
  }

  return (
    <div
      className={
        "relative overflow-auto rounded-lg border border-gray-200 bg-white " +
        (className ?? "")
      }
      data-testid="trace-dag"
      role="tree"
    >
      {computed.warnings.length > 0 && (
        <div
          className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
          data-testid="trace-dag-warnings"
        >
          {computed.warnings.length} layout warning
          {computed.warnings.length === 1 ? "" : "s"}
        </div>
      )}
      <svg
        viewBox={`0 0 ${computed.width} ${computed.height}`}
        width={computed.width}
        height={computed.height}
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label={`Trace DAG with ${computed.nodes.length} spans`}
      >
        {/* Edges */}
        <g aria-hidden="true">
          {computed.edges.map((edge) => {
            const from = computed.nodes.find((n) => n.span.span_id === edge.from);
            const to = computed.nodes.find((n) => n.span.span_id === edge.to);
            if (!from || !to) return null;
            const x1 = from.x + from.width / 2;
            const y1 = from.y + from.height;
            const x2 = to.x + to.width / 2;
            const y2 = to.y;
            // Cubic bezier with vertical handles for a clean tree look.
            const midY = (y1 + y2) / 2;
            const path = `M ${x1},${y1} C ${x1},${midY} ${x2},${midY} ${x2},${y2}`;
            return (
              <path
                key={`${edge.from}-${edge.to}`}
                d={path}
                stroke="#9ca3af"
                strokeWidth={1.5}
                fill="none"
                data-testid={`dag-edge-${edge.from}-${edge.to}`}
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {computed.nodes.map((node) => {
            const color = statusColor(node.span.status);
            const isSelected = node.span.span_id === selectedSpanId;
            return (
              <g
                key={node.span.span_id}
                transform={`translate(${node.x}, ${node.y})`}
                role="treeitem"
                aria-label={`${node.span.name} (${node.span.status ?? "unknown"})`}
                tabIndex={0}
                onClick={() => onSelectSpan?.(node.span)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectSpan?.(node.span);
                  }
                }}
                style={{ cursor: onSelectSpan ? "pointer" : "default" }}
                data-testid={`dag-node-${node.span.span_id}`}
                data-selected={isSelected ? "true" : "false"}
                data-status={node.span.status ?? "unknown"}
              >
                <rect
                  x={0}
                  y={0}
                  width={node.width}
                  height={node.height}
                  rx={8}
                  ry={8}
                  className={`${color.bg} ${color.border}`}
                  stroke={isSelected ? "#2563eb" : undefined}
                  strokeWidth={isSelected ? 3 : 1.5}
                  fill="currentColor"
                  style={{ color: "white" }}
                />
                {/* Status dot */}
                <circle
                  cx={14}
                  cy={14}
                  r={5}
                  fill={color.dot}
                  aria-hidden="true"
                />
                <foreignObject x={26} y={6} width={node.width - 32} height={20}>
                  <div
                    className={`truncate text-xs font-semibold ${color.text}`}
                    title={node.span.name}
                  >
                    {node.span.name}
                  </div>
                </foreignObject>
                <foreignObject
                  x={10}
                  y={26}
                  width={node.width - 20}
                  height={16}
                >
                  <div className="flex items-center justify-between text-[10px] text-gray-600">
                    <span className="truncate">{node.span.status ?? "—"}</span>
                    <span>{formatDuration(node.span.duration_ms)}</span>
                  </div>
                </foreignObject>
                <foreignObject
                  x={10}
                  y={42}
                  width={node.width - 20}
                  height={16}
                >
                  <div className="truncate text-[10px] text-gray-500 font-mono">
                    {node.span.span_id}
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

export default TraceDag;