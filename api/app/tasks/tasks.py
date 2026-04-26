import json
import httpx
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.celery_app import celery_app
from app.config import get_settings

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


@celery_app.task
def cleanup_old_events():
    """
    Cleanup task to run via Celery Beat.
    For MVP, partition dropping handles retention.
    """
    pass  # Placeholder for retention policy


@celery_app.task
def send_email_alert(event_id: str, event_data: dict):
    """
    Send email alert for failed events via Resend.
    Does NOT retry on failure — just logs and returns.
    """
    try:
        import resend
        from app.models import AlertLog
        from sqlalchemy.orm import Session

        if not settings.resend_api_key or not settings.alert_email_to:
            return {"status": "skipped", "reason": "no_email_config"}

        session = SessionLocal()
        try:
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
                "to": settings.alert_email_to,
                "subject": f"🚨 FlowWatch: {workflow_name} failed",
                "html": html_body,
            }
            resend.Emails.send(params)


            # Log alert
            alert = AlertLog(
                source_id=source_id,
                alert_type="email",
                message=f"Email alert sent for event {event_id}",
                status="sent"
            )
            session.add(alert)
            session.commit()


            return {"status": "sent", "alert_type": "email"}

        finally:
            session.close()

    except Exception as exc:
        # Don't retry - just log and return
        try:
            from app.models import AlertLog
            session = SessionLocal()
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
def cleanup_old_events():
    pass