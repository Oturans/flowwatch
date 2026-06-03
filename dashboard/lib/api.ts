const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(endpoint: string): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    cache: "no-store",
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