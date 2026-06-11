"use client";

/**
 * SlackConfigForm
 *
 * Per-source Slack webhook configuration. Stores the URL in
 * ``WebhookSource.alert_config.slack_webhook_url`` (the existing
 * ``send_alert`` Celery task already reads from this location) and
 * the enabled flag + channel hint alongside.
 *
 * Communicates with:
 *   GET  /api/v1/sources/{id}/slack-config
 *   POST /api/v1/sources/{id}/slack-config
 *
 * The form does NOT validate the URL client-side beyond the prefix
 * check; the server is the source of truth and rejects URLs that
 * don't start with the Slack hooks host. We surface the server's
 * error message inline so the user can correct typos.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getSlackConfig,
  setSlackConfig,
  type SlackConfigResponse,
} from "@/lib/api";
import { Loader2, MessageSquare, Send } from "lucide-react";

export function SlackConfigForm({ sourceId }: { sourceId: string }) {
  const queryClient = useQueryClient();
  const [webhookUrl, setWebhookUrl] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [channelHint, setChannelHint] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  const query = useQuery({
    queryKey: ["slack-config", sourceId],
    queryFn: () => getSlackConfig(sourceId),
  });

  useEffect(() => {
    if (query.data) {
      setEnabled(query.data.enabled);
      setChannelHint(query.data.channel_hint || "");
      // Don't populate the URL field — it's a secret. The user
      // only ever types it once; subsequent edits show a
      // placeholder.
    }
  }, [query.data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      setSlackConfig(sourceId, {
        webhook_url: webhookUrl || null,
        enabled,
        channel_hint: channelHint || null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["slack-config", sourceId], data);
      queryClient.invalidateQueries({ queryKey: ["slack-config", sourceId] });
      setIsEditing(false);
      setWebhookUrl(""); // clear the secret from local state
    },
  });

  const clearMutation = useMutation({
    mutationFn: () =>
      setSlackConfig(sourceId, {
        webhook_url: "",
        enabled,
        channel_hint: channelHint || null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["slack-config", sourceId], data);
      queryClient.invalidateQueries({ queryKey: ["slack-config", sourceId] });
    },
  });

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading Slack config...
      </div>
    );
  }

  const config: SlackConfigResponse | undefined = query.data;
  const hasConfig = !!config?.webhook_url_set;

  return (
    <div className="space-y-2">
      <h5 className="text-xs font-semibold text-gray-700 uppercase flex items-center gap-1">
        <MessageSquare className="w-3 h-3" /> Slack Webhook
      </h5>

      <div className="p-2 bg-white border border-gray-200 rounded space-y-2">
        <div className="flex items-center gap-2 text-sm">
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              hasConfig && enabled
                ? "bg-green-100 text-green-800"
                : hasConfig
                  ? "bg-amber-100 text-amber-800"
                  : "bg-gray-100 text-gray-600"
            }`}
          >
            {hasConfig && enabled
              ? "Active"
              : hasConfig
                ? "Configured (paused)"
                : "Not configured"}
          </span>
          {hasConfig && (
            <button
              onClick={() => clearMutation.mutate()}
              disabled={clearMutation.isPending}
              className="text-xs text-red-600 hover:text-red-700"
            >
              {clearMutation.isPending ? "Clearing..." : "Clear"}
            </button>
          )}
        </div>

        {(!hasConfig || isEditing) && (
          <div className="space-y-2">
            <input
              type="text"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder={
                hasConfig
                  ? "Enter new URL to replace"
                  : "https://hooks.slack.com/services/T0/B0/secret"
              }
              className="w-full px-2 py-1 border border-gray-300 rounded text-sm font-mono"
            />
            <input
              type="text"
              value={channelHint}
              onChange={(e) => setChannelHint(e.target.value)}
              placeholder="Channel hint (e.g. #ops)"
              className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="rounded"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              <span>Send notifications</span>
            </label>
            <div className="flex items-center gap-2">
              <button
                onClick={() => saveMutation.mutate()}
                disabled={!webhookUrl || saveMutation.isPending}
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
              >
                <Send className="w-3 h-3" />
                {saveMutation.isPending ? "Saving..." : "Save webhook"}
              </button>
              {isEditing && (
                <button
                  onClick={() => {
                    setIsEditing(false);
                    setWebhookUrl("");
                  }}
                  className="px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300"
                >
                  Cancel
                </button>
              )}
            </div>
            {saveMutation.isError && (
              <p className="text-xs text-red-600">
                {(saveMutation.error as Error)?.message || "Save failed"}
              </p>
            )}
          </div>
        )}

        {hasConfig && !isEditing && (
          <button
            onClick={() => setIsEditing(true)}
            className="text-xs text-blue-600 hover:text-blue-700"
          >
            Update webhook
          </button>
        )}
      </div>
    </div>
  );
}
