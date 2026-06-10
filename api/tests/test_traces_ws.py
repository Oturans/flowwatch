"""Sprint 2: WebSocket trace ingestion tests.

Strategy: exercise the WebSocket route *function* directly with a
fake ``WebSocket`` object. The route is a plain coroutine that
calls ``websocket.accept()`` and ``websocket.send_json()`` etc. —
we can stub all of those and assert the call sequence.

The reason we don't use ``starlette.testclient.TestClient`` is
that it spins up its own anyio portal / event loop in a
background thread, which collides with the conftest's
``async_engine`` (already bound to pytest-asyncio's loop). The
direct-call strategy is loop-agnostic and faster.

Covers:

* Auth: missing token, bad token, wrong-org token, inactive user.
* Happy path: send a valid trace payload, expect an ``ack`` with
  the persisted id; the row shows up in the DB.
* Validation: malformed JSON, missing required fields, bad status.
* Keep-alive: ``ping`` -> ``pong``.
* Multi-tenant isolation: a user from a different org cannot
  push to this org's socket.
* In-process broadcast: a second connected socket receives
  traces pushed by the first.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.auth import create_access_token
from app.database import AsyncSessionLocal
from app.models import Trace


# ---------------------------------------------------------------------------
# Fake WebSocket
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """A minimal WebSocket stand-in.

    Records every ``send_*`` call so the test can assert the
    server's response. ``receive_text`` is fed from a queue that
    the test populates.
    """

    def __init__(self, query_params: Optional[dict] = None):
        self.query_params = query_params or {}
        self.accepted = False
        self.sent: list[Any] = []
        self.sent_text: list[str] = []
        self.closed: bool = False
        self.close_code: Optional[int] = None
        self.close_reason: Optional[str] = None
        self._inbox: asyncio.Queue[str] = asyncio.Queue()
        self.client_state = "connected"  # stub: never disconnect

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def send_json(self, data) -> None:
        self.sent.append(data)
        self.sent_text.append(json.dumps(data, default=str))

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def receive_text(self) -> str:
        return await self._inbox.get()

    def push(self, text: str) -> None:
        """Test helper: enqueue a message for the route to read."""
        self._inbox.put_nowait(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_task(coro):
    """Await a coroutine on the *current* event loop (the one pytest-asyncio
    is running this test on) but with a short cancellation safety net
    so a hang doesn't block the suite. Mostly a no-op; the real value
    is a stable name to read in stack traces.
    """
    return coro


async def _drive(handler, ws: FakeWebSocket, max_steps: int = 4) -> None:
    """Run the WebSocket handler with a small budget.

    The handler is a long-lived coroutine that loops on
    ``receive_text()``; we let it process ``max_steps`` messages
    and then cancel it.
    """
    task = asyncio.create_task(handler(ws))
    try:
        # Give the handler a beat to process the inbox up to
        # ``max_steps`` times. After that we cancel and let it
        # clean up.
        for _ in range(max_steps):
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
            except asyncio.TimeoutError:
                # No more messages ready; let the test decide whether
                # to push more or finish.
                break
            except asyncio.CancelledError:
                break
            except Exception:
                # The handler may raise WebSocketDisconnect on close;
                # swallow and let the test assert on the WS state.
                break
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


async def _insert_user(tenant, email: str = "ws@example.com", is_active: bool = True):
    from app.core.auth import hash_password
    from app.models import User
    async with AsyncSessionLocal() as session:
        u = User(
            email=email.lower(),
            hashed_password=hash_password("hunter2hunter2"),
            org_id=tenant.id,
            role="admin",
            is_active=is_active,
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
    return u


async def _read_traces(org_id) -> list[Trace]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trace).where(Trace.org_id == org_id))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ws_missing_token_closes_socket(tenant_factory):
    from app.routes.traces import traces_ws

    tenant = await tenant_factory(name="WS MissingToken")
    ws = FakeWebSocket(query_params={})  # no token
    await traces_ws(ws, tenant.id)
    assert ws.accepted is True
    assert ws.closed is True
    assert ws.close_reason and "token" in ws.close_reason.lower()


async def test_ws_bad_token_closes_socket(tenant_factory):
    from app.routes.traces import traces_ws

    tenant = await tenant_factory(name="WS BadToken")
    ws = FakeWebSocket(query_params={"token": "not-a-real-jwt"})
    await traces_ws(ws, tenant.id)
    assert ws.closed is True
    assert "auth failed" in (ws.close_reason or "").lower()


async def test_ws_wrong_org_token_closes_socket(tenant_factory, user_factory):
    from app.routes.traces import traces_ws

    t1 = await tenant_factory(name="WS A")
    t2 = await tenant_factory(name="WS B")
    user = await user_factory(t1, email="xor@example.com")
    token = create_access_token(user.id, t1.id)
    ws = FakeWebSocket(query_params={"token": token})
    await traces_ws(ws, t2.id)  # token says t1, URL says t2
    assert ws.closed is True
    assert "org_id" in (ws.close_reason or "").lower()


async def test_ws_inactive_user_closes_socket(tenant_factory):
    from app.routes.traces import traces_ws

    tenant = await tenant_factory(name="WS Inactive")
    user = await _insert_user(tenant, email="inactive@example.com", is_active=False)
    token = create_access_token(user.id, tenant.id)
    ws = FakeWebSocket(query_params={"token": token})
    await traces_ws(ws, tenant.id)
    assert ws.closed is True


async def test_ws_valid_trace_persists_and_acks(tenant_factory, user_factory):
    from app.routes.traces import connection_registry, traces_ws

    tenant = await tenant_factory(name="WS Valid")
    user = await user_factory(tenant, email="valid@example.com")
    token = create_access_token(user.id, tenant.id)
    ws = FakeWebSocket(query_params={"token": token})

    payload = {
        "trace_id": "trace-abc-123",
        "name": "llm.completion",
        "workflow_id": "wf-1",
        "status": "ok",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 250,
        "attributes": {"model": "gpt-4", "tokens": 1234},
    }

    # Start the handler, push 2 messages, then cancel.
    handler = traces_ws(ws, tenant.id)
    task = asyncio.create_task(handler)
    try:
        # Wait for the "ready" frame
        for _ in range(50):
            if ws.sent:
                break
            await asyncio.sleep(0.01)
        assert any(m.get("type") == "ready" for m in ws.sent)

        ws.push(json.dumps(payload))
        ws.push(json.dumps({"type": "ping"}))

        for _ in range(50):
            ack_msgs = [m for m in ws.sent if m.get("type") == "ack"]
            pong_msgs = [m for m in ws.sent if m.get("type") == "pong"]
            if ack_msgs and pong_msgs:
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        connection_registry.discard(tenant.id, ws)

    # Assertions
    ack_msgs = [m for m in ws.sent if m.get("type") == "ack"]
    pong_msgs = [m for m in ws.sent if m.get("type") == "pong"]
    assert len(ack_msgs) == 1, f"expected 1 ack, got {ack_msgs}"
    assert uuid.UUID(ack_msgs[0]["id"])
    assert len(pong_msgs) == 1

    # Verify the trace landed in the DB
    rows = await _read_traces(tenant.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.trace_id == "trace-abc-123"
    assert row.name == "llm.completion"
    assert row.status == "ok"
    assert row.workflow_id == "wf-1"
    assert row.attributes == {"model": "gpt-4", "tokens": 1234}
    assert row.duration_ms == 250


async def test_ws_invalid_json_returns_error_not_closes(tenant_factory, user_factory):
    from app.routes.traces import connection_registry, traces_ws

    tenant = await tenant_factory(name="WS BadJson")
    user = await user_factory(tenant, email="badjson@example.com")
    token = create_access_token(user.id, tenant.id)
    ws = FakeWebSocket(query_params={"token": token})

    task = asyncio.create_task(traces_ws(ws, tenant.id))
    try:
        for _ in range(50):
            if ws.sent:
                break
            await asyncio.sleep(0.01)

        ws.push("{not json")
        ws.push(json.dumps({"type": "ping"}))

        for _ in range(50):
            err = [m for m in ws.sent if m.get("type") == "error"]
            pong = [m for m in ws.sent if m.get("type") == "pong"]
            if err and pong:
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        connection_registry.discard(tenant.id, ws)

    errs = [m for m in ws.sent if m.get("type") == "error"]
    pongs = [m for m in ws.sent if m.get("type") == "pong"]
    assert len(errs) == 1
    assert "JSON" in errs[0]["message"]
    assert len(pongs) == 1  # connection still open
    assert ws.closed is False


async def test_ws_missing_required_fields_returns_error(tenant_factory, user_factory):
    from app.routes.traces import connection_registry, traces_ws

    tenant = await tenant_factory(name="WS Missing")
    user = await user_factory(tenant, email="missing@example.com")
    token = create_access_token(user.id, tenant.id)
    ws = FakeWebSocket(query_params={"token": token})

    task = asyncio.create_task(traces_ws(ws, tenant.id))
    try:
        for _ in range(50):
            if ws.sent:
                break
            await asyncio.sleep(0.01)
        ws.push(json.dumps({"status": "ok"}))  # missing required fields
        for _ in range(50):
            if any(m.get("type") == "error" for m in ws.sent):
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        connection_registry.discard(tenant.id, ws)

    errs = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errs) == 1
    # No ack must have been emitted
    assert not any(m.get("type") == "ack" for m in ws.sent)


async def test_ws_invalid_status_value_returns_error(tenant_factory, user_factory):
    from app.routes.traces import connection_registry, traces_ws

    tenant = await tenant_factory(name="WS BadStatus")
    user = await user_factory(tenant, email="badstatus@example.com")
    token = create_access_token(user.id, tenant.id)
    ws = FakeWebSocket(query_params={"token": token})

    task = asyncio.create_task(traces_ws(ws, tenant.id))
    try:
        for _ in range(50):
            if ws.sent:
                break
            await asyncio.sleep(0.01)
        ws.push(json.dumps({
            "trace_id": "x",
            "name": "thing",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "EXPLODED",
        }))
        for _ in range(50):
            if any(m.get("type") == "error" for m in ws.sent):
                break
            await asyncio.sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        connection_registry.discard(tenant.id, ws)

    errs = [m for m in ws.sent if m.get("type") == "error"]
    assert len(errs) == 1
    assert not any(m.get("type") == "ack" for m in ws.sent)


async def test_ws_broadcasts_to_other_sockets_in_same_org(tenant_factory, user_factory):
    """A second connected socket in the same org receives a trace
    pushed by the first socket via the in-process registry."""
    from app.routes.traces import connection_registry, traces_ws

    tenant = await tenant_factory(name="WS Broadcast")
    user = await user_factory(tenant, email="bcast@example.com")
    token = create_access_token(user.id, tenant.id)

    sender = FakeWebSocket(query_params={"token": token})
    observer = FakeWebSocket(query_params={"token": token})
    # Register the observer BEFORE the sender publishes (broadcast
    # only reaches currently-registered sockets).
    connection_registry.add(tenant.id, observer)

    sender_task = asyncio.create_task(traces_ws(sender, tenant.id))
    observer_task = asyncio.create_task(traces_ws(observer, tenant.id))
    try:
        # Wait for both to emit their "ready" frame
        for _ in range(50):
            if any(m.get("type") == "ready" for m in sender.sent) and any(
                m.get("type") == "ready" for m in observer.sent
            ):
                break
            await asyncio.sleep(0.01)

        payload = {
            "trace_id": "broadcast-1",
            "name": "thing",
            "status": "ok",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        sender.push(json.dumps(payload))

        # Wait for observer to receive the broadcast
        for _ in range(50):
            if any(m.get("type") == "trace" for m in observer.sent):
                break
            await asyncio.sleep(0.02)
    finally:
        for t in (sender_task, observer_task):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        connection_registry.discard(tenant.id, sender)
        connection_registry.discard(tenant.id, observer)

    traces_for_observer = [
        json.loads(m) for m in observer.sent_text
        if m.startswith("{") and '"type": "trace"' in m
    ]
    assert len(traces_for_observer) == 1
    assert traces_for_observer[0]["trace_id"] == "broadcast-1"
    assert traces_for_observer[0]["name"] == "thing"
