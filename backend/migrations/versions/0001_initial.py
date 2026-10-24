"""Initial scenario-isolated ERP, immutable decision history and local authentication."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def id_column():
    return sa.Column("id", sa.String(36), primary_key=True)


def json_column(name="data", nullable=False):
    return sa.Column(name, sa.JSON(), nullable=nullable)


def scenario_fk():
    return sa.Column("scenario_id", sa.String(100), sa.ForeignKey("scenarios.id"), nullable=False)


def upgrade():
    op.create_table("scenarios", sa.Column("id", sa.String(100), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False), json_column())
    op.create_table("erp_records", id_column(), scenario_fk(), sa.Column("collection", sa.String(50), nullable=False), sa.Column("record_id", sa.String(100), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), json_column(), sa.UniqueConstraint("scenario_id", "collection", "record_id"))
    op.create_index("ix_erp_records_scenario_collection", "erp_records", ["scenario_id", "collection"])
    op.create_table("users", id_column(), sa.Column("email", sa.String(254), nullable=False, unique=True), sa.Column("password_hash", sa.Text(), nullable=False), sa.Column("role", sa.String(20), nullable=False))
    op.create_table("sessions", sa.Column("token_hash", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("audit_events", id_column(), sa.Column("scenario_id", sa.String(100)), sa.Column("actor", sa.String(254), nullable=False), sa.Column("action", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), json_column("before", True), json_column("after", True))
    op.create_index("ix_audit_events_scenario_id", "audit_events", ["scenario_id"])
    op.create_table("jobs", id_column(), sa.Column("scenario_id", sa.String(100)), sa.Column("kind", sa.String(40), nullable=False), json_column("payload"), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("error", sa.Text()))
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_table("discussion_runs", id_column(), scenario_fk(), sa.Column("snapshot_revision", sa.Integer(), nullable=False), json_column("snapshot"), json_column("calculation"), sa.Column("status", sa.String(30), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), json_column("error", True), json_column("progress"))
    op.create_index("ix_discussion_runs_scenario_id", "discussion_runs", ["scenario_id"])
    op.create_table("run_artifacts", id_column(), sa.Column("run_id", sa.String(36), sa.ForeignKey("discussion_runs.id"), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("kind", sa.String(30), nullable=False), json_column(), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("run_id", "sequence"))
    op.create_index("ix_run_artifacts_run_id", "run_artifacts", ["run_id"])
    op.create_table("recommendations", id_column(), sa.Column("run_id", sa.String(36), sa.ForeignKey("discussion_runs.id"), nullable=False), scenario_fk(), sa.Column("snapshot_revision", sa.Integer(), nullable=False), sa.Column("candidate_id", sa.String(100), nullable=False), json_column(), sa.Column("status", sa.String(30), nullable=False))
    op.create_index("ix_recommendations_run_id", "recommendations", ["run_id"])
    op.create_table("approvals", id_column(), scenario_fk(), sa.Column("snapshot_revision", sa.Integer(), nullable=False), sa.Column("recommendation_id", sa.String(36), sa.ForeignKey("recommendations.id"), nullable=False), sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("amount", sa.Numeric(24, 6), nullable=False), json_column(), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("scenario_id", "snapshot_revision"), sa.UniqueConstraint("actor_id", "idempotency_key"), sa.UniqueConstraint("recommendation_id"))
    op.create_table("external_sources", id_column(), sa.Column("revision", sa.Integer(), nullable=False), json_column())
    op.create_table("collection_runs", id_column(), sa.Column("source_id", sa.String(36), sa.ForeignKey("external_sources.id"), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(20), nullable=False), json_column())
    op.create_index("ix_collection_runs_source_id", "collection_runs", ["source_id"])
    op.create_table("external_issues", id_column(), sa.Column("source_id", sa.String(36), sa.ForeignKey("external_sources.id"), nullable=False), sa.Column("external_key", sa.String(500), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False), json_column(), sa.UniqueConstraint("source_id", "external_key"))
    op.create_table("issue_evidence", id_column(), sa.Column("issue_id", sa.String(36), sa.ForeignKey("external_issues.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), json_column())
    op.create_index("ix_issue_evidence_issue_id", "issue_evidence", ["issue_id"])
    op.create_table("source_requests", id_column(), sa.Column("source_id", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_source_requests_created_at", "source_requests", ["created_at"])
    op.create_table("alerts", id_column(), scenario_fk(), sa.Column("scope_key", sa.String(250), nullable=False), sa.Column("status", sa.String(30), nullable=False), json_column(), json_column("acknowledgement", True), sa.UniqueConstraint("scenario_id", "scope_key"))


def downgrade():
    for name in ("alerts", "source_requests", "issue_evidence", "external_issues", "collection_runs", "external_sources", "approvals", "recommendations", "run_artifacts", "discussion_runs", "jobs", "audit_events", "sessions", "users", "erp_records", "scenarios"):
        op.drop_table(name)
