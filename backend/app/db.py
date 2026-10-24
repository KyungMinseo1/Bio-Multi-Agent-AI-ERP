from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from .config import setting

url = setting("DATABASE_URL", "sqlite:///./bioerp.db")
engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}, pool_pre_ping=True)
if url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_constraints(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


def assert_migrated():
    from sqlalchemy import text
    if not inspect(engine).has_table("alembic_version"):
        raise RuntimeError("Database migration required: run alembic upgrade head")
    with engine.connect() as conn:
        if conn.execute(text("SELECT version_num FROM alembic_version")).scalar() != "0001_initial":
            raise RuntimeError("Database migration required: run alembic upgrade head")


def insert_if_missing(db, model, values, keys):
    # Both supported dialects provide real conflict-safe insert, including parallel API/worker startup.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return db.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=keys))
