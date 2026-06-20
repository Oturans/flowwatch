/**
 * DAG layout + helpers for Sprint 4 trace visualization.
 *
 * Pure functions, no React. The layout algorithm is the classic
 * "tidy tree" variant:
 *
 *   1. Compute a depth for each node (root = 0).
 *   2. Group nodes by depth.
 *   3. For each depth, assign a vertical position that minimizes
 *      crossing with the parent's subtree (a simple left-to-right
 *      DFS ordering).
 *
 * The output is a flat list of positioned nodes + edges, ready to
 * drop into an SVG. The implementation is small (no third-party
 * dagre/d3 dependency) because:
 *
 *  - Traces in FlowWatch are small (10s of spans, not 1000s).
 *  - Avoids pulling in ~200KB of layout code just for a view.
 *  - It's deterministic and easy to unit test.
 */

import type { TraceSpan } from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DagNode {
  /** The span this node represents. */
  span: TraceSpan;
  /** Depth in the tree (root = 0). */
  depth: number;
  /** Horizontal position among its siblings. */
  order: number;
  /** Layout X coordinate (pixels). */
  x: number;
  /** Layout Y coordinate (pixels). */
  y: number;
  /** Pixel width of the rendered box. */
  width: number;
  /** Pixel height of the rendered box. */
  height: number;
}

export interface DagEdge {
  /** Source span id. */
  from: string;
  /** Target span id. */
  to: string;
}

export interface DagLayout {
  nodes: DagNode[];
  edges: DagEdge[];
  /** Total SVG width needed to render everything. */
  width: number;
  /** Total SVG height needed to render everything. */
  height: number;
  /** Useful diagnostic info: cycle detection. */
  warnings: string[];
}

export interface LayoutOptions {
  /** Horizontal spacing between nodes at the same depth. */
  columnSpacing?: number;
  /** Vertical spacing between depths. */
  rowSpacing?: number;
  /** Box width. */
  nodeWidth?: number;
  /** Box height. */
  nodeHeight?: number;
  /** Horizontal padding around the whole DAG. */
  paddingX?: number;
  /** Vertical padding around the whole DAG. */
  paddingY?: number;
}

const DEFAULTS: Required<LayoutOptions> = {
  columnSpacing: 32,
  rowSpacing: 56,
  nodeWidth: 200,
  nodeHeight: 64,
  paddingX: 24,
  paddingY: 24,
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Build a DAG layout from a flat list of spans. Returns an empty
 * layout for empty input. Cycles are detected and the offending
 * edges are dropped (the renderer still draws the node).
 */
export function layoutTraceDag(
  spans: TraceSpan[] | undefined | null,
  options: LayoutOptions = {}
): DagLayout {
  const opts = { ...DEFAULTS, ...options };
  const warnings: string[] = [];

  if (!spans || spans.length === 0) {
    return {
      nodes: [],
      edges: [],
      width: opts.paddingX * 2 + opts.nodeWidth,
      height: opts.paddingY * 2 + opts.nodeHeight,
      warnings,
    };
  }

  // 1. Index + adjacency
  const byId = new Map<string, TraceSpan>();
  for (const s of spans) {
    if (byId.has(s.span_id)) {
      warnings.push(`duplicate span_id: ${s.span_id}`);
      continue;
    }
    byId.set(s.span_id, s);
  }
  const childrenOf = new Map<string | null, TraceSpan[]>();
  for (const s of byId.values()) {
    const parent = s.parent_id ?? null;
    if (parent !== null && !byId.has(parent)) {
      // Dangling parent - treat as a root so it still renders.
      warnings.push(
        `span ${s.span_id} references missing parent ${parent}; treating as root`
      );
      const arr = childrenOf.get(null) ?? [];
      arr.push(s);
      childrenOf.set(null, arr);
      continue;
    }
    const arr = childrenOf.get(parent) ?? [];
    arr.push(s);
    childrenOf.set(parent, arr);
  }

  // Roots: nodes whose parent_id is null OR unresolved.
  const roots = (childrenOf.get(null) ?? []).slice().sort((a, b) =>
    a.span_id.localeCompare(b.span_id)
  );

  // 2. Compute depth + DFS order
  const orderMap = new Map<string, { depth: number; order: number }>();
  let orderCounter = 0;

  type Frame = { node: TraceSpan; depth: number };
  const visitedInChain = new Set<string>();
  const stack: Frame[] = roots.map((r) => ({ node: r, depth: 0 }));

  while (stack.length > 0) {
    const frame = stack.pop()!;
    const id = frame.node.span_id;
    if (visitedInChain.has(id)) {
      warnings.push(`cycle detected at span ${id}; skipping subtree`);
      continue;
    }
    visitedInChain.add(id);
    orderMap.set(id, { depth: frame.depth, order: orderCounter++ });

    const kids = (childrenOf.get(id) ?? [])
      .slice()
      .sort((a, b) => a.span_id.localeCompare(b.span_id));
    for (let i = kids.length - 1; i >= 0; i--) {
      stack.push({ node: kids[i], depth: frame.depth + 1 });
    }
  }

  // Any span not visited (cycle or unreachable) gets an order slot
  // appended to depth 0 so it still renders.
  let fallbackOrder = orderCounter;
  for (const s of byId.values()) {
    if (!orderMap.has(s.span_id)) {
      warnings.push(`unreachable span: ${s.span_id}`);
      orderMap.set(s.span_id, { depth: 0, order: fallbackOrder++ });
    }
  }

  // 3. Group by depth, compute X positions per depth
  const byDepth = new Map<number, TraceSpan[]>();
  for (const s of byId.values()) {
    const d = orderMap.get(s.span_id)!.depth;
    const arr = byDepth.get(d) ?? [];
    arr.push(s);
    byDepth.set(d, arr);
  }
  const depths = Array.from(byDepth.keys()).sort((a, b) => a - b);

  const positions = new Map<string, { x: number; y: number }>();
  let maxRowWidth = 0;

  for (const depth of depths) {
    const row = byDepth.get(depth)!.slice().sort((a, b) => {
      const ao = orderMap.get(a.span_id)!.order;
      const bo = orderMap.get(b.span_id)!.order;
      return ao - bo;
    });
    const rowWidth =
      row.length * opts.nodeWidth + (row.length - 1) * opts.columnSpacing;
    if (rowWidth > maxRowWidth) maxRowWidth = rowWidth;

    for (let i = 0; i < row.length; i++) {
      const x = opts.paddingX + i * (opts.nodeWidth + opts.columnSpacing);
      const y = opts.paddingY + depth * (opts.nodeHeight + opts.rowSpacing);
      positions.set(row[i].span_id, { x, y });
    }
  }

  // 4. Build nodes + edges
  const nodes: DagNode[] = [];
  const edges: DagEdge[] = [];
  for (const s of byId.values()) {
    const meta = orderMap.get(s.span_id)!;
    const pos = positions.get(s.span_id)!;
    nodes.push({
      span: s,
      depth: meta.depth,
      order: meta.order,
      x: pos.x,
      y: pos.y,
      width: opts.nodeWidth,
      height: opts.nodeHeight,
    });
    if (s.parent_id && byId.has(s.parent_id)) {
      edges.push({ from: s.parent_id, to: s.span_id });
    }
  }

  const totalWidth =
    maxRowWidth > 0 ? maxRowWidth + opts.paddingX * 2 : opts.paddingX * 2;
  const totalHeight =
    depths.length > 0
      ? depths[depths.length - 1] * (opts.nodeHeight + opts.rowSpacing) +
        opts.nodeHeight +
        opts.paddingY * 2
      : opts.paddingY * 2;

  return {
    nodes,
    edges,
    width: totalWidth,
    height: totalHeight,
    warnings,
  };
}

// ---------------------------------------------------------------------------
// Helpers consumed by the React layer
// ---------------------------------------------------------------------------

/**
 * Map a span status string to a Tailwind color token. The DAG
 * component renders the nodes; this just centralises the palette
 * so tests can assert against a known contract.
 */
export function statusColor(status: TraceSpan["status"] | null | undefined): {
  bg: string;
  border: string;
  text: string;
  dot: string;
} {
  switch ((status ?? "").toLowerCase()) {
    case "ok":
    case "success":
      return {
        bg: "bg-green-50",
        border: "border-green-400",
        text: "text-green-900",
        dot: "#22c55e",
      };
    case "error":
    case "failed":
      return {
        bg: "bg-red-50",
        border: "border-red-400",
        text: "text-red-900",
        dot: "#ef4444",
      };
    case "running":
      return {
        bg: "bg-blue-50",
        border: "border-blue-400",
        text: "text-blue-900",
        dot: "#3b82f6",
      };
    case "timeout":
      return {
        bg: "bg-amber-50",
        border: "border-amber-400",
        text: "text-amber-900",
        dot: "#f59e0b",
      };
    case "cancelled":
      return {
        bg: "bg-gray-100",
        border: "border-gray-400",
        text: "text-gray-700",
        dot: "#9ca3af",
      };
    default:
      return {
        bg: "bg-gray-50",
        border: "border-gray-300",
        text: "text-gray-700",
        dot: "#9ca3af",
      };
  }
}

/**
 * Compute a topologically-sorted list of spans. Used by the timeline
 * view so the rows are stable across renders.
 */
export function topoSortSpans(spans: TraceSpan[]): TraceSpan[] {
  const byId = new Map<string, TraceSpan>();
  const inDegree = new Map<string, number>();
  for (const s of spans) {
    byId.set(s.span_id, s);
    inDegree.set(s.span_id, 0);
  }
  const edges: Array<[string, string]> = [];
  for (const s of spans) {
    if (s.parent_id && byId.has(s.parent_id)) {
      edges.push([s.parent_id, s.span_id]);
      inDegree.set(s.span_id, (inDegree.get(s.span_id) ?? 0) + 1);
    }
  }
  const queue: string[] = [];
  for (const [id, deg] of inDegree.entries()) {
    if (deg === 0) queue.push(id);
  }
  queue.sort();
  const out: TraceSpan[] = [];
  while (queue.length > 0) {
    const id = queue.shift()!;
    out.push(byId.get(id)!);
    for (const [from, to] of edges) {
      if (from !== id) continue;
      const nd = (inDegree.get(to) ?? 0) - 1;
      inDegree.set(to, nd);
      if (nd === 0) {
        let i = 0;
        while (i < queue.length && queue[i] < to) i++;
        queue.splice(i, 0, to);
      }
    }
  }
  for (const s of spans) {
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

/** Format a duration_ms value as "1.2s" / "420ms" etc. */
export function formatDuration(durationMs: number | null | undefined): string {
  if (durationMs == null) return "—";
  if (durationMs < 1000) return `${durationMs}ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(2)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.floor((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/** Aggregate stats over a list of spans. Useful for the detail header. */
export interface SpanStats {
  total: number;
  ok: number;
  error: number;
  running: number;
  cancelled: number;
  timeout: number;
  totalDurationMs: number;
  maxDepth: number;
}

export function computeSpanStats(
  spans: TraceSpan[] | undefined | null
): SpanStats {
  const stats: SpanStats = {
    total: 0,
    ok: 0,
    error: 0,
    running: 0,
    cancelled: 0,
    timeout: 0,
    totalDurationMs: 0,
    maxDepth: 0,
  };
  if (!spans) return stats;
  const byId = new Map<string, TraceSpan>();
  for (const s of spans) byId.set(s.span_id, s);
  const depth = new Map<string, number>();
  const visit = (id: string): number => {
    if (depth.has(id)) return depth.get(id)!;
    const s = byId.get(id);
    if (!s) return 0;
    const d =
      s.parent_id && byId.has(s.parent_id) ? visit(s.parent_id) + 1 : 0;
    depth.set(id, d);
    return d;
  };

  for (const s of spans) {
    stats.total += 1;
    const status = (s.status ?? "").toLowerCase();
    if (status === "ok" || status === "success") stats.ok += 1;
    else if (status === "error" || status === "failed") stats.error += 1;
    else if (status === "running") stats.running += 1;
    else if (status === "cancelled") stats.cancelled += 1;
    else if (status === "timeout") stats.timeout += 1;
    if (typeof s.duration_ms === "number") {
      stats.totalDurationMs += s.duration_ms;
    }
    const d = visit(s.span_id);
    if (d > stats.maxDepth) stats.maxDepth = d;
  }
  return stats;
}