"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getAlerts, acknowledgeAlert, type AlertLog } from "@/lib/api";
import { AlertTriangle, CheckCircle, XCircle, Check } from "lucide-react";
import { formatDistanceToNow } from "@/lib/utils";

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const { data: alerts = [], isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => getAlerts(),
  });

  const ackMutation = useMutation({
    mutationFn: (alertId: string) => acknowledgeAlert(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Alert History</h1>
        <p className="text-gray-600 mt-2">View and acknowledge alerts to suppress escalation</p>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">Loading alerts...</div>
      ) : alerts.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <AlertTriangle className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-500">No alerts triggered yet</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {alerts.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              onAcknowledge={() => ackMutation.mutate(alert.id)}
              ackPending={ackMutation.isPending && ackMutation.variables === alert.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AlertCard({
  alert,
  onAcknowledge,
  ackPending,
}: {
  alert: AlertLog;
  onAcknowledge: () => void;
  ackPending: boolean;
}) {
  const isAcknowledged = alert.status === "acknowledged" || alert.status === "escalated";

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "sent":
        return <CheckCircle className="w-5 h-5 text-green-500" />;
      case "acknowledged":
        return <Check className="w-5 h-5 text-blue-500" />;
      case "escalated":
        return <AlertTriangle className="w-5 h-5 text-red-500" />;
      case "failed":
        return <XCircle className="w-5 h-5 text-red-500" />;
      default:
        return <AlertTriangle className="w-5 h-5 text-yellow-500" />;
    }
  };

  return (
    <div className="bg-white p-6 rounded-xl border border-gray-200">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className={`p-3 rounded-xl ${
            alert.status === "sent" ? "bg-green-100" :
            alert.status === "acknowledged" ? "bg-blue-100" :
            alert.status === "escalated" ? "bg-red-100" :
            alert.status === "failed" ? "bg-red-100" :
            "bg-yellow-100"
          }`}>
            {getStatusIcon(alert.status)}
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 capitalize">{alert.alert_type} Alert</h3>
            <p className="text-sm text-gray-500">Source: {alert.source_id}</p>
            {alert.message && (
              <p className="text-sm text-gray-700 mt-1">{alert.message}</p>
            )}
          </div>
        </div>
        <div className="text-right flex flex-col items-end gap-2">
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            alert.status === "sent" ? "bg-green-100 text-green-700" :
            alert.status === "acknowledged" ? "bg-blue-100 text-blue-700" :
            alert.status === "escalated" ? "bg-red-100 text-red-700" :
            alert.status === "failed" ? "bg-red-100 text-red-700" :
            "bg-yellow-100 text-yellow-700"
          }`}>
            {alert.status}
          </span>
          <p className="text-sm text-gray-500">
            {formatDistanceToNow(alert.triggered_at)}
          </p>
          {!isAcknowledged && (
            <button
              onClick={onAcknowledge}
              disabled={ackPending}
              className="text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {ackPending ? "Acknowledging..." : "Acknowledge"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}