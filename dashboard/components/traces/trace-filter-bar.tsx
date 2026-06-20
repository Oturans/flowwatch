"use client";

/**
 * Sprint 4 — filter / sort controls for the traces list.
 *
 * A controlled component: the parent owns the filter + sort state
 * and we just emit change events. This keeps the form usable from
 * a single source of truth (URL or React state) and the rendering
 * logic easy to snapshot-test.
 */

import type { ChangeEvent } from "react";
import {
  type TraceFilters,
  type TraceSort,
  type SortField,
  type SortDir,
} from "@/lib/trace-filters";

export interface TraceFilterBarProps {
  filters: TraceFilters;
  sort: TraceSort;
  onChange: (filters: TraceFilters) => void;
  onSortChange: (sort: TraceSort) => void;
  sources: string[];
}

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "ok", label: "Success" },
  { value: "error", label: "Failure" },
  { value: "running", label: "Running" },
  { value: "timeout", label: "Timeout" },
  { value: "cancelled", label: "Cancelled" },
];

export function TraceFilterBar({
  filters,
  sort,
  onChange,
  onSortChange,
  sources,
}: TraceFilterBarProps) {
  const patch = (delta: Partial<TraceFilters>) =>
    onChange({ ...filters, ...delta });

  const onStatus = (e: ChangeEvent<HTMLSelectElement>) =>
    patch({ status: e.target.value as TraceFilters["status"] });
  const onSource = (e: ChangeEvent<HTMLSelectElement>) =>
    patch({ source: e.target.value });
  const onWorkflow = (e: ChangeEvent<HTMLInputElement>) =>
    patch({ workflowId: e.target.value });
  const onSince = (e: ChangeEvent<HTMLInputElement>) =>
    patch({ since: e.target.value || null });
  const onSearch = (e: ChangeEvent<HTMLInputElement>) =>
    patch({ search: e.target.value });
  const onSortField = (e: ChangeEvent<HTMLSelectElement>) =>
    onSortChange({ ...sort, field: e.target.value as SortField });
  const onSortDir = (e: ChangeEvent<HTMLSelectElement>) =>
    onSortChange({ ...sort, dir: e.target.value as SortDir });

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-1 md:grid-cols-6 gap-3"
      data-testid="trace-filter-bar"
    >
      <div className="md:col-span-2">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Search
        </label>
        <input
          type="search"
          value={filters.search ?? ""}
          onChange={onSearch}
          placeholder="trace, name, workflow…"
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="trace-filter-search"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Status
        </label>
        <select
          value={filters.status ?? "all"}
          onChange={onStatus}
          className="w-full px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="trace-filter-status"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Source
        </label>
        <select
          value={filters.source ?? "all"}
          onChange={onSource}
          className="w-full px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="trace-filter-source"
        >
          <option value="all">All</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Workflow ID
        </label>
        <input
          type="text"
          value={filters.workflowId ?? ""}
          onChange={onWorkflow}
          placeholder="exact match"
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="trace-filter-workflow"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Since
        </label>
        <input
          type="datetime-local"
          value={filters.since ? filters.since.slice(0, 16) : ""}
          onChange={onSince}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="trace-filter-since"
        />
      </div>

      <div className="md:col-span-3 flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Sort by
          </label>
          <select
            value={sort.field}
            onChange={onSortField}
            className="w-full px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            data-testid="trace-sort-field"
          >
            <option value="started_at">Started</option>
            <option value="duration_ms">Duration</option>
            <option value="name">Name</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Direction
          </label>
          <select
            value={sort.dir}
            onChange={onSortDir}
            className="w-full px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            data-testid="trace-sort-dir"
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
        </div>
        <button
          type="button"
          onClick={() =>
            onChange({
              status: "all",
              source: "all",
              workflowId: "",
              since: null,
              search: "",
            })
          }
          className="px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
          data-testid="trace-filter-reset"
        >
          Reset
        </button>
      </div>
    </div>
  );
}

export default TraceFilterBar;