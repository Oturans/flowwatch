"use client";

/**
 * Sprint 4 — real-time trace feed hook.
 *
 * Subscribes to the org's SSE trace stream and pushes new traces
 * into a callback. The hook is intentionally tiny: the page that
 * uses it owns the buffer (kept in React Query state) so we can
 * re-use the existing invalidation machinery.
 *
 * Lifecycle:
 *  - on mount: opens an EventSource
 *  - on message: parses JSON, validates the basic shape, calls
 *    onTrace with the decoded object
 *  - on unmount: closes the EventSource
 *
 * The hook does NOT auto-reconnect (EventSource already does), but
 * it DOES survive an org_id change by tearing down the old source
 * and opening a fresh one.
 */

import { useEffect } from "react";
import { createTraceStream, type Trace } from "@/lib/api";

export function isTracePayload(value: unknown): value is Trace {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  // We don't require every field (the server is allowed to omit
  // optional ones), but the id + status must be present.
  return typeof v.id === "string" && typeof v.status === "string";
}

export function useTraceStream(
  orgId: string | null,
  onTrace: (trace: Trace) => void,
  options: { enabled?: boolean } = {}
) {
  const { enabled = true } = options;

  useEffect(() => {
    if (!orgId || !enabled) return;
    const source = createTraceStream(orgId);

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (isTracePayload(data)) {
          onTrace(data);
        }
      } catch {
        // Ignore non-JSON / malformed messages.
      }
    };

    source.onerror = () => {
      // EventSource auto-reconnects; we don't need to do anything.
    };

    return () => {
      source.close();
    };
  }, [orgId, enabled, onTrace]);
}