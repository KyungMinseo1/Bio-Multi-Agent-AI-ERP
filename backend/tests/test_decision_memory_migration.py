from pathlib import Path
import json
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text,inspect


def test_memory_migration_preserves_legacy_snapshots_and_does_not_guess_owners(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1];url='sqlite:///'+(tmp_path/'memory.db').as_posix();monkeypatch.setenv('DATABASE_URL',url)
    config=Config(str(root/'alembic.ini'));config.set_main_option('script_location',str(root/'migrations'))
    command.upgrade(config,'0003_quote_workflow');engine=create_engine(url)
    frozen={'revision':7,'materials':[{'id':'m','name':'original','quantity':'0'}]}
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (id,email,password_hash,role) VALUES ('u','legacy@example.test','unused','approver')"))
            conn.execute(text("INSERT INTO scenarios (id,revision,data) VALUES ('s',7,'{}')"))
            conn.execute(text("INSERT INTO discussion_runs (id,scenario_id,snapshot_revision,snapshot,calculation,status,progress,created_at) VALUES ('run','s',7,:snapshot,'{}','completed','{}',CURRENT_TIMESTAMP)"),{'snapshot':json.dumps(frozen)})
        command.upgrade(config,'head')
        with engine.connect() as conn:
            row=conn.execute(text("SELECT snapshot,actor_id FROM discussion_runs WHERE id='run'")).one()
            assert json.loads(row[0])==frozen and row[1] is None
            assert conn.execute(text('SELECT COUNT(*) FROM decision_cases')).scalar()==0
            assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0004_decision_memory'
        assert any(x['referred_table']=='discussion_runs' for x in inspect(engine).get_foreign_keys('decision_cases'))
        command.downgrade(config,'0003_quote_workflow')
        with engine.connect() as conn:
            assert json.loads(conn.execute(text("SELECT snapshot FROM discussion_runs WHERE id='run'")).scalar())==frozen
        assert not inspect(engine).has_table('decision_cases')
    finally:
        engine.dispose()
