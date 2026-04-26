import { getDashboardStats, getRecentEvents, getSources } from "@/lib/api";
import { DashboardStats } from "@/components/dashboard/stats-card";
import { RecentEvents } from "@/components/dashboard/recent-events";
import { SourcesOverview } from "@/components/dashboard/sources-overview";
import Link from "next/link";

export default async function HomePage() {
  const [stats, events, sources] = await Promise.all([
    getDashboardStats(),
    getRecentEvents(5),
    getSources(),
  ]);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">FlowWatch Dashboard</h1>
        <p className="text-gray-600 mt-2">Real-time observability for your AI workflows</p>
      </div>

      <div className="mb-8 flex gap-4">
        <Link href="/sources" className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition">
          Manage Sources
        </Link>
        <Link href="/events" className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition">
          View All Events
        </Link>
        <Link href="/alerts" className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition">
          Alert History
        </Link>
      </div>

      <DashboardStats stats={stats} />
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        <RecentEvents events={events} />
        <SourcesOverview sources={sources} />
      </div>
    </div>
  );
}