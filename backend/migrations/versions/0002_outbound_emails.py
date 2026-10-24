"""Persist outbound RFQ email status without storing message bodies."""
from alembic import op
import sqlalchemy as sa

revision = "0002_outbound_emails"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outbound_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("case_id", sa.String(100), nullable=False),
        sa.Column("vendor_id", sa.String(100), nullable=False),
        sa.Column("vendor_name", sa.String(200), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sender", sa.String(254), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(250), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message_id", sa.String(500)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_outbound_emails_case_id", "outbound_emails", ["case_id"])
    op.create_index("ix_outbound_emails_actor_id", "outbound_emails", ["actor_id"])
    op.create_index("ix_outbound_emails_status", "outbound_emails", ["status"])
    op.create_index("ix_outbound_emails_created_at", "outbound_emails", ["created_at"])


def downgrade():
    op.drop_table("outbound_emails")
