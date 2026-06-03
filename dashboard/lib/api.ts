const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API Error: ${res.status}`);
  }
  return res.json();
}

// Types
export interface WebhookSource {
  id: string;
  name: string;
  platform: string;
  alert_config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface WorkflowEvent {
  id: string;
  source_id: string;
  workflow_id: string;
  run_id: string | null;
  event_type: string;
  status: string;
  payload: Record<string, unknown> | null;
  error_message: string | null;
  duration_ms: number | null;
  received_at: string;
}

export interface DashboardStats {
  total_events: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  active_sources: number;
  events_today: number;
}

export interface AlertLog {
  id: string;
  source_id: string;
  alert_type: string;
  triggered_at: string;
  message: string | null;
  status: string;
}

// API Functions
export async function getDashboardStats(): Promise<DashboardStats> {
  return fetchAPI<DashboardStats>("/api/dashboard/stats");
}

export async function getSources(): Promise<WebhookSource[]> {
  return fetchAPI<WebhookSource[]>("/api/sources");
}

export async function getSource(id: string): Promise<WebhookSource> {
  return fetchAPI<WebhookSource>(`/api/sources/${id}`);
}

export async function createSource(data: {
  id: string;
  name: string;
  signing_secret: string;
  platform: string;
  alert_config?: Record<string, unknown>;
}): Promise<WebhookSource> {
  const res = await fetch(`${API_BASE}/api/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error(`Failed to create source: ${res.status}`);
  }
  return res.json();
}

export async function updateSource(
  id: string,
  data: { name?: string; alert_config?: Record<string, unknown>; is_active?: boolean }
): Promise<WebhookSource> {
  const res = await fetch(`${API_BASE}/api/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error(`Failed to update source: ${res.status}`);
  }
  return res.json();
}

export async function deleteSource(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sources/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Failed to delete source: ${res.status}`);
  }
}

export async function getEvents(params?: {
  source_id?: string;
  status?: string;
  limit?: number;
}): Promise<WorkflowEvent[]> {
  const searchParams = new URLSearchParams();
  if (params?.source_id) searchParams.set("source_id", params.source_id);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  
  const query = searchParams.toString();
  return fetchAPI<WorkflowEvent[]>(`/api/events${query ? `?${query}` : ""}`);
}

export async function getRecentEvents(limit: number = 10): Promise<WorkflowEvent[]> {
  return getEvents({ limit });
}

export async function getEvent(id: string): Promise<WorkflowEvent> {
  return fetchAPI<WorkflowEvent>(`/api/events/${id}`);
}

export async function getAlerts(sourceId?: string): Promise<AlertLog[]> {
  const query = sourceId ? `?source_id=${sourceId}` : "";
  return fetchAPI<AlertLog[]>(`/api/alerts${query}`);
}

// SSE for real-time updates
export function createEventSource(): EventSource {
  return new EventSource(`${API_BASE}/api/stream/events`);
}

// ============== P2: Alert rules (mute windows + escalation) ==============

export interface MuteWindow {
  days: string[];          // ["monday", "tuesday", ...]
  start_hour: number;      // 0-23
  end_hour: number;        // 0-23
  timezone: string;        // IANA tz name, e.g. "UTC" or "America/New_York"
}

export interface EscalationRule {
  enabled: boolean;
  minutes_until_escalate: number;
  escalate_to: string[];
}

export interface AlertRules {
  source_id: string;
  mute_windows: MuteWindow[];
  escalation: EscalationRule;
}

export interface MuteTestResult {
  source_id: string;
  muted: boolean;
  active_windows: MuteWindow[];
}

export async function getAlertRules(sourceId: string): Promise<AlertRules> {
  return fetchAPI<AlertRules>(`/api/sources/${sourceId}/alert-rules`);
}

export async function updateAlertRules(
  sourceId: string,
  rules: { mute_windows?: MuteWindow[]; escalation?: EscalationRule }
): Promise<{ source_id: string; alert_config: Record<string, unknown> }> {
  const res = await fetch(`${API_BASE}/api/sources/${sourceId}/alert-rules`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rules),
  });
  if (!res.ok) {
    throw new Error(`Failed to update alert rules: ${res.status}`);
  }
  return res.json();
}

export async function testMute(sourceId: string): Promise<MuteTestResult> {
  return fetchAPI<MuteTestResult>(`/api/sources/${sourceId}/test-mute`, {
    method: "POST",
  });
}

export async function acknowledgeAlert(
  alertId: string,
  acknowledgedBy?: string
): Promise<{
  alert_id: string;
  status: string;
  acknowledged_at: string;
  acknowledged_by: string | null;
}> {
  const res = await fetch(`${API_BASE}/api/alerts/${alertId}/acknowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(acknowledgedBy ? { acknowledged_by: acknowledgedBy } : {}),
  });
  if (!res.ok) {
    throw new Error(`Failed to acknowledge alert: ${res.status}`);
  }
  return res.json();
}

// ============== Per-source email recipients (P2) ==============

/**
 * Update the per-source email recipients list. Recipients are merged
 * into the source's alert_config.emails array.
 */
export async function updateSourceEmails(
  sourceId: string,
  emails: string[]
): Promise<WebhookSource> {
  // We need the current alert_config to merge in. The simplest path
  // is to fetch then PATCH, but for now we PATCH the whole alert_config.
  const source = await getSource(sourceId);
  const cfg = (source.alert_config as Record<string, unknown>) || {};
  return updateSource(sourceId, { alert_config: { ...cfg, emails } });
}