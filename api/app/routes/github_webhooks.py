"""
GitHub-specific webhook endpoint.

POST /webhooks/github
---------------------
Accepts GitHub Actions / GitHub Apps webhook payloads (no platform-agnostic
source id). The repository ``owner/repo`` is mapped to a source via the
``X-Hub-Signature-256`` header (HMAC-SHA256) and a configured GitHub App
secret.

Payload contract (subset of GitHub's ``workflow_run`` event):
    {
        "action": "completed",
        "workflow_run": {
            "id": 1234567890,
            "name": "CI",
            "head_branch": "main",
            "conclusion": "success" | "failure" | "cancelled" | ...,
            "run_started_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:05:00Z"
        },
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "username"}
    }

The endpoint:
    1. Verifies the ``X-Hub-Signature-256`` HMAC against the source's
       ``signing_secret`` (which stores the GitHub webhook secret).
    2. Translates the GitHub payload to a normalised FlowWatch event.
    3. Stores the event and dispatches the same processing pipeline as
       the platform-agnostic ``/api/webhook/{source_id}`` endpoint.
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import WebhookSource

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["github-webhook"])

# Map GitHub "conclusion" values to FlowWatch's normalised statuses.
_GITHUB_STATUS_MAP = {
    "success": "success",
    "failure": "error",
    "cancelled": "cancelled",
    "timed_out": "timeout",
    "startup_failure": "error",
    "neutral": "running",
}


def _verify_github_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Verify ``X-Hub-Signature-256`` header (sha256=<hex>)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    provided = signature_header.split("=", 1)[1]
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided, expected)


def _normalise_github_event(payload: dict) -> dict:
    """Convert a GitHub ``workflow_run`` payload to FlowWatch event fields."""
    workflow_run = payload.get("workflow_run") or {}

    conclusion = workflow_run.get("conclusion") or "unknown"
    status = _GITHUB_STATUS_MAP.get(conclusion, "unknown")

    # workflow_id: prefer workflow_run.id (string), fall back to name
    workflow_id = str(workflow_run.get("id") or workflow_run.get("name") or "unknown")
    run_id = workflow_run.get("run_number")
    run_id = str(run_id) if run_id is not None else None

    error_message: Optional[str] = None
    if status == "error":
        # GitHub doesn't put a free-form error in the webhook; we record the
        # conclusion as the human-readable error.
        error_message = f"GitHub Actions run concluded with: {conclusion}"

    duration_ms: Optional[int] = None
    started = workflow_run.get("run_started_at")
    updated = workflow_run.get("updated_at")
    if started and updated:
        try:
            s = datetime.fromisoformat(started.replace("Z", "+00:00"))
            u = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            duration_ms = int((u - s).total_seconds() * 1000)
        except (ValueError, AttributeError):
            duration_ms = None

    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "event_type": "workflow_run",
        "status": status,
        "payload": payload,
        "error_message": error_message,
        "duration_ms": duration_ms,
    }


async def _find_github_source(repository_full_name: str) -> WebhookSource:
    """Find the source whose ``alert_config.github_repo`` matches."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(WebhookSource).where(
                WebhookSource.platform == "github",
                WebhookSource.is_active.is_(True),
            )
        )
        candidates = result.scalars().all()

    for src in candidates:
        repo = (src.alert_config or {}).get("github_repo")
        if repo == repository_full_name:
            return src

    raise HTTPException(
        status_code=404,
        detail=f"No active source registered for repo '{repository_full_name}'",
    )


@router.post("/github")
async def ingest_github_webhook(request: Request, response: Response):
    """
    Ingest a GitHub webhook (workflow_run events).

    Returns 200 on success (even for ignored events), 401 on signature
    failure, 404 if no source is configured for the repository, 400 on
    malformed payloads.
    """
    body = await request.body()
    headers = dict(request.headers)

    # 1. Parse the JSON early so we can identify the repo for key lookup.
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    repo = (payload.get("repository") or {}).get("full_name")
    if not repo:
        raise HTTPException(
            status_code=400, detail="Missing repository.full_name in payload"
        )

    # 2. Look up the source for this repo.
    source = await _find_github_source(repo)

    # 3. Verify GitHub signature.
    sig_header = headers.get("x-hub-signature-256", "")
    if not _verify_github_signature(body, sig_header, source.signing_secret):
        raise HTTPException(
            status_code=401, detail="Invalid GitHub signature"
        )

    # 4. Translate to normalised event.
    event_data = _normalise_github_event(payload)

    # 5. Build the full event envelope (mirrors platform-agnostic path).
    event_id = str(uuid.uuid4())
    event = {
        "id": event_id,
        "source_id": source.id,
        "received_at": datetime.utcnow().isoformat(),
        **event_data,
    }

    # 6. Dispatch Celery task for persistence.
    from app.tasks.tasks import process_event

    try:
        process_event.delay(event)
    except Exception as exc:  # pragma: no cover - broker outage
        logger.exception("Failed to enqueue process_event: %s", exc)
        # We still return 200 because the webhook must be idempotent
        # (research gotcha #7). The event is lost, but we don't make
        # GitHub retry forever.
        return {"status": "accepted", "warning": "queue_unavailable"}

    return {"status": "accepted", "event_id": event_id, "source_id": source.id}


@router.get("/github/health")
async def github_webhook_health():
    """Health check for the GitHub webhook endpoint."""
    return {"status": "healthy", "endpoint": "/webhooks/github"}
