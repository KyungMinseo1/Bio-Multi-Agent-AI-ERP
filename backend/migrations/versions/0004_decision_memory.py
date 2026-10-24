"""Decision snapshots, outcome revisions and private analysis ownership."""
from alembic import op
import sqlalchemy as sa
revision='0004_decision_memory'
down_revision='0003_quote_workflow'
branch_labels=depends_on=None

def upgrade():
    with op.batch_alter_table('discussion_runs') as batch:
        batch.add_column(sa.Column('actor_id',sa.String(36),nullable=True))
        batch.create_foreign_key('fk_discussion_actor','users',['actor_id'],['id'])
    op.create_table('decision_cases',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('scenario_id',sa.String(100),sa.ForeignKey('scenarios.id'),nullable=False),
        sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('po_id',sa.String(100),nullable=False),
        sa.Column('run_id',sa.String(36),sa.ForeignKey('discussion_runs.id'),nullable=True),
        sa.Column('source_kind',sa.String(20),nullable=False),
        sa.Column('decision',sa.JSON(),nullable=False),
        sa.Column('outcome',sa.JSON(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('scenario_id','po_id',name='uq_decision_case_po'))
    op.create_index('ix_decision_cases_actor_id','decision_cases',['actor_id'])
    op.create_index('ix_decision_cases_scenario_id','decision_cases',['scenario_id'])

def downgrade():
    op.drop_table('decision_cases')
    with op.batch_alter_table('discussion_runs') as batch:
        batch.drop_constraint('fk_discussion_actor',type_='foreignkey')
        batch.drop_column('actor_id')
