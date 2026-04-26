${message}

"""
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

    # Create initial partitions (today + 7 days ahead)
    today = '2026-04-26'
    for i in range(8):
        day_str = f'2026-04-{26+i:02d}' if i < 5 else f'2026-05-{i-4:02d}'
        next_day = f'2026-04-{27+i:02d}' if i < 4 else f'2026-05-{i-3:02d}'
        
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS workflow_events_y{i} 
            PARTITION OF workflow_events 
            FOR VALUES FROM ('{day_str}') TO ('{next_day}')
        """)


def downgrade() -> None:
    op.drop_table('alert_log')
    op.drop_index('idx_events_status_received')
    op.drop_index('idx_events_workflow_received')
    op.drop_index('idx_events_source_received')
    op.drop_table('workflow_events')
    op.drop_table('webhook_sources')