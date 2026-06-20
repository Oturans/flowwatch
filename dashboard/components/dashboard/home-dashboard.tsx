"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  getDashboardStats,
  getRecentEvents,
  getSources,
} from "@/lib/api";
import { DashboardStats } from "@/components/dashboard/stats-card";
import { RecentEvents } from "@/components/dashboard/recent-events";
import { SourcesOverview } from "@/components/dashboard/sources-overview";

/**
 * Client-side home dashboard.
 *
 * Uses React Query so the Authorization header attached by our
 * api client is sent on every request. (Server components don't
 * have access to localStorage and would have to round-trip
 * through a cookie-based session, which is out of scope for
 * Sprint 1.)
 */
export function HomeDashboard() {
  const stats = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => getDashboardStats(),
  });
  const events = useQuery({
    queryKey: ["events", "recent", 5],
    queryFn: () => getRecentEvents(5),
  });
  const sources = useQuery({
    queryKey: ["sources"],
    queryFn: () => getSources(),
  });

  const isLoading = stats.isLoading || events.isLoading || sources.isLoading;
  const hasError = stats.error || events.error || sources.error;

  if (isLoading) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="text-gray-500 text-sm">Loading dashboard…</div>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 text-sm">
          Failed to load dashboard:{" "}
          {String(
            (stats.error || events.error || sources.error) ?? "unknown error"
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">FlowWatch Dashboard</h1>
        <p className="text-gray-600 mt-2">
          Real-time observability for your AI workflows
        </p>
      </div>

      <div className="mb-8 flex gap-4">
        <Link
          href="/sources"
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
        >
          Manage Sources
        </Link>
        <Link
          href="/events"
          className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition"
        >
          View All Events
        </Link>
        <Link
          href="/alerts"
          className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition"
        >
          Alert History
        </Link>
        <Link
          href="/traces"
          className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition"
          data-testid="home-traces-link"
        >
          View Traces
        </Link>
      </div>

      {stats.data && <DashboardStats stats={stats.data} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        {events.data && <RecentEvents events={events.data} />}
        {sources.data && <SourcesOverview sources={sources.data} />}
      </div>
    </div>
  );
}

export default HomeDashboard;
