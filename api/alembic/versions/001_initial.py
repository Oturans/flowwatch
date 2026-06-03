"""Initial schema

Creates the three core tables: webhook_sources, workflow_events (parent
of a RANGE-partitioned by-received_at tree), and alert_log. Initial
partitions are created for today + 7 days forward; Celery Beat's
``cleanup_old_events`` task keeps them rolled forward in production.
"""

from datetime import date, timedelta

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create webhook_sources table
    op.create_table(
        'webhook_sources',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('signing_secret', sa.String(255), nullable=False),
        sa.Column('platform', sa.String(32), nullable=False),
        sa.Column('alert_config', postgresql.JSON, default=dict),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create workflow_events table (parent for partitioning)
    op.create_table(
        'workflow_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.func.gen_random_uuid()),
        sa.Column('source_id', sa.String(64), sa.ForeignKey('webhook_sources.id'), nullable=False),
        sa.Column('workflow_id', sa.String(128), nullable=False),
        sa.Column('run_id', sa.String(128), nullable=True),
        sa.Column('event_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('payload', postgresql.JSON, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), primary_key=True, server_default=sa.func.now()),
        postgresql_partition_by='RANGE (received_at)',
    )

    # Create indexes
    op.create_index('idx_events_source_received', 'workflow_events', ['source_id', 'received_at'])
    op.create_index('idx_events_workflow_received', 'workflow_events', ['workflow_id', 'received_at'])
    op.create_index('idx_events_status_received', 'workflow_events', ['status', 'received_at'])

    # Create alert_log table
    op.create_table(
        'alert_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.func.gen_random_uuid()),
        sa.Column('source_id', sa.String(64), sa.ForeignKey('webhook_sources.id'), nullable=False),
        sa.Column('alert_type', sa.String(32), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('status', sa.String(16), default='sent'),
    )

    # Create initial partitions for today + the next 7 days. Celery Beat's
    # ``cleanup_old_events`` task keeps these rolled forward in production.
    today = date.today()
    for i in range(8):
        d = today + timedelta(days=i)
        next_d = d + timedelta(days=1)
        table_name = f"workflow_events_y{d.strftime('%Y%m%d')}"
        start_val = d.strftime("%Y-%m-%d 00:00:00")
        end_val = next_d.strftime("%Y-%m-%d 00:00:00")
        op.execute(
            f"CREATE TABLE IF NOT EXISTS {table_name} "
            f"PARTITION OF workflow_events "
            f"FOR VALUES FROM ('{start_val}') TO ('{end_val}')"
        )


def downgrade() -> None:
    op.drop_table('alert_log')
    op.drop_index('idx_events_status_received')
    op.drop_index('idx_events_workflow_received')
    op.drop_index('idx_events_source_received')
    op.drop_table('workflow_events')
    op.drop_table('webhook_sources')