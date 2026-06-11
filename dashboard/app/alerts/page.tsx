"use client";

/**
 * Sprint 3 alert history view.
 *
 * Replaces the older alerts page with a richer table that:
 * - filters by source / status / severity / time range
 * - paginates (the backend caps page_size at 200)
 * - exposes per-row Acknowledge and Dismiss actions
 * - lets the user send a test Slack message for an alert
 *
 * The v1 backend is in ``app/routes/sprint3.py``; the client
 * wrappers are in ``@/lib/api``.
 */

import { useState } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  acknowledgeAlertV1,
  dismissAlert,
  listAlerts,
  testSlackForAlert,
  type AlertListItem,
  type AlertListParams,
  type AlertSeverity,
  type AlertStatusFilter,
} from "@/lib/api";
import { formatDistanceToNow } from "@/lib/utils";
import {
  AlertTriangle,
  Check,
  CheckCircle,
  Send,
  Trash2,
  XCircle,
  Filter,
  RefreshCw,
} from "lucide-react";

const SEVERITY_OPTIONS: { value: AlertSeverity | ""; label: string }[] = [
  { value: "", label: "All severities" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" },
];

const STATUS_OPTIONS: { value: AlertStatusFilter | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "dismissed", label: "Dismissed" },
];

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<AlertListParams>({
    page: 1,
    page_size: 25,
  });
  const [showFilters, setShowFilters] = useState(false);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["alerts", "v1", filters],
    queryFn: () => listAlerts(filters),
  });

  const ackMutation = useMutation({
    mutationFn: (alertId: string) => acknowledgeAlertV1(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts", "v1"] });
    },
  });

  const dismissMutation = useMutation({
    mutationFn: (alertId: string) => dismissAlert(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts", "v1"] });
    },
  });

  const testSlackMutation = useMutation({
    mutationFn: (alertId: string) => testSlackForAlert(alertId),
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Alert History</h1>
          <p className="text-gray-600 mt-2">
            View, acknowledge, and dismiss triggered alerts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded"
          >
            <RefreshCw className="w-3 h-3" />
            Refresh
          </button>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded"
          >
            <Filter className="w-3 h-3" />
            {showFilters ? "Hide filters" : "Filters"}
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="mb-4 p-4 bg-white border border-gray-200 rounded-lg grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block text-sm">
            <span className="text-gray-700">Status</span>
            <select
              value={filters.status ?? ""}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  page: 1,
                  status:
                    (e.target.value as AlertStatusFilter) || undefined,
                })
              }
              className="mt-1 w-full px-2 py-1 border border-gray-300 rounded"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-gray-700">Severity</span>
            <select
              value={filters.severity ?? ""}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  page: 1,
                  severity:
                    (e.target.value as AlertSeverity) || undefined,
                })
              }
              className="mt-1 w-full px-2 py-1 border border-gray-300 rounded"
            >
              {SEVERITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-gray-700">Source ID</span>
            <input
              type="text"
              value={filters.source_id ?? ""}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  page: 1,
                  source_id: e.target.value || undefined,
                })
              }
              placeholder="filter by source id"
              className="mt-1 w-full px-2 py-1 border border-gray-300 rounded"
            />
          </label>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading alerts...</div>
      ) : isError ? (
        <div className="text-center py-12 text-red-500">
          Failed to load alerts.
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <AlertTriangle className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-500">No alerts match these filters.</p>
        </div>
      ) : (
        <>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2 text-left">Severity</th>
                  <th className="px-4 py-2 text-left">Status</th>
                  <th className="px-4 py-2 text-left">Source</th>
                  <th className="px-4 py-2 text-left">Message</th>
                  <th className="px-4 py-2 text-left">Detected</th>
                  <th className="px-4 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items.map((alert) => (
                  <AlertRow
                    key={alert.id}
                    alert={alert}
                    onAcknowledge={() => ackMutation.mutate(alert.id)}
                    onDismiss={() => dismissMutation.mutate(alert.id)}
                    onTestSlack={() => testSlackMutation.mutate(alert.id)}
                    ackPending={
                      ackMutation.isPending && ackMutation.variables === alert.id
                    }
                    dismissPending={
                      dismissMutation.isPending &&
                      dismissMutation.variables === alert.id
                    }
                    testPending={
                      testSlackMutation.isPending &&
                      testSlackMutation.variables === alert.id
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            hasMore={data.has_more}
            onPageChange={(p) => setFilters({ ...filters, page: p })}
          />
        </>
      )}

      {testSlackMutation.data && (
        <p className="mt-4 text-sm text-gray-600 text-center">
          {testSlackMutation.data.sent
            ? "Test Slack message sent."
            : "Test Slack message failed."}
        </p>
      )}
    </div>
  );
}

function AlertRow({
  alert,
  onAcknowledge,
  onDismiss,
  onTestSlack,
  ackPending,
  dismissPending,
  testPending,
}: {
  alert: AlertListItem;
  onAcknowledge: () => void;
  onDismiss: () => void;
  onTestSlack: () => void;
  ackPending: boolean;
  dismissPending: boolean;
  testPending: boolean;
}) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3">
        <SeverityBadge severity={alert.severity} />
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={alert.status} />
      </td>
      <td className="px-4 py-3">
        <div className="font-medium text-gray-800">
          {alert.source_name || alert.source_id || "—"}
        </div>
        {alert.rule_name && (
          <div className="text-xs text-gray-500">{alert.rule_name}</div>
        )}
      </td>
      <td className="px-4 py-3 max-w-md">
        <div className="text-gray-800 truncate" title={alert.message}>
          {alert.message}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
        {formatDistanceToNow(alert.detected_at)}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          {alert.status === "open" && (
            <button
              onClick={onAcknowledge}
              disabled={ackPending}
              className="text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {ackPending ? "..." : "Ack"}
            </button>
          )}
          {alert.status !== "dismissed" && (
            <button
              onClick={onDismiss}
              disabled={dismissPending}
              className="text-xs px-2 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50"
              title="Dismiss"
            >
              {dismissPending ? "..." : <Trash2 className="w-3 h-3" />}
            </button>
          )}
          <button
            onClick={onTestSlack}
            disabled={testPending}
            className="text-xs px-2 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50"
            title="Send test Slack"
          >
            {testPending ? "..." : <Send className="w-3 h-3" />}
          </button>
        </div>
      </td>
    </tr>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const color =
    severity === "critical"
      ? "bg-red-200 text-red-900"
      : severity === "high"
        ? "bg-red-100 text-red-800"
        : severity === "medium"
          ? "bg-amber-100 text-amber-800"
          : "bg-green-100 text-green-800";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color}`}
    >
      {severity}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "acknowledged") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
        <Check className="w-3 h-3" /> acknowledged
      </span>
    );
  }
  if (status === "dismissed") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-gray-200 text-gray-600">
        <XCircle className="w-3 h-3" /> dismissed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">
      <CheckCircle className="w-3 h-3" /> open
    </span>
  );
}

function Pagination({
  page,
  pageSize,
  total,
  hasMore,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  hasMore: boolean;
  onPageChange: (p: number) => void;
}) {
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-gray-500">
      <span>
        {total === 0
          ? "0 alerts"
          : `Showing ${start}–${end} of ${total} alerts`}
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="px-2 py-1 border border-gray-300 rounded disabled:opacity-50"
        >
          Prev
        </button>
        <span>Page {page}</span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={!hasMore}
          className="px-2 py-1 border border-gray-300 rounded disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}
