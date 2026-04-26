"use client";

import { Folder, Activity } from "lucide-react";
import type { WebhookSource } from "@/lib/api";
import Link from "next/link";

interface SourcesOverviewProps {
  sources: WebhookSource[];
}

export function SourcesOverview({ sources }: SourcesOverviewProps) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Webhook Sources</h2>
        <Link
          href="/sources"
          className="text-sm text-blue-600 hover:text-blue-700 font-medium"
        >
          Manage →
        </Link>
      </div>

      {sources.length === 0 ? (
        <div className="text-center py-8">
          <Folder className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">No sources connected yet</p>
          <Link
            href="/sources"
            className="text-blue-600 hover:text-blue-700 text-sm font-medium mt-2 inline-block"
          >
            Add your first source
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {sources.slice(0, 5).map((source) => (
            <div
              key={source.id}
              className="flex items-center justify-between p-4 bg-gray-50 rounded-lg border border-gray-200"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-100 rounded-lg">
                  <Activity className="w-4 h-4 text-blue-600" />
                </div>
                <div>
                  <p className="font-medium text-gray-900">{source.name}</p>
                  <p className="text-sm text-gray-500 capitalize">{source.platform}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-1 rounded-full text-xs font-medium ${
                    source.is_active
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {source.is_active ? "Active" : "Inactive"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}