"use client";

import { Activity, AlertCircle, CheckCircle, Zap } from "lucide-react";
import type { DashboardStats as DashboardStatsType } from "@/lib/api";

interface DashboardStatsProps {
  stats: DashboardStatsType;
}

export function DashboardStats({ stats }: DashboardStatsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <StatCard
        title="Total Events"
        value={stats.total_events.toLocaleString()}
        icon={<Activity className="w-5 h-5" />}
        description="All-time webhook events"
      />
      <StatCard
        title="Success Rate"
        value={`${stats.success_rate.toFixed(1)}%`}
        icon={<CheckCircle className="w-5 h-5 text-green-500" />}
        description={`${stats.success_count} successful`}
        trend={stats.success_rate >= 95 ? "good" : "warning"}
      />
      <StatCard
        title="Active Sources"
        value={stats.active_sources.toString()}
        icon={<Zap className="w-5 h-5 text-blue-500" />}
        description="Connected webhook sources"
      />
      <StatCard
        title="Events Today"
        value={stats.events_today.toLocaleString()}
        icon={<AlertCircle className="w-5 h-5 text-orange-500" />}
        description="Webhook events in last 24h"
      />
    </div>
  );
}

interface StatCardProps {
  title: string;
  value: string;
  icon: React.ReactNode;
  description: string;
  trend?: "good" | "warning" | "danger";
}

function StatCard({ title, value, icon, description, trend }: StatCardProps) {
  const trendColors = {
    good: "bg-green-50 text-green-700",
    warning: "bg-yellow-50 text-yellow-700",
    danger: "bg-red-50 text-red-700",
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-500">{title}</h3>
        {icon}
      </div>
      <div className="text-3xl font-bold text-gray-900 mb-1">{value}</div>
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-500">{description}</span>
        {trend && (
          <span className={`text-xs px-2 py-1 rounded-full ${trendColors[trend]}`}>
            {trend === "good" ? "Healthy" : trend === "warning" ? "Attention" : "Critical"}
          </span>
        )}
      </div>
    </div>
  );
}