"""Version-bound quote approval snapshots and Gmail MCP receipts."""
from alembic import op
import sqlalchemy as sa
revision = "0003_quote_workflow"
down_revision = "0002_outbound_emails"
branch_labels = None
depends_on = None

def upgrade():
    for column in [sa.Column("delivery_mode", sa.String(30), nullable=False, server_default="smtp"), sa.Column("source_stamp", sa.String(64)), sa.Column("thread_id", sa.String(500)), sa.Column("payload", sa.JSON()), sa.Column("responses", sa.JSON())]:
        op.add_column("outbound_emails", column)

def downgrade():
    with op.batch_alter_table("outbound_emails") as batch:
        for name in ["responses", "payload", "thread_id", "source_stamp", "delivery_mode"]:
            batch.drop_column(name)
