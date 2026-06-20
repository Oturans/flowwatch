"use client";

/**
 * Sprint 4 — single row in the traces list table.
 *
 * Wraps a clickable link that navigates to the trace detail page
 * (the link wrapping makes right-click + open-in-new-tab work).
 */

import Link from "next/link";
import type { Trace } from "@/lib/api";
import { formatDistanceToNow } from "@/lib/utils";
import { formatDuration } from "@/lib/trace-dag";

export interface TraceRowProps {
  trace: Trace;
  orgId: string;
}

function statusPill(status: string): { bg: string; text: string } {
  switch ((status ?? "").toLowerCase()) {
    case "ok":
    case "success":
      return { bg: "bg-green-100", text: "text-green-700" };
    case "error":
    case "failed":
      return { bg: "bg-red-100", text: "text-red-700" };
    case "running":
      return { bg: "bg-blue-100", text: "text-blue-700" };
    case "timeout":
      return { bg: "bg-amber-100", text: "text-amber-700" };
    case "cancelled":
      return { bg: "bg-gray-100", text: "text-gray-700" };
    default:
      return { bg: "bg-gray-100", text: "text-gray-700" };
  }
}

export function TraceRow({ trace, orgId }: TraceRowProps) {
  const pill = statusPill(trace.status);
  const errored = trace.error_message != null && trace.error_message.length > 0;
  return (
    <tr
      className="hover:bg-gray-50"
      data-testid={`trace-row-${trace.id}`}
      data-status={trace.status}
    >
      <td className="px-6 py-4 whitespace-nowrap">
        <span
          className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${pill.bg} ${pill.text}`}
        >
          {trace.status}
        </span>
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <Link
          href={`/traces/${trace.id}`}
          className="text-blue-600 hover:underline font-medium"
          data-testid={`trace-row-link-${trace.id}`}
        >
          {trace.name}
        </Link>
        <div className="text-xs text-gray-500 font-mono">{trace.trace_id}</div>
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
        {trace.workflow_id ?? "—"}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
        {trace.source ?? "—"}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
        {formatDuration(trace.duration_ms)}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
        {trace.spans?.length ?? 0}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
        {formatDistanceToNow(trace.started_at)}
      </td>
      {errored && (
        <td className="px-6 py-4 whitespace-nowrap text-xs text-red-600 max-w-xs truncate">
          {trace.error_message}
        </td>
      )}
      {/* Hidden marker so the URL passes through without being
          used as a visible column. */}
      <td className="hidden" data-org-id={orgId}></td>
    </tr>
  );
}

export default TraceRow;