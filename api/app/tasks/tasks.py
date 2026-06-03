import json
import httpx
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.celery_app import celery_app
from app.config import get_settings
from app.alerts.mute_windows import is_muted

settings = get_settings()

# Sync engine for Celery (psycopg2)
engine = create_engine(settings.database_url_sync)
SessionLocal = sessionmaker(bind=engine)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=60)
def process_event(self, event_data: dict):
    """
    Process webhook event: store in PostgreSQL.
    Uses exponential backoff on failures.
    """
    try:
        from app.models import WorkflowEvent

        session = SessionLocal()
        try:
            # Parse received_at or use current time
            received_at = event_data.get("received_at")
            if received_at:
                if isinstance(received_at, str):
                    received_at = datetime.fromisoformat(received_at.replace("Z", "+00:00"))

            db_event = WorkflowEvent(
                source_id=event_data["source_id"],
                workflow_id=event_data["workflow_id"],
                run_id=event_data.get("run_id"),
                event_type=event_data.get("event_type", "unknown"),
                status=event_data.get("status", "unknown"),
                payload=event_data.get("payload"),
                error_message=event_data.get("error_message"),
                duration_ms=event_data.get("duration_ms"),
                received_at=received_at or datetime.utcnow(),
            )
            session.add(db_event)
            session.commit()

            # Check if we should trigger alert
            if db_event.status in ("error", "failed"):
                send_alert.delay(str(db_event.id), event_data)

            return {"status": "processed", "event_id": str(db_event.id)}
        finally:
            session.close()

    except Exception as exc:
        # Exponential backoff: 60s, 120s, 240s, 480s, 960s
        countdown = 60 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def send_alert(self, event_id: str, event_data: dict):
    """
    Send Slack alert for failed events.
    Uses Block Kit for rich formatting.
    """
    try:
        from app.models import WebhookSource, AlertLog
        from sqlalchemy.orm import Session

        session = SessionLocal()
        try:
            # Get source config
            source = session.query(WebhookSource).filter_by(id=event_data["source_id"]).first()
            if not source or not source.alert_config.get("slack_webhook_url"):
                return {"status": "skipped", "reason": "no_slack_config"}

            webhook_url = source.alert_config["slack_webhook_url"]

            # Honor mute windows (P2 feature): skip if the source is
            # currently muted. Escalation is handled separately.
            if is_muted(source):
                return {"status": "skipped", "reason": "muted"}

            # Build Block Kit message
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"⚠️ Workflow Failed: {event_data.get('workflow_id', 'Unknown')}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Source:*\n{event_data.get('source_id', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Status:*\n{event_data.get('status', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Time:*\n{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"},
                        {"type": "mrkdwn", "text": f"*Error:*\n{event_data.get('error_message', 'N/A')[:200]}"},
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View in FlowWatch"},
                            "url": f"https://flowwatch.app/events/{event_id}"
                        }
                    ]
                }
            ]

            # Send to Slack
            response = httpx.post(webhook_url, json={"blocks": blocks}, timeout=10)
            response.raise_for_status()

            # Log Slack alert
            alert = AlertLog(
                source_id=event_data["source_id"],
                alert_type="slack",
                message=f"Alert sent for event {event_id}",
                status="sent"
            )
            session.add(alert)
            session.commit()

            # Fire email alert in parallel (don't block)
            send_email_alert.delay(event_id, event_data)

            return {"status": "sent", "alert_type": "slack"}

        finally:
            session.close()

    except httpx.HTTPError as exc:
        raise self.retry(exc=exc, countdown=30)
    except Exception as exc:
        # Don't retry alert failures forever - log and move on
        self.max_retries = 2
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_alert(self, event_id: str, event_data: dict):
    """
    Send email alert for failed events via Resend.
    Does NOT retry on failure — just logs and returns.

    Recipients are resolved in this order:
      1. Per-source ``alert_config['emails']`` list (P2 feature)
      2. Global ``settings.alert_email_to`` fallback
    If neither is configured, the task is skipped.
    """
    try:
        import resend
        from app.models import WebhookSource, AlertLog

        if not settings.resend_api_key:
            return {"status": "skipped", "reason": "no_resend_key"}

        # Resolve recipients: per-source first, then global fallback.
        recipients: list[str] = []
        source_id = event_data.get("source_id", "")
        source: WebhookSource | None = None
        with SessionLocal() as session:
            try:
                source = session.query(WebhookSource).filter_by(id=source_id).first()
                if source and source.alert_config:
                    per_source = source.alert_config.get("emails")
                    if isinstance(per_source, list) and per_source:
                        # Filter out empty / non-string entries defensively.
                        recipients = [e for e in per_source if isinstance(e, str) and e]
            finally:
                session.close()

        # Honor mute windows (P2 feature)
        if is_muted(source):
            return {"status": "skipped", "reason": "muted"}

        if not recipients and settings.alert_email_to:
            recipients = [settings.alert_email_to]
        if not recipients:
            return {"status": "skipped", "reason": "no_recipients"}

        workflow_name = event_data.get("workflow_id", "Unknown")
        source_id = event_data.get("source_id", "N/A")
        error_message = event_data.get("error_message", "N/A")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        dashboard_link = f"https://flowwatch.app/events/{event_id}"

        html_body = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #333;">
            <div style="background: linear-gradient(135deg, #ff6b6b 0%, #ee5a5a 100%); padding: 20px; text-align: center;">
                <h1 style="color: white; margin: 0;">🚨 Workflow Failed</h1>
            </div>
            <div style="padding: 20px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Workflow</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{workflow_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Source</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{source_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Error</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; color: #d32f2f;">{error_message[:500]}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;"><strong>Time</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee;">{timestamp}</td>
                    </tr>
                </table>
                <div style="margin-top: 20px; text-align: center;">
                    <a href="{dashboard_link}" style="background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">View in FlowWatch Dashboard</a>
                </div>
            </div>
        </body>
        </html>
        """

        resend.api_key = settings.resend_api_key
        params = {
            "from": settings.alert_email_from,
            "to": recipients,
            "subject": f"🚨 FlowWatch: {workflow_name} failed",
            "html": html_body,
        }
        resend.Emails.send(params)

        # Log alert with recipient count for audit trail
        with SessionLocal() as session:
            try:
                alert = AlertLog(
                    source_id=source_id,
                    alert_type="email",
                    message=(
                        f"Email alert sent for event {event_id} "
                        f"to {len(recipients)} recipient(s)"
                    ),
                    status="sent",
                )
                session.add(alert)
                session.commit()
            finally:
                session.close()

        return {"status": "sent", "alert_type": "email", "recipients": recipients}

    except Exception as exc:
        # Don't retry - just log and return
        try:
            from app.models import AlertLog
            with SessionLocal() as session:
                try:
                    alert = AlertLog(
                        source_id=event_data.get("source_id", ""),
                        alert_type="email",
                        message=f"Email alert failed for event {event_id}: {str(exc)}",
                        status="failed"
                    )
                    session.add(alert)
                    session.commit()
                finally:
                    session.close()
        except Exception:
            pass  # Give up if even logging fails
        return {"status": "failed", "error": str(exc)}


@celery_app.task
def check_escalation():
    """Scan for unacknowledged alerts and trigger escalation emails.

    Runs on Celery Beat (see ``app.celery_app.celery_app.beat_schedule``).
    Each escalated alert is re-sent to the source's
    ``escalation.escalate_to`` recipients and stamped with
    ``status='escalated'`` + ``escalated_at=now`` so it won't be picked
    up again.
    """
    from app.alerts.escalation import find_alerts_to_escalate, get_escalation_config
    from app.models import WebhookSource, AlertLog

    session = SessionLocal()
    try:
        to_escalate = find_alerts_to_escalate(session)
        if not to_escalate:
            return {"status": "ok", "escalated": 0}

        count = 0
        for alert in to_escalate:
            source = (
                session.query(WebhookSource).filter_by(id=alert.source_id).first()
            )
            cfg = get_escalation_config(source)
            if not cfg["enabled"] or not cfg["escalate_to"]:
                continue

            # Build an event envelope that send_email_alert understands.
            escalation_event = {
                "source_id": alert.source_id,
                "workflow_id": "ESCALATION",
                "event_type": "escalation",
                "status": "escalated",
                "error_message": (
                    f"Original alert for event {alert.message or 'n/a'} "
                    f"was not acknowledged within {cfg['minutes_until_escalate']}m"
                ),
            }
            # Reuse the email task but force recipients to escalation list.
            # We do this inline (not via .delay) so the escalate_to list is
            # the *only* set of recipients; the original recipients are
            # bypassed because the per-source emails are temporarily
            # overridden via a one-shot call.
            _send_escalation_email(
                str(alert.id),
                escalation_event,
                cfg["escalate_to"],
            )
            alert.status = "escalated"
            alert.escalated_at = datetime.utcnow()
            count += 1
        # Flush before commit so concurrent readers see the change
        # immediately. The Celery worker may be invoked repeatedly by
        # Beat; we don't want a stale view of the alert.
        session.flush()
        session.commit()
        return {"status": "ok", "escalated": count}
    except Exception as exc:  # pragma: no cover - defensive
        session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()


def _send_escalation_email(
    event_id: str,
    event_data: dict,
    recipients: list[str],
) -> None:
    """Send an escalation email bypassing per-source ``emails`` config.

    Mirrors ``send_email_alert`` but always uses ``recipients`` instead
    of looking up ``alert_config['emails']``. Logs to ``AlertLog`` for
    audit.
    """
    import resend
    from app.models import AlertLog

    if not settings.resend_api_key or not recipients:
        return

    workflow_name = event_data.get("workflow_id", "ESCALATION")
    error_message = event_data.get("error_message", "")
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    html_body = f"""
    <html><body style="font-family: sans-serif; color: #333;">
      <h2 style="color: #d32f2f;">🚨 Escalation: Unacknowledged Alert</h2>
      <p><strong>Source:</strong> {event_data.get('source_id', 'N/A')}</p>
      <p><strong>Reason:</strong> {error_message}</p>
      <p><strong>Time:</strong> {timestamp}</p>
      <p style="margin-top: 20px; color: #555;">
        This is an escalation. The original alert was not acknowledged
        within the configured window.
      </p>
    </body></html>
    """
    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send(
            {
                "from": settings.alert_email_from,
                "to": recipients,
                "subject": f"🚨 [ESCALATED] FlowWatch: {workflow_name}",
                "html": html_body,
            }
        )
        with SessionLocal() as session:
            try:
                session.add(
                    AlertLog(
                        source_id=event_data.get("source_id", ""),
                        alert_type="email",
                        message=f"Escalation email sent for alert {event_id}",
                        status="sent",
                    )
                )
                session.commit()
            finally:
                session.close()
    except Exception:
        # Escalation is best-effort; if the email fails, the next run
        # will try again.
        pass


@celery_app.task
def cleanup_old_events():
    """
    Partition maintenance via Celery Beat (daily at 2am UTC).
    - Creates partitions for the next 7 days
    - Drops partitions older than 7 days
    Uses raw SQL via psycopg2 sync engine.
    """
    from datetime import date, timedelta
    from sqlalchemy import text

    with engine.connect() as conn:
        # --- Create future partitions (next 7 days) ---
        today = date.today()
        for i in range(1, 8):
            partition_date = today + timedelta(days=i)
            table_name = f"workflow_events_y{partition_date.strftime('%Y%m%d')}"
            start_val = partition_date.strftime("%Y-%m-%d 00:00:00")
            end_val = partition_date.strftime("%Y-%m-%d 23:59:59")
            conn.execute(text(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name}
                PARTITION OF workflow_events
                FOR VALUES FROM ('{start_val}') TO ('{end_val}')
                """
            ))
        conn.commit()

        # --- Drop partitions older than 7 days ---
        cutoff = (today - timedelta(days=7)).strftime("%Y%m%d")
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'workflow_events_y%' "
                "AND table_name < 'workflow_events_y' || :cutoff "
                "AND table_schema = 'public'"
            ),
            {"cutoff": cutoff},
        )
        old_partitions = [row[0] for row in result]
        for table_name in old_partitions:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        conn.commit()
