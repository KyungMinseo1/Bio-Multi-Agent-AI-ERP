"""Upgrade a populated 0002 database without touching the local demo database."""
from pathlib import Path
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text, inspect


def test_upgrade_preserves_existing_dispatches(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'migration.db').as_posix()
    monkeypatch.setenv('DATABASE_URL',url)
    root=Path(__file__).resolve().parents[1]
    config=Config(str(root/'alembic.ini'))
    config.set_main_option('script_location',str(root/'migrations'))
    command.upgrade(config,'0002_outbound_emails')
    engine=create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (id,email,password_hash,role) VALUES ('u','buyer@company.co.kr','unused','approver')"))
            conn.execute(text("INSERT INTO outbound_emails (id,idempotency_key,case_id,vendor_id,vendor_name,actor_id,sender,recipient,subject,status,created_at,updated_at) VALUES ('old','old-key','PR-old','A','A','u','buyer@company.co.kr','rfq@supplier.co.kr','old subject','sent',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO outbound_emails (id,idempotency_key,case_id,vendor_id,vendor_name,actor_id,sender,recipient,subject,status,error_code,created_at,updated_at) VALUES ('old-timeout','old-timeout-key','PR-old','B','B','u','buyer@company.co.kr','rfq@supplier.co.kr','old subject','failed','MailDeliveryError',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        command.upgrade(config,'head')
        with engine.connect() as conn:
            row=conn.execute(text("SELECT mode,status,scope,request_data FROM outbound_emails WHERE id='old'")).one()
            assert tuple(row)==('legacy','sent',None,'{}')
            assert conn.execute(text("SELECT reply_status FROM outbound_emails WHERE id='old'")).scalar()=='awaiting_reply'
            assert conn.execute(text("SELECT status FROM outbound_emails WHERE id='old-timeout'")).scalar()=='unknown'
            assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0003_rfq_drafts'
        assert any(c['column_names']==['scope'] for c in inspect(engine).get_unique_constraints('outbound_emails'))
    finally:
        engine.dispose()
