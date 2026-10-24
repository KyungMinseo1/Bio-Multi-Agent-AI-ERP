"""The imported teammate migration preserves existing 0002 data."""
from pathlib import Path
import json
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text


def test_team_migration_preserves_existing_supplier_and_mail_data(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]
    url='sqlite:///'+(tmp_path/'upgrade.db').as_posix();monkeypatch.setenv('DATABASE_URL',url)
    config=Config(str(root/'alembic.ini'));config.set_main_option('script_location',str(root/'migrations'))
    command.upgrade(config,'0002_outbound_emails')
    engine=create_engine(url)
    data={'id':'SUP-B','name':'B','email':'existing@supplier.co.kr'}
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (id,email,password_hash,role) VALUES ('u','buyer@example.test','unused','approver')"))
            conn.execute(text("INSERT INTO scenarios (id,revision,data) VALUES ('s',1,'{}')"))
            conn.execute(text("INSERT INTO erp_records (id,scenario_id,collection,record_id,revision,data) VALUES ('r','s','suppliers','SUP-B',1,:data)"),{'data':json.dumps(data)})
            conn.execute(text("INSERT INTO outbound_emails (id,idempotency_key,case_id,vendor_id,vendor_name,actor_id,sender,recipient,subject,status,created_at,updated_at) VALUES ('old','old-key','PR-old','B','B','u','buyer@example.test','existing@supplier.co.kr','preserved','sent',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        command.upgrade(config,'head')
        with engine.connect() as conn:
            assert json.loads(conn.execute(text("SELECT data FROM erp_records WHERE id='r'")).scalar())==data
            assert tuple(conn.execute(text("SELECT status,subject,delivery_mode,payload FROM outbound_emails WHERE id='old'")).one())==('sent','preserved','smtp',None)
            assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0003_quote_workflow'
    finally:
        engine.dispose()
