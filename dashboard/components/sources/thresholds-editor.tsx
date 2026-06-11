"use client";

/**
 * ThresholdsEditor
 *
 * Per-source configurable anomaly thresholds. Renders three sliders
 * (latency_ms, error_rate_pct, failure_count) with sensible min/max
 * defaults. The user can save the whole set with one button; the
 * API treats the request as a full replacement (see
 * ThresholdsUpdate in ``app/schemas/sprint3.py``).
 *
 * Why sliders? The three values span wildly different scales
 * (milliseconds, percent, count) and the user typically thinks in
 * "I want a higher bar" rather than "I want exactly 750 ms".
 * A range input is the lightest-weight way to express that.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getSourceThresholds,
  updateSourceThresholds,
  type ThresholdItem,
  type ThresholdResponse,
} from "@/lib/api";
import { Loader2, Save } from "lucide-react";

interface MetricSpec {
  key: "latency_ms" | "error_rate_pct" | "failure_count";
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  defaultWindow: number;
  hint: string;
}

const METRICS: MetricSpec[] = [
  {
    key: "latency_ms",
    label: "Latency (p95)",
    unit: "ms",
    min: 50,
    max: 10000,
    step: 50,
    defaultValue: 500,
    defaultWindow: 300,
    hint: "Fire when p95 latency in the window exceeds this value (ms).",
  },
  {
    key: "error_rate_pct",
    label: "Error rate",
    unit: "%",
    min: 0.1,
    max: 50,
    step: 0.1,
    defaultValue: 5,
    defaultWindow: 300,
    hint: "Fire when the error rate in the window exceeds this percent (0-50).",
  },
  {
    key: "failure_count",
    label: "Failure count",
    unit: "failures",
    min: 1,
    max: 200,
    step: 1,
    defaultValue: 10,
    defaultWindow: 600,
    hint: "Fire when this many failures occur in the window.",
  },
];

function defaultItems(): ThresholdItem[] {
  return METRICS.map((m) => ({
    metric: m.key,
    value: m.defaultValue,
    window_seconds: m.defaultWindow,
    enabled: true,
  }));
}

function fromResponses(responses: ThresholdResponse[]): ThresholdItem[] {
  // The backend may return a partial set (e.g. only latency_ms).
  // Fill in the rest with defaults so the sliders are visible.
  const byKey = new Map(responses.map((r) => [r.metric, r]));
  return METRICS.map<ThresholdItem>((m) => {
    const existing = byKey.get(m.key);
    if (existing) {
      return {
        metric: m.key,
        value: existing.value,
        window_seconds: existing.window_seconds,
        enabled: existing.enabled,
      };
    }
    return {
      metric: m.key,
      value: m.defaultValue,
      window_seconds: m.defaultWindow,
      enabled: true,
    };
  });
}

export function ThresholdsEditor({ sourceId }: { sourceId: string }) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<ThresholdItem[]>(() => defaultItems());

  const query = useQuery({
    queryKey: ["thresholds", sourceId],
    queryFn: () => getSourceThresholds(sourceId),
  });

  useEffect(() => {
    if (query.data) {
      setItems(fromResponses(query.data.thresholds));
    }
  }, [query.data]);

  const mutation = useMutation({
    mutationFn: () => updateSourceThresholds(sourceId, items),
    onSuccess: (data) => {
      queryClient.setQueryData(["thresholds", sourceId], data);
      queryClient.invalidateQueries({ queryKey: ["thresholds", sourceId] });
    },
  });

  const hasChanges = useMemo(() => {
    if (!query.data) return true; // first save
    const origByKey = new Map(
      query.data.thresholds.map((r) => [r.metric, r])
    );
    return items.some((item) => {
      const orig = origByKey.get(item.metric);
      if (!orig) return true;
      return (
        orig.value !== item.value ||
        orig.window_seconds !== item.window_seconds ||
        orig.enabled !== item.enabled
      );
    });
  }, [query.data, items]);

  const updateItem = (metric: ThresholdItem["metric"], patch: Partial<ThresholdItem>) => {
    setItems((prev) =>
      prev.map((i) => (i.metric === metric ? { ...i, ...patch } : i))
    );
  };

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading thresholds...
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h5 className="text-xs font-semibold text-gray-700 uppercase">
        Anomaly Thresholds
      </h5>
      {METRICS.map((m) => {
        const item = items.find((i) => i.metric === m.key) ?? {
          metric: m.key,
          value: m.defaultValue,
          window_seconds: m.defaultWindow,
          enabled: true,
        };
        return (
          <div
            key={m.key}
            className="p-2 bg-white border border-gray-200 rounded space-y-1"
          >
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="rounded"
                  checked={item.enabled}
                  onChange={(e) =>
                    updateItem(m.key, { enabled: e.target.checked })
                  }
                />
                <span className="font-medium text-gray-800">{m.label}</span>
              </label>
              <span className="text-sm font-mono text-gray-700">
                {m.key === "error_rate_pct"
                  ? `${item.value.toFixed(1)}${m.unit}`
                  : `${item.value}${m.unit}`}
              </span>
            </div>
            <input
              type="range"
              min={m.min}
              max={m.max}
              step={m.step}
              value={item.value}
              disabled={!item.enabled}
              onChange={(e) =>
                updateItem(m.key, { value: parseFloat(e.target.value) })
              }
              className="w-full disabled:opacity-40"
            />
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>{m.hint}</span>
              <label className="flex items-center gap-1">
                Window:
                <select
                  value={item.window_seconds}
                  disabled={!item.enabled}
                  onChange={(e) =>
                    updateItem(m.key, {
                      window_seconds: parseInt(e.target.value, 10),
                    })
                  }
                  className="px-1 py-0.5 border border-gray-300 rounded text-xs disabled:opacity-40"
                >
                  <option value={60}>1m</option>
                  <option value={300}>5m</option>
                  <option value={600}>10m</option>
                  <option value={900}>15m</option>
                  <option value={1800}>30m</option>
                  <option value={3600}>1h</option>
                </select>
              </label>
            </div>
          </div>
        );
      })}
      <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
        <button
          onClick={() => mutation.mutate()}
          disabled={!hasChanges || mutation.isPending}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
        >
          <Save className="w-3 h-3" />
          {mutation.isPending ? "Saving..." : "Save thresholds"}
        </button>
        {mutation.isSuccess && !mutation.isPending && (
          <span className="text-xs text-green-600">Saved</span>
        )}
        {mutation.isError && (
          <span className="text-xs text-red-600">Save failed</span>
        )}
      </div>
    </div>
  );
}
