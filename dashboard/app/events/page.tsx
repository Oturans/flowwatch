"use client";

import { useQuery } from "@tanstack/react-query";
import { getEvents, type WorkflowEvent } from "@/lib/api";
import { CheckCircle, XCircle, Clock, RefreshCw } from "lucide-react";
import Link from "next/link";
import { formatDistanceToNow } from "@/lib/utils";

export default function EventsPage() {
  const { data: events = [], isLoading } = useQuery({
    queryKey: ["events"],
    queryFn: () => getEvents({ limit: 100 }),
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Workflow Events</h1>
        <p className="text-gray-600 mt-2">View all incoming webhook events</p>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading events...</div>
      ) : events.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <p className="text-gray-500">No events recorded yet</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Workflow</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: WorkflowEvent }) {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case "success":
        return <CheckCircle className="w-5 h-5 text-green-500" />;
      case "error":
        return <XCircle className="w-5 h-5 text-red-500" />;
      case "running":
        return <Clock className="w-5 h-5 text-blue-500" />;
      case "retried":
        return <RefreshCw className="w-5 h-5 text-yellow-500" />;
      default:
        return <Clock className="w-5 h-5 text-gray-400" />;
    }
  };

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-6 py-4 whitespace-nowrap">
        <div className="flex items-center gap-2">
          {getStatusIcon(event.status)}
          <span className="capitalize font-medium">{event.status}</span>
        </div>
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <Link href={`/events/${event.id}`} className="text-blue-600 hover:underline">
          {event.workflow_id}
        </Link>
        {event.run_id && (
          <p className="text-xs text-gray-500">Run: {event.run_id}</p>
        )}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-gray-500">
        {event.source_id}
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${
          event.event_type === "failed" ? "bg-red-100 text-red-700" :
          event.event_type === "completed" ? "bg-green-100 text-green-700" :
          "bg-gray-100 text-gray-700"
        }`}>
          {event.event_type}
        </span>
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-gray-500">
        {formatDistanceToNow(event.received_at)}
      </td>
    </tr>
  );
}