"use client";

/**
 * AlertRulesEditor
 *
 * Per-source editor for P2 features:
 *   - Mute windows (timezone-aware day/hour scheduling)
 *   - Escalation rules (acknowledge-to-suppress with Celery Beat)
 *   - Per-source email recipients
 *
 * Communicates with the API via:
 *   GET  /api/sources/{id}/alert-rules
 *   PUT  /api/sources/{id}/alert-rules
 *   POST /api/sources/{id}/test-mute
 *
 * Designed to be embedded inside the existing Sources page; the
 * "Configure alerts" button toggles it open. The component is
 * controlled by its parent (which provides the source id) and manages
 * its own local state for the in-flight form.
 */

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAlertRules,
  updateAlertRules,
  testMute,
  getSource,
  updateSource,
  type MuteWindow,
  type EscalationRule,
  type AlertRules,
} from "@/lib/api";
import { ThresholdsEditor } from "@/components/sources/thresholds-editor";
import { SlackConfigForm } from "@/components/sources/slack-config-form";
import { Plus, Trash2, ChevronDown, ChevronUp, Loader2 } from "lucide-react";

const DAY_NAMES = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "America/Chicago",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Tokyo",
];

function emptyWindow(): MuteWindow {
  return { days: ["saturday", "sunday"], start_hour: 0, end_hour: 8, timezone: "UTC" };
}

function emptyEscalation(): EscalationRule {
  return { enabled: false, minutes_until_escalate: 15, escalate_to: [] };
}

function parseEmails(input: string): string[] {
  return input
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function AlertRulesEditor({ sourceId }: { sourceId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [testResult, setTestResult] = useState<{ muted: boolean; active_windows: MuteWindow[] } | null>(null);
  const [emailsInput, setEmailsInput] = useState("");

  // Current server state
  const rulesQuery = useQuery({
    queryKey: ["alert-rules", sourceId],
    queryFn: () => getAlertRules(sourceId),
    enabled: open,
  });

  const sourceQuery = useQuery({
    queryKey: ["source", sourceId],
    queryFn: () => getSource(sourceId),
    enabled: open,
  });

  // Local edit state
  const [windows, setWindows] = useState<MuteWindow[]>([]);
  const [escalation, setEscalation] = useState<EscalationRule>(emptyEscalation());

  // Sync local state from server when the query loads
  useEffect(() => {
    if (rulesQuery.data) {
      setWindows(rulesQuery.data.mute_windows || []);
      setEscalation(rulesQuery.data.escalation || emptyEscalation());
    }
  }, [rulesQuery.data]);

  useEffect(() => {
    if (sourceQuery.data) {
      const cfg = (sourceQuery.data.alert_config as Record<string, unknown>) || {};
      if (Array.isArray(cfg.emails)) {
        setEmailsInput((cfg.emails as string[]).join(", "));
      }
    }
  }, [sourceQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      // Save mute windows + escalation
      await updateAlertRules(sourceId, {
        mute_windows: windows,
        escalation,
      });
      // Save emails separately
      const emails = parseEmails(emailsInput);
      if (sourceQuery.data) {
        const cfg = (sourceQuery.data.alert_config as Record<string, unknown>) || {};
        await updateSource(sourceId, { alert_config: { ...cfg, emails } });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-rules", sourceId] });
      queryClient.invalidateQueries({ queryKey: ["source", sourceId] });
      queryClient.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  const testMutation = useMutation({
    mutationFn: () => testMute(sourceId),
    onSuccess: (data) => setTestResult(data),
  });

  const hasChanges = useMemo(() => {
    if (!rulesQuery.data) return false;
    const orig = rulesQuery.data;
    if (JSON.stringify(orig.mute_windows) !== JSON.stringify(windows)) return true;
    if (JSON.stringify(orig.escalation) !== JSON.stringify(escalation)) return true;
    const origEmails = ((sourceQuery.data?.alert_config as Record<string, unknown>)?.emails as string[]) || [];
    const newEmails = parseEmails(emailsInput);
    if (JSON.stringify(origEmails.sort()) !== JSON.stringify(newEmails.sort())) return true;
    return false;
  }, [rulesQuery.data, sourceQuery.data, windows, escalation, emailsInput]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg flex items-center gap-1"
      >
        <ChevronDown className="w-3 h-3" />
        Configure alerts
      </button>
    );
  }

  return (
    <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-gray-900">Alert Rules</h4>
        <button
          onClick={() => setOpen(false)}
          className="p-1 hover:bg-gray-200 rounded"
          aria-label="Close"
        >
          <ChevronUp className="w-4 h-4" />
        </button>
      </div>

      {rulesQuery.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading rules...
        </div>
      ) : (
        <>
          {/* Mute windows */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h5 className="text-xs font-semibold text-gray-700 uppercase">Mute Windows</h5>
              <button
                type="button"
                onClick={() => setWindows([...windows, emptyWindow()])}
                className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1"
              >
                <Plus className="w-3 h-3" /> Add
              </button>
            </div>
            {windows.length === 0 ? (
              <p className="text-xs text-gray-500 italic">No mute windows. Alerts are always sent.</p>
            ) : (
              <div className="space-y-2">
                {windows.map((w, i) => (
                  <MuteWindowRow
                    key={i}
                    window={w}
                    onChange={(nw) => setWindows(windows.map((x, j) => (i === j ? nw : x)))}
                    onRemove={() => setWindows(windows.filter((_, j) => j !== i))}
                  />
                ))}
              </div>
            )}
            <button
              type="button"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending}
              className="mt-2 text-xs px-2 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
            >
              {testMutation.isPending ? "Testing..." : "Test current time"}
            </button>
            {testResult && (
              <div
                className={`mt-2 text-xs px-2 py-1 rounded ${
                  testResult.muted
                    ? "bg-amber-100 text-amber-800"
                    : "bg-green-100 text-green-800"
                }`}
              >
                {testResult.muted
                  ? `Currently muted (${testResult.active_windows.length} active window(s))`
                  : "Currently active (alerts will be sent)"}
              </div>
            )}
          </section>

          {/* Escalation */}
          <section>
            <h5 className="text-xs font-semibold text-gray-700 uppercase mb-2">Escalation</h5>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={escalation.enabled}
                onChange={(e) =>
                  setEscalation({ ...escalation, enabled: e.target.checked })
                }
                className="rounded"
              />
              <span>Enable escalation</span>
            </label>
            {escalation.enabled && (
              <div className="mt-2 space-y-2 pl-6">
                <label className="block text-xs text-gray-600">
                  Escalate after (minutes)
                  <input
                    type="number"
                    min={1}
                    max={10080}
                    value={escalation.minutes_until_escalate}
                    onChange={(e) =>
                      setEscalation({
                        ...escalation,
                        minutes_until_escalate: parseInt(e.target.value, 10) || 15,
                      })
                    }
                    className="ml-2 px-2 py-1 border border-gray-300 rounded w-20 text-sm"
                  />
                </label>
                <label className="block text-xs text-gray-600">
                  Escalate to (comma-separated emails)
                  <input
                    type="text"
                    value={escalation.escalate_to.join(", ")}
                    onChange={(e) =>
                      setEscalation({
                        ...escalation,
                        escalate_to: parseEmails(e.target.value),
                      })
                    }
                    placeholder="manager@example.com, ceo@example.com"
                    className="mt-1 w-full px-2 py-1 border border-gray-300 rounded text-sm"
                  />
                </label>
                <p className="text-xs text-gray-500 italic">
                  Acknowledging an alert stops escalation. Celery Beat checks every 5 minutes.
                </p>
              </div>
            )}
          </section>

          {/* Per-source emails */}
          <section>
            <h5 className="text-xs font-semibold text-gray-700 uppercase mb-2">
              Email Recipients
            </h5>
            <input
              type="text"
              value={emailsInput}
              onChange={(e) => setEmailsInput(e.target.value)}
              placeholder="oncall@example.com, ops@example.com"
              className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
            />
            <p className="mt-1 text-xs text-gray-500 italic">
              Per-source recipients override the global default. Leave empty to use the
              global default.
            </p>
          </section>

          {/* Sprint 3: per-source anomaly thresholds */}
          <section className="space-y-2">
            <ThresholdsEditor sourceId={sourceId} />
          </section>

          {/* Sprint 3: Slack webhook */}
          <section>
            <SlackConfigForm sourceId={sourceId} />
          </section>

          <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!hasChanges || saveMutation.isPending}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saveMutation.isPending ? "Saving..." : "Save changes"}
            </button>
            {saveMutation.isSuccess && !saveMutation.isPending && (
              <span className="text-xs text-green-600">Saved</span>
            )}
            {saveMutation.isError && (
              <span className="text-xs text-red-600">Save failed</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function MuteWindowRow({
  window: w,
  onChange,
  onRemove,
}: {
  window: MuteWindow;
  onChange: (w: MuteWindow) => void;
  onRemove: () => void;
}) {
  return (
    <div className="p-2 bg-white border border-gray-200 rounded space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 space-y-2">
          {/* Day checkboxes */}
          <div className="flex flex-wrap gap-1">
            {DAY_NAMES.map((day) => {
              const checked = w.days.includes(day);
              return (
                <label
                  key={day}
                  className={`px-2 py-0.5 text-xs border rounded cursor-pointer ${
                    checked
                      ? "bg-blue-100 border-blue-300 text-blue-800"
                      : "bg-white border-gray-200 text-gray-500"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="hidden"
                    checked={checked}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...w.days, day]
                        : w.days.filter((d) => d !== day);
                      onChange({ ...w, days: next });
                    }}
                  />
                  {day.slice(0, 3)}
                </label>
              );
            })}
          </div>
          {/* Hours */}
          <div className="flex items-center gap-2 text-xs">
            <input
              type="number"
              min={0}
              max={23}
              value={w.start_hour}
              onChange={(e) =>
                onChange({ ...w, start_hour: parseInt(e.target.value, 10) || 0 })
              }
              className="w-14 px-1 py-0.5 border border-gray-300 rounded"
            />
            <span className="text-gray-500">to</span>
            <input
              type="number"
              min={0}
              max={23}
              value={w.end_hour}
              onChange={(e) =>
                onChange({ ...w, end_hour: parseInt(e.target.value, 10) || 0 })
              }
              className="w-14 px-1 py-0.5 border border-gray-300 rounded"
            />
            <select
              value={w.timezone}
              onChange={(e) => onChange({ ...w, timezone: e.target.value })}
              className="px-1 py-0.5 border border-gray-300 rounded text-xs"
            >
              {COMMON_TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="p-1 text-red-500 hover:bg-red-50 rounded"
          aria-label="Remove"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
