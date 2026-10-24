"""Durable RFQ drafts and one delivery per inquiry/mode. Legacy sends stay protected."""
from alembic import op
import sqlalchemy as sa

revision = "0003_rfq_drafts"
down_revision = "0002_outbound_emails"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("outbound_emails") as batch:
        batch.add_column(sa.Column("scope", sa.String(200), nullable=True))
        batch.add_column(sa.Column("mode", sa.String(20), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("reply_status", sa.String(30), nullable=False, server_default="not_requested"))
        batch.add_column(sa.Column("request_data", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_unique_constraint("uq_outbound_emails_scope", ["scope"])
    op.execute("UPDATE outbound_emails SET reply_status='awaiting_reply' WHERE status='sent'")
    # The old SMTP handler could label timeouts as failed after DATA was accepted.
    op.execute("UPDATE outbound_emails SET status='unknown', reply_status='check_required' WHERE status='failed' AND (error_code IS NULL OR error_code NOT IN ('configuration', 'ValueError'))")
    op.execute("UPDATE outbound_emails SET reply_status='check_required' WHERE status='sending'")


def downgrade():
    with op.batch_alter_table("outbound_emails") as batch:
        batch.drop_constraint("uq_outbound_emails_scope", type_="unique")
        for column in ("request_data", "reply_status", "mode", "scope"):
            batch.drop_column(column)
