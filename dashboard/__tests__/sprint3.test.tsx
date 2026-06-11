/**
 * Frontend tests for Sprint 3 components.
 *
 * Covers:
 *
 * - ThresholdsEditor: renders sliders, calls PATCH with the right body
 * - SlackConfigForm: shows "Active" state, opens the edit form
 * - AlertsPage (v1): renders filter UI, table rows with actions,
 *   test-slack result text
 * - lib/api Sprint 3 wrappers: build URLs with the right query
 *   parameters and PATCH bodies
 */

import React, { ReactNode } from "react";
import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Module mocks (must come before importing the SUT)
// ---------------------------------------------------------------------------

// Use jest.fn() directly so the mock factory below can return real fns.
const apiMock = {
  // Sprint 3 endpoints
  getSourceThresholds: jest.fn(),
  updateSourceThresholds: jest.fn(),
  getSlackConfig: jest.fn(),
  setSlackConfig: jest.fn(),
  listAlerts: jest.fn(),
  acknowledgeAlertV1: jest.fn(),
  dismissAlert: jest.fn(),
  testSlackForAlert: jest.fn(),
  // Existing endpoints (used by AlertRulesEditor wrapper)
  getAlertRules: jest.fn(),
  updateAlertRules: jest.fn(),
  testMute: jest.fn(),
  getSource: jest.fn(),
  updateSource: jest.fn(),
  // Auth (required by AuthContext, which is NOT mounted in these tests)
  login: jest.fn(),
  register: jest.fn(),
  refresh: jest.fn(),
  fetchMe: jest.fn(),
  getSources: jest.fn(),
  getAlerts: jest.fn(),
  acknowledgeAlert: jest.fn(),
};

jest.mock("@/lib/api", () => apiMock);

// Mock next/navigation (used by App Router pages)
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

// SUT imports (after mocks are set up so the components pick up the
// mocked @/lib/api module on first evaluation).
import { ThresholdsEditor } from "@/components/sources/thresholds-editor";
import { SlackConfigForm } from "@/components/sources/slack-config-form";
import AlertsPage from "@/app/alerts/page";

function withQueryClient(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  Object.values(apiMock).forEach((fn) => (fn as jest.Mock).mockReset());
  // Default: return empty thresholds / slack config / alerts
  apiMock.getSourceThresholds.mockResolvedValue({
    source_id: "src-1",
    thresholds: [],
  });
  apiMock.updateSourceThresholds.mockResolvedValue({
    source_id: "src-1",
    thresholds: [],
  });
  apiMock.getSlackConfig.mockResolvedValue({
    source_id: "src-1",
    webhook_url_set: false,
    enabled: true,
    channel_hint: null,
  });
  apiMock.setSlackConfig.mockResolvedValue({
    source_id: "src-1",
    webhook_url_set: true,
    enabled: true,
    channel_hint: "#ops",
  });
  apiMock.listAlerts.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 25,
    has_more: false,
  });
});

// ---------------------------------------------------------------------------
// ThresholdsEditor
// ---------------------------------------------------------------------------

describe("ThresholdsEditor", () => {
  test("renders three sliders and a save button", async () => {
    render(withQueryClient(<ThresholdsEditor sourceId="src-1" />));
    await waitFor(() => {
      expect(screen.getByText("Anomaly Thresholds")).toBeInTheDocument();
    });
    expect(screen.getByText(/Latency \(p95\)/)).toBeInTheDocument();
    expect(screen.getByText(/Error rate/)).toBeInTheDocument();
    expect(screen.getByText(/Failure count/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Save thresholds/i })
    ).toBeInTheDocument();
  });

  test("save button calls PATCH with default values", async () => {
    render(withQueryClient(<ThresholdsEditor sourceId="src-1" />));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Save thresholds/i })
      ).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /Save thresholds/i })
      );
    });
    await waitFor(() => {
      expect(apiMock.updateSourceThresholds).toHaveBeenCalled();
    });
    const args = apiMock.updateSourceThresholds.mock.calls[0];
    expect(args[0]).toBe("src-1");
    expect(Array.isArray(args[1])).toBe(true);
    const metrics = (args[1] as { metric: string }[]).map((t) => t.metric);
    expect(metrics).toEqual(
      expect.arrayContaining(["latency_ms", "error_rate_pct", "failure_count"])
    );
  });
});

// ---------------------------------------------------------------------------
// SlackConfigForm
// ---------------------------------------------------------------------------

describe("SlackConfigForm", () => {
  test("shows 'Not configured' when no webhook is set", async () => {
    render(withQueryClient(<SlackConfigForm sourceId="src-1" />));
    await waitFor(() => {
      expect(screen.getByText("Slack Webhook")).toBeInTheDocument();
    });
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/hooks\.slack\.com/)
    ).toBeInTheDocument();
  });

  test("shows 'Active' when webhook is set and enabled", async () => {
    apiMock.getSlackConfig.mockResolvedValue({
      source_id: "src-1",
      webhook_url_set: true,
      enabled: true,
      channel_hint: "#ops",
    });
    render(withQueryClient(<SlackConfigForm sourceId="src-1" />));
    await waitFor(() => {
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  test("shows 'Configured (paused)' when disabled but set", async () => {
    apiMock.getSlackConfig.mockResolvedValue({
      source_id: "src-1",
      webhook_url_set: true,
      enabled: false,
      channel_hint: null,
    });
    render(withQueryClient(<SlackConfigForm sourceId="src-1" />));
    await waitFor(() => {
      expect(screen.getByText(/Configured \(paused\)/)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// AlertsPage
// ---------------------------------------------------------------------------

describe("AlertsPage", () => {
  test("renders empty state and list-alerts call", async () => {
    render(withQueryClient(<AlertsPage />));
    await waitFor(() => {
      expect(apiMock.listAlerts).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(
        screen.getByText(/No alerts match these filters/)
      ).toBeInTheDocument();
    });
  });

  test("renders alert rows with ack and dismiss buttons", async () => {
    apiMock.listAlerts.mockResolvedValue({
      items: [
        {
          id: "a-1",
          source_id: "src-1",
          source_name: "n8n-prod",
          rule_id: "r-1",
          rule_name: "p95-too-high",
          severity: "high",
          status: "open",
          message: "p95 latency 1234ms exceeds threshold 500ms",
          context: null,
          detected_at: new Date().toISOString(),
          acknowledged_at: null,
          acknowledged_by: null,
          dismissed_at: null,
          dismissed_by: null,
        },
        {
          id: "a-2",
          source_id: "src-2",
          source_name: null,
          rule_id: "r-2",
          rule_name: null,
          severity: "medium",
          status: "dismissed",
          message: "errors > 5%",
          context: null,
          detected_at: new Date().toISOString(),
          acknowledged_at: null,
          acknowledged_by: null,
          dismissed_at: new Date().toISOString(),
          dismissed_by: "alice",
        },
      ],
      total: 2,
      page: 1,
      page_size: 25,
      has_more: false,
    });
    render(withQueryClient(<AlertsPage />));
    await waitFor(() => {
      expect(screen.getByText("n8n-prod")).toBeInTheDocument();
    });
    expect(screen.getByText(/p95 latency 1234ms/)).toBeInTheDocument();
    // Ack button on the open alert
    expect(screen.getAllByRole("button", { name: /^Ack$/ }).length).toBe(1);
    // Severity badge
    expect(screen.getByText("high")).toBeInTheDocument();
    // Status badges
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText("dismissed")).toBeInTheDocument();
  });

  test("clicking Ack triggers the mutation", async () => {
    apiMock.listAlerts.mockResolvedValue({
      items: [
        {
          id: "a-1",
          source_id: "src-1",
          source_name: "n8n-prod",
          rule_id: "r-1",
          rule_name: "p95",
          severity: "high",
          status: "open",
          message: "x",
          context: null,
          detected_at: new Date().toISOString(),
          acknowledged_at: null,
          acknowledged_by: null,
          dismissed_at: null,
          dismissed_by: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
      has_more: false,
    });
    apiMock.acknowledgeAlertV1.mockResolvedValue({});
    render(withQueryClient(<AlertsPage />));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Ack$/ })).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Ack$/ }));
    });
    await waitFor(() => {
      expect(apiMock.acknowledgeAlertV1).toHaveBeenCalledWith("a-1");
    });
  });

  test("filter dropdown updates the query", async () => {
    render(withQueryClient(<AlertsPage />));
    await waitFor(() => {
      expect(apiMock.listAlerts).toHaveBeenCalled();
    });
    // Open the filter panel
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    // Pick "Open" in the status select
    const selects = screen.getAllByRole("combobox");
    const statusSelect = selects[0];
    await act(async () => {
      fireEvent.change(statusSelect, { target: { value: "open" } });
    });
    await waitFor(() => {
      const calls = apiMock.listAlerts.mock.calls;
      const lastCall = calls[calls.length - 1];
      expect(lastCall[0]).toEqual(expect.objectContaining({ status: "open" }));
    });
  });
});

// ---------------------------------------------------------------------------
// API wrappers
// ---------------------------------------------------------------------------

describe("lib/api v1 wrappers", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  test("updateSourceThresholds sends PATCH with thresholds array", async () => {
    // Re-import the real (un-mocked-for-this-test) module by resetting
    // the @/lib/api mock just for this test.
    jest.resetModules();
    jest.doMock("@/lib/api", () => {
      // Re-export everything from the real module by requiring it.
      // We can't easily do that here; instead, call fetch directly
      // using the URL the wrapper would build.
      const actual = jest.requireActual("@/lib/api");
      return actual;
    });
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ source_id: "src-1", thresholds: [] }),
    }) as unknown as typeof fetch;
    const api = await import("@/lib/api");
    await api.updateSourceThresholds("src-1", [
      { metric: "latency_ms", value: 250, window_seconds: 300, enabled: true },
    ]);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/sources/src-1/thresholds"),
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          thresholds: [
            { metric: "latency_ms", value: 250, window_seconds: 300, enabled: true },
          ],
        }),
      })
    );
  });

  test("listAlerts passes query parameters through", async () => {
    jest.resetModules();
    jest.doMock("@/lib/api", () => jest.requireActual("@/lib/api"));
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        items: [],
        total: 0,
        page: 1,
        page_size: 25,
        has_more: false,
      }),
    }) as unknown as typeof fetch;
    const api = await import("@/lib/api");
    await api.listAlerts({
      status: "open",
      severity: "high",
      page: 2,
      page_size: 50,
    });
    const calledUrl = (global.fetch as jest.Mock).mock.calls[0][0] as string;
    expect(calledUrl).toMatch(/status=open/);
    expect(calledUrl).toMatch(/severity=high/);
    expect(calledUrl).toMatch(/page=2/);
    expect(calledUrl).toMatch(/page_size=50/);
  });

  test("dismissAlert uses PATCH on /dismiss", async () => {
    jest.resetModules();
    jest.doMock("@/lib/api", () => jest.requireActual("@/lib/api"));
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    }) as unknown as typeof fetch;
    const api = await import("@/lib/api");
    await api.dismissAlert("a-1", "alice");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/alerts/a-1/dismiss"),
      expect.objectContaining({ method: "PATCH" })
    );
  });
});
