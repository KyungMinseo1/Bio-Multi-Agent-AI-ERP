import asyncio
import signal
from datetime import timedelta, timezone
from sqlalchemy import select, update, or_, and_
from .db import SessionLocal, assert_migrated
from .models import Job, Scenario, ExternalSource, now
from .auth import bootstrap_accounts
from .providers import close_clients
from .services.external_sources import seed_sources, sync_source
from .services.discussions import run_discussion
from .services.alerts import recalculate


def claim_job():
    with SessionLocal() as db:
        moment = now()
        eligible = or_(Job.status == "queued", and_(Job.status == "running", Job.lease_until < moment))
        job = db.scalar(select(Job).where(eligible).order_by(Job.created_at).with_for_update(skip_locked=True).limit(1))
        if not job:
            return None
        # SQLite returns naive datetimes; skip Python-side evaluation against the aware `moment`.
        result = db.execute(update(Job).where(Job.id == job.id, eligible).values(status="running", lease_until=moment + timedelta(minutes=5)).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        return {"id": job.id, "kind": job.kind, "scenario_id": job.scenario_id, "payload": job.payload}


async def heartbeat(job_id):
    while True:
        await asyncio.sleep(30)
        with SessionLocal() as db:
            db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(lease_until=now() + timedelta(minutes=5)))
            db.commit()


def schedule_periodic():
    with SessionLocal() as db:
        moment = now()
        for source in db.scalars(select(ExternalSource)):
            value = source.data
            if not value.get("enabled"):
                continue
            last = value.get("last_success")
            interval = max(int(value.get("poll_interval_minutes", 720)), int(value.get("feed_ttl_minutes", 0)))
            due = not last or __import__("datetime").datetime.fromisoformat(last) + timedelta(minutes=interval) <= moment
            existing = db.scalar(select(Job.id).where(Job.kind == "external_sync", Job.status.in_(["queued", "running"]), Job.payload["source_id"].as_string() == source.id))
            if due and not existing:
                # Failed endpoints retry no faster than the scheduler's five-minute cadence.
                db.add(Job(kind="external_sync", payload={"source_id": source.id}))
        for scenario_id in db.scalars(select(Scenario.id)):
            if not db.scalar(select(Job.id).where(Job.kind == "recalculate", Job.scenario_id == scenario_id, Job.status.in_(["queued", "running"]))):
                db.add(Job(kind="recalculate", scenario_id=scenario_id, payload={}))
        db.commit()


async def main():
    assert_migrated()
    with SessionLocal() as db:
        bootstrap_accounts(db)
        seed_sources(db)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    last_schedule = 0
    try:
        while not stop.is_set():
            if loop.time() - last_schedule >= 300:
                schedule_periodic()
                last_schedule = loop.time()
            job = claim_job()
            if not job:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass
                continue
            beat = asyncio.create_task(heartbeat(job["id"]))
            error = None
            try:
                if job["kind"] == "discussion":
                    await run_discussion(job["payload"]["run_id"])
                elif job["kind"] == "recalculate":
                    with SessionLocal() as db:
                        recalculate(db, job["scenario_id"])
                elif job["kind"] == "external_sync":
                    result = await sync_source(job["payload"]["source_id"])
                    if result["status"] == "failed":
                        error = result.get("error", "Source collection failed")
                else:
                    error = "Unknown job kind"
            except Exception as exc:
                error = f"Job failed ({type(exc).__name__})"
            finally:
                beat.cancel()
                try:
                    await beat
                except asyncio.CancelledError:
                    pass
            with SessionLocal() as db:
                row = db.get(Job, job["id"])
                row.status, row.error, row.lease_until = ("failed" if error else "completed"), error, None
                db.commit()
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
