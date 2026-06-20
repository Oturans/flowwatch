/**
 * Sprint 4 — pure helpers in lib/trace-dag.ts.
 *
 * Covers:
 *  - layoutTraceDag: empty input, single span, tree, multi-root,
 *    deep tree, cycle, dangling parent_id, duplicate id, custom
 *    layout options. Verifies node positions, edges and warnings.
 *  - statusColor: every supported status + unknown.
 *  - formatDuration: ms / s / m+s.
 *  - computeSpanStats: counts + max depth + total duration.
 *  - topoSortSpans: stable order.
 */

import type { TraceSpan } from "@/lib/api";
import {
  layoutTraceDag,
  statusColor,
  formatDuration,
  computeSpanStats,
  topoSortSpans,
} from "@/lib/trace-dag";

const span = (overrides: Partial<TraceSpan>): TraceSpan => ({
  span_id: overrides.span_id ?? "x",
  parent_id: overrides.parent_id ?? null,
  name: overrides.name ?? "step",
  status: overrides.status ?? "ok",
  duration_ms: overrides.duration_ms ?? 100,
});

describe("layoutTraceDag", () => {
  it("returns an empty layout for empty input", () => {
    const r = layoutTraceDag([]);
    expect(r.nodes).toEqual([]);
    expect(r.edges).toEqual([]);
    expect(r.warnings).toEqual([]);
    expect(r.width).toBeGreaterThan(0);
    expect(r.height).toBeGreaterThan(0);
  });

  it("handles null / undefined input", () => {
    expect(layoutTraceDag(null).nodes).toEqual([]);
    expect(layoutTraceDag(undefined).nodes).toEqual([]);
  });

  it("places a single root span at depth 0", () => {
    const r = layoutTraceDag([span({ span_id: "only" })]);
    expect(r.nodes).toHaveLength(1);
    expect(r.nodes[0].depth).toBe(0);
    expect(r.nodes[0].x).toBeGreaterThanOrEqual(24);
    expect(r.nodes[0].y).toBeGreaterThanOrEqual(24);
    expect(r.edges).toEqual([]);
  });

  it("builds a tree with one edge per child", () => {
    const spans = [
      span({ span_id: "root" }),
      span({ span_id: "child-a", parent_id: "root" }),
      span({ span_id: "child-b", parent_id: "root" }),
      span({ span_id: "grand", parent_id: "child-a" }),
    ];
    const r = layoutTraceDag(spans);
    expect(r.nodes).toHaveLength(4);
    expect(r.edges).toEqual(
      expect.arrayContaining([
        { from: "root", to: "child-a" },
        { from: "root", to: "child-b" },
        { from: "child-a", to: "grand" },
      ])
    );
    const byId = (id: string) =>
      r.nodes.find((n) => n.span.span_id === id)!;
    expect(byId("root").depth).toBe(0);
    expect(byId("child-a").depth).toBe(1);
    expect(byId("child-b").depth).toBe(1);
    expect(byId("grand").depth).toBe(2);
  });

  it("supports multiple roots", () => {
    const spans = [
      span({ span_id: "r1" }),
      span({ span_id: "r2" }),
      span({ span_id: "c1", parent_id: "r1" }),
      span({ span_id: "c2", parent_id: "r2" }),
    ];
    const r = layoutTraceDag(spans);
    expect(r.nodes.filter((n) => n.depth === 0)).toHaveLength(2);
    expect(r.nodes.filter((n) => n.depth === 1)).toHaveLength(2);
  });

  it("warns on duplicate span_id but keeps the first", () => {
    const r = layoutTraceDag([
      span({ span_id: "dup", name: "first" }),
      span({ span_id: "dup", name: "second" }),
    ]);
    expect(r.nodes).toHaveLength(1);
    expect(r.warnings.some((w) => w.includes("duplicate"))).toBe(true);
  });

  it("recovers from cycles by placing every node at depth 0", () => {
    const r = layoutTraceDag([
      span({ span_id: "a", parent_id: "b" }),
      span({ span_id: "b", parent_id: "a" }),
    ]);
    // Both nodes are placed (the renderer still works).
    expect(r.nodes).toHaveLength(2);
    // Nodes are placed at depth 0 so the DAG renders even if the
    // edge directions are not meaningful.
    expect(r.nodes.every((n) => n.depth === 0)).toBe(true);
    // A warning is recorded so the UI can show it.
    expect(r.warnings.some((w) => w.includes("unreachable"))).toBe(true);
  });

  it("terminates on a deep linear chain", () => {
    // 50-level deep tree; mainly guards against accidental
    // recursion blow-ups if the algorithm regresses.
    const spans = Array.from({ length: 50 }, (_, i) =>
      span({ span_id: `s${i}`, parent_id: i === 0 ? null : `s${i - 1}` })
    );
    const r = layoutTraceDag(spans);
    expect(r.nodes).toHaveLength(50);
    expect(r.warnings).toEqual([]);
  });

  it("treats a dangling parent_id as a root", () => {
    const r = layoutTraceDag([
      span({ span_id: "ghost-child", parent_id: "ghost-parent" }),
    ]);
    expect(r.nodes).toHaveLength(1);
    expect(r.nodes[0].depth).toBe(0);
    expect(r.warnings.some((w) => w.includes("missing parent"))).toBe(true);
  });

  it("respects custom layout options", () => {
    const r = layoutTraceDag(
      [
        span({ span_id: "a" }),
        span({ span_id: "b", parent_id: "a" }),
      ],
      { nodeWidth: 100, rowSpacing: 10, columnSpacing: 10, paddingX: 5, paddingY: 5 }
    );
    expect(r.width).toBe(100 + 10);
    // row 0 = paddingY 5; row 1 = 5 + 64 + 10 = 79
    expect(r.height).toBe(5 + 64 + 10 + 64 + 5);
    const a = r.nodes.find((n) => n.span.span_id === "a")!;
    expect(a.width).toBe(100);
  });

  it("produces deterministic output across runs", () => {
    const spans = [
      span({ span_id: "b" }),
      span({ span_id: "a" }),
      span({ span_id: "c", parent_id: "b" }),
    ];
    const r1 = layoutTraceDag(spans);
    const r2 = layoutTraceDag(spans);
    expect(r1).toEqual(r2);
  });
});

describe("statusColor", () => {
  it("returns green for ok", () => {
    const c = statusColor("ok");
    expect(c.bg).toContain("green");
    expect(c.dot).toBe("#22c55e");
  });
  it("returns red for error", () => {
    expect(statusColor("error").bg).toContain("red");
  });
  it("returns blue for running", () => {
    expect(statusColor("running").bg).toContain("blue");
  });
  it("returns amber for timeout", () => {
    expect(statusColor("timeout").bg).toContain("amber");
  });
  it("returns gray for cancelled", () => {
    expect(statusColor("cancelled").bg).toContain("gray");
  });
  it("handles 'failed' alias for error", () => {
    expect(statusColor("failed").bg).toContain("red");
  });
  it("falls back to gray for unknown", () => {
    expect(statusColor("bogus").bg).toContain("gray");
    expect(statusColor(undefined).bg).toContain("gray");
    expect(statusColor(null).bg).toContain("gray");
  });
});

describe("formatDuration", () => {
  it("returns ms under a second", () => {
    expect(formatDuration(420)).toBe("420ms");
  });
  it("returns seconds up to a minute", () => {
    expect(formatDuration(1500)).toBe("1.50s");
    expect(formatDuration(59999)).toBe("60.00s"); // edge of formatting band
  });
  it("returns minutes + seconds past 60s", () => {
    expect(formatDuration(65_000)).toBe("1m 5s");
  });
  it("returns em-dash for null/undefined", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });
});

describe("computeSpanStats", () => {
  it("returns zeroes for empty input", () => {
    const s = computeSpanStats([]);
    expect(s.total).toBe(0);
    expect(s.maxDepth).toBe(0);
  });

  it("counts statuses and computes depth", () => {
    const spans = [
      span({ span_id: "a", status: "ok" }),
      span({ span_id: "b", parent_id: "a", status: "error" }),
      span({ span_id: "c", parent_id: "b", status: "running" }),
    ];
    const s = computeSpanStats(spans);
    expect(s.total).toBe(3);
    expect(s.ok).toBe(1);
    expect(s.error).toBe(1);
    expect(s.running).toBe(1);
    expect(s.maxDepth).toBe(2);
    expect(s.totalDurationMs).toBe(300);
  });

  it("handles null/undefined", () => {
    expect(computeSpanStats(null).total).toBe(0);
    expect(computeSpanStats(undefined).total).toBe(0);
  });
});

describe("topoSortSpans", () => {
  it("returns roots before children", () => {
    const spans = [
      span({ span_id: "c", parent_id: "b" }),
      span({ span_id: "b", parent_id: "a" }),
      span({ span_id: "a" }),
    ];
    const sorted = topoSortSpans(spans).map((s) => s.span_id);
    expect(sorted.indexOf("a")).toBeLessThan(sorted.indexOf("b"));
    expect(sorted.indexOf("b")).toBeLessThan(sorted.indexOf("c"));
  });

  it("is deterministic for ties", () => {
    const spans = [
      span({ span_id: "a" }),
      span({ span_id: "b" }),
    ];
    expect(topoSortSpans(spans)).toEqual(topoSortSpans(spans));
  });
});