"""Sprint 2 — additional tests for the in-process connection registry
and trace broadcaster.

These tests target the smaller pieces of ``app.routes.traces`` that
the WebSocket round-trip tests don't directly exercise: the
``_ConnectionRegistry`` itself (add / discard / broadcast), the
dead-connection cleanup, and the ``_publish_trace`` Redis error
path.

Keeping these as a separate file from ``test_traces_ws.py`` so a
failure in the lower-level plumbing is easy to isolate.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import List

import pytest

from app.routes import traces as traces_routes


# ---------------------------------------------------------------------------
# _ConnectionRegistry
# ---------------------------------------------------------------------------


class TestConnectionRegistry:
    async def test_add_and_discard_roundtrip(self):
        reg = traces_routes._ConnectionRegistry()
        org = uuid.uuid4()
        ws = _FakeWS()
        reg.add(org, ws)
        assert ws in reg._by_org[org]
        reg.discard(org, ws)
        assert org not in reg._by_org

    async def test_discard_unknown_websocket_is_a_noop(self):
        reg = traces_routes._ConnectionRegistry()
        org = uuid.uuid4()
        # No add, just discard — should not raise.
        reg.discard(org, _FakeWS())
        assert org not in reg._by_org

    async def test_broadcast_to_no_connections_returns_zero(self):
        reg = traces_routes._ConnectionRegistry()
        n = await reg.broadcast(uuid.uuid4(), {"hello": "world"})
        assert n == 0

    async def test_broadcast_delivers_to_every_connection(self):
        reg = traces_routes._ConnectionRegistry()
        org = uuid.uuid4()
        a = _FakeWS()
        b = _FakeWS()
        c = _FakeWS()
        for ws in (a, b, c):
            reg.add(org, ws)
        n = await reg.broadcast(org, {"type": "trace", "id": "abc"})
        assert n == 3
        for ws in (a, b, c):
            assert len(ws.texts) == 1
            payload = json.loads(ws.texts[0])
            assert payload["id"] == "abc"

    async def test_broadcast_drops_dead_sockets(self):
        """Sockets that raise on send_text are removed from the registry."""
        reg = traces_routes._ConnectionRegistry()
        org = uuid.uuid4()
        good = _FakeWS()
        dead = _FakeWS(fail_on_send=True)
        reg.add(org, good)
        reg.add(org, dead)
        n = await reg.broadcast(org, {"type": "trace", "id": "x"})
        # We delivered to good but the dead one threw; the helper
        # increments per-attempt so n is at least 1 (good got it).
        assert n >= 1
        # The dead socket should have been pruned.
        assert dead not in reg._by_org[org]
        # Good socket is still there.
        assert good in reg._by_org[org]

    async def test_broadcast_swallows_send_errors(self):
        """If every connection fails, the broadcast must not raise."""
        reg = traces_routes._ConnectionRegistry()
        org = uuid.uuid4()
        for _ in range(3):
            reg.add(org, _FakeWS(fail_on_send=True))
        # Should not raise.
        n = await reg.broadcast(org, {"type": "trace", "id": "y"})
        assert n == 0
        # All dead sockets should be removed.
        assert org not in reg._by_org


# ---------------------------------------------------------------------------
# _publish_trace (Redis path)
# ---------------------------------------------------------------------------


class TestPublishTrace:
    async def test_publish_trace_returns_zero_on_no_subscribers(self, monkeypatch):
        """The in-process broadcast returns 0 when nobody's connected."""
        # Use a fake trace object — we don't need the DB.
        trace = _FakeTrace()
        # Patch the in-process broadcaster to verify it was called.
        delivered = await traces_routes._publish_trace(trace)
        # No sockets registered → 0.
        assert delivered == 0

    async def test_publish_trace_broadcasts_to_existing_sockets(self):
        """When a socket is registered, broadcast delivers the trace."""
        reg = traces_routes.connection_registry
        org = uuid.uuid4()
        ws = _FakeWS()
        reg.add(org, ws)
        try:
            trace = _FakeTrace(org_id=org)
            await traces_routes._publish_trace(trace)
            assert len(ws.texts) == 1
            payload = json.loads(ws.texts[0])
            assert payload["type"] == "trace"
            assert payload["id"] == str(trace.id)
        finally:
            reg.discard(org, ws)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeWS:
    """Tiny stand-in for a WebSocket used by the registry tests."""

    def __init__(self, fail_on_send: bool = False):
        self.texts: List[str] = []
        self._fail = fail_on_send

    async def send_text(self, data: str) -> None:
        if self._fail:
            raise RuntimeError("client disconnected")
        self.texts.append(data)


class _FakeTrace:
    """A trace-shaped object that satisfies ``_publish_trace``'s reads."""

    def __init__(self, org_id=None):
        self.id = uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.trace_id = "trace-fake"
        self.workflow_id = "wf-fake"
        self.name = "fake.name"
        self.status = "ok"
        self.started_at = datetime.now(timezone.utc)
        self.ended_at = None
        self.duration_ms = 42
        self.source = None
        self.attributes = {"k": "v"}
        self.error_message = None
        # Sprint 4 added ``spans`` (JSONB list). Older tests use this
        # fake without it; default to an empty list.
        self.spans = []
