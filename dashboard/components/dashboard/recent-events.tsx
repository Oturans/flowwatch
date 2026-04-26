"use client";

import { formatDistanceToNow } from "@/lib/utils";
import type { WorkflowEvent } from "@/lib/api";
import { CheckCircle, XCircle, Clock, RefreshCw } from "lucide-react";

interface RecentEventsProps {
  events: WorkflowEvent[];
}

export function RecentEvents({ events }: RecentEventsProps) {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case "success":
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case "error":
        return <XCircle className="w-4 h-4 text-red-500" />;
      case "running":
        return <Clock className="w-4 h-4 text-blue-500" />;
      case "retried":
        return <RefreshCw className="w-4 h-4 text-yellow-500" />;
      default:
        return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "success":
        return "bg-green-50 border-green-200";
      case "error":
        return "bg-red-50 border-red-200";
      case "running":
        return "bg-blue-50 border-blue-200";
      case "retried":
        return "bg-yellow-50 border-yellow-200";
      default:
        return "bg-gray-50 border-gray-200";
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Recent Events</h2>
      
      {events.length === 0 ? (
        <p className="text-gray-500 text-center py-8">No events yet</p>
      ) : (
        <div className="space-y-3">
          {events.map((event) => (
            <div
              key={event.id}
              className={`flex items-center justify-between p-4 rounded-lg border ${getStatusColor(event.status)}`}
            >
              <div className="flex items-center gap-3">
                {getStatusIcon(event.status)}
                <div>
                  <p className="font-medium text-gray-900">{event.workflow_id}</p>
                  <p className="text-sm text-gray-500">
                    {event.event_type} • {event.source_id}
                  </p>
                </div>
              </div>
              <div className="text-right">
                <p className="text-sm font-medium capitalize">{event.status}</p>
                <p className="text-xs text-gray-500">
                  {formatDistanceToNow(event.received_at)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}