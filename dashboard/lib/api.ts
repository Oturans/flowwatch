const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Auth token storage
// ---------------------------------------------------------------------------
//
// Tokens live in localStorage under a single namespaced key. The auth
// context below owns reading/writing this; helper functions here
// are kept tiny so non-React code (e.g. fetch) can still read it.

export const AUTH_TOKEN_KEY = "flowwatch:auth:token";
export const AUTH_REFRESH_KEY = "flowwatch:auth:refresh";
export const AUTH_USER_KEY = "flowwatch:auth:user";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getStoredUser(): import("./api").AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(AUTH_USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as import("./api").AuthUser;
  } catch {
    return null;
  }
}

export function getStoredRefresh(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(AUTH_REFRESH_KEY);
}

export function storeAuth(token: string, refresh: string, user: AuthUser) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  window.localStorage.setItem(AUTH_REFRESH_KEY, refresh);
  window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_REFRESH_KEY);
  window.localStorage.removeItem(AUTH_USER_KEY);
}

async function fetchAPI<T>(endpoint: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  };

  // Auto-attach bearer token if we have one and the caller didn't
  // set their own Authorization header. Endpoints that need to
  // remain public (auth/*) won't be impacted because they ignore
  // the header.
  if (!headers["Authorization"] && !headers["authorization"]) {
    const token = getStoredToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${endpoint}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) {
      // Surface a typed error the auth context can pick up.
      const err = new Error(`API Error: ${res.status}`) as Error & {
        status?: number;
      };
      err.status = 401;
      throw err;
    }
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

// ============== Sprint 1: Auth + multi-tenant ==============

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  org_id: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthTenant {
  id: string;
  name: string;
  slug: string;
  plan: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterPayload {
  tenant: {
    name: string;
    slug: string;
    plan?: string;
  };
  user: {
    email: string;
    password: string;
    full_name?: string | null;
  };
}

export interface RegisterResponse {
  user: AuthUser;
  tenant: AuthTenant;
  tokens: TokenPair;
}

export interface MeResponse {
  user: AuthUser;
  tenant: AuthTenant;
}

export async function register(
  payload: RegisterPayload
): Promise<RegisterResponse> {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to register: ${res.status}`);
  }
  return res.json();
}

export async function login(
  email: string,
  password: string
): Promise<TokenPair> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to login: ${res.status}`);
  }
  return res.json();
}

export async function refresh(refreshToken: string): Promise<TokenPair> {
  const res = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to refresh: ${res.status}`);
  }
  return res.json();
}

export async function fetchMe(): Promise<MeResponse> {
  return fetchAPI<MeResponse>("/api/auth/me");
}

async function safeDetail(res: Response): Promise<string | null> {
  try {
    const j = await res.json();
    if (j && typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return null;
}

// ============== Sprint 3: per-source thresholds + alerts v1 ==============

export type ThresholdMetric = "latency_ms" | "error_rate_pct" | "failure_count";

export interface ThresholdItem {
  metric: ThresholdMetric;
  value: number;
  window_seconds: number;
  enabled: boolean;
}

export interface ThresholdResponse extends ThresholdItem {
  updated_at: string;
}

export interface ThresholdsResponse {
  source_id: string;
  thresholds: ThresholdResponse[];
}

export interface SlackConfigResponse {
  source_id: string;
  webhook_url_set: boolean;
  enabled: boolean;
  channel_hint: string | null;
}

export type AlertStatusFilter = "open" | "acknowledged" | "dismissed";
export type AlertSeverity = "low" | "medium" | "high" | "critical";

export interface AlertListItem {
  id: string;
  source_id: string;
  source_name: string | null;
  rule_id: string;
  rule_name: string | null;
  severity: string;
  status: string;
  message: string;
  context: Record<string, unknown> | null;
  detected_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  dismissed_at: string | null;
  dismissed_by: string | null;
}

export interface AlertListResponse {
  items: AlertListItem[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface AlertListParams {
  source_id?: string;
  status?: AlertStatusFilter;
  severity?: AlertSeverity;
  start?: string;
  end?: string;
  page?: number;
  page_size?: number;
}

export async function getSourceThresholds(
  sourceId: string
): Promise<ThresholdsResponse> {
  return fetchAPI<ThresholdsResponse>(
    `/api/v1/sources/${encodeURIComponent(sourceId)}/thresholds`
  );
}

export async function updateSourceThresholds(
  sourceId: string,
  thresholds: ThresholdItem[]
): Promise<ThresholdsResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/sources/${encodeURIComponent(sourceId)}/thresholds`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thresholds }),
    }
  );
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to update thresholds: ${res.status}`);
  }
  return res.json();
}

export async function getSlackConfig(
  sourceId: string
): Promise<SlackConfigResponse> {
  return fetchAPI<SlackConfigResponse>(
    `/api/v1/sources/${encodeURIComponent(sourceId)}/slack-config`
  );
}

export async function setSlackConfig(
  sourceId: string,
  body: {
    webhook_url?: string | null;
    enabled?: boolean;
    channel_hint?: string | null;
  }
): Promise<SlackConfigResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/sources/${encodeURIComponent(sourceId)}/slack-config`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to set Slack config: ${res.status}`);
  }
  return res.json();
}

export async function testSlackForAlert(
  alertId: string
): Promise<{ alert_id: string; source_id: string; sent: boolean }> {
  const res = await fetch(
    `${API_BASE}/api/v1/alerts/${encodeURIComponent(alertId)}/test-slack`,
    { method: "POST" }
  );
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to test Slack: ${res.status}`);
  }
  return res.json();
}

export async function listAlerts(
  params: AlertListParams = {}
): Promise<AlertListResponse> {
  const search = new URLSearchParams();
  if (params.source_id) search.set("source_id", params.source_id);
  if (params.status) search.set("status", params.status);
  if (params.severity) search.set("severity", params.severity);
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.page) search.set("page", params.page.toString());
  if (params.page_size) search.set("page_size", params.page_size.toString());
  const qs = search.toString();
  return fetchAPI<AlertListResponse>(`/api/v1/alerts${qs ? `?${qs}` : ""}`);
}

export async function acknowledgeAlertV1(
  alertId: string,
  acknowledgedBy?: string
): Promise<AlertListItem> {
  const res = await fetch(
    `${API_BASE}/api/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        acknowledgedBy ? { acknowledged_by: acknowledgedBy } : {}
      ),
    }
  );
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to acknowledge: ${res.status}`);
  }
  return res.json();
}

export async function dismissAlert(
  alertId: string,
  dismissedBy?: string
): Promise<AlertListItem> {
  const res = await fetch(
    `${API_BASE}/api/v1/alerts/${encodeURIComponent(alertId)}/dismiss`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dismissedBy ? { dismissed_by: dismissedBy } : {}),
    }
  );
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Failed to dismiss: ${res.status}`);
  }
  return res.json();
}
// ============== Sprint 4: traces (DAG + real-time feed) ==============

/**
 * Single span (DAG node) attached to a trace.
 *
 * The API persists spans as part of the trace row (JSONB) so a
 * single GET returns the full DAG. ``parent_id`` references another
 * span in the same trace, or is ``null`` for root spans.
 */
export interface TraceSpan {
  span_id: string;
  parent_id?: string | null;
  name: string;
  status?: TraceStatus;
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;
  attributes?: Record<string, unknown> | null;
  error_message?: string | null;
}

export type TraceStatus =
  | "ok"
  | "error"
  | "running"
  | "timeout"
  | "cancelled"
  | string;

/** The wire shape for a trace — matches the API's ``TraceResponse``. */
export interface Trace {
  id: string;
  org_id: string;
  trace_id: string;
  workflow_id: string | null;
  name: string;
  source: string | null;
  status: TraceStatus;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  attributes: Record<string, unknown> | null;
  error_message: string | null;
  spans: TraceSpan[];
  created_at: string;
}

export interface TraceListParams {
  workflow_id?: string;
  status?: TraceStatus;
  limit?: number;
  since?: string;
}

export async function getTraces(
  orgId: string,
  params: TraceListParams = {}
): Promise<Trace[]> {
  const search = new URLSearchParams();
  if (params.workflow_id) search.set("workflow_id", params.workflow_id);
  if (params.status) search.set("status", params.status);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.since) search.set("since", params.since);
  const qs = search.toString();
  return fetchAPI<Trace[]>(`/api/orgs/${orgId}/traces${qs ? `?${qs}` : ""}`);
}

export async function getTrace(orgId: string, traceDbId: string): Promise<Trace> {
  return fetchAPI<Trace>(`/api/orgs/${orgId}/traces/${traceDbId}`);
}

/**
 * Server-Sent Events stream of new traces for the org. Returns an
 * ``EventSource`` so the caller can attach listeners. The shape of
 * each message is a ``Trace`` (same as the REST list endpoint).
 */
export function createTraceStream(orgId: string): EventSource {
  return new EventSource(`${API_BASE}/api/orgs/${orgId}/traces/stream`);
}
