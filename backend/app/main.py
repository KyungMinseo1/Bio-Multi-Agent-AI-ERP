import asyncio
import copy
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlsplit
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import models
from .auth import COOKIE, approver, bootstrap_accounts, current_user, mutation_user, public_user, token_hash, verify_password
from .config import COLLECTIONS, setting, planning_date, review_rounds
from .db import get_db, SessionLocal, assert_migrated
from .models import User, Session, Scenario, ERPRecord, Job, DiscussionRun, RunArtifact, Recommendation, ExternalSource, ExternalIssue, IssueEvidence, CollectionRun, AuditEvent, Alert, uid, now
from .schemas import Login, DiscussionInput, ApprovalInput, DepartmentTurn
from .providers import require_configuration, public_settings, ProviderError, generate_json, close_clients
from .scenarios import list_scenarios
from .services.erp import ensure_scenario, snapshot, mutate, audit, lock_revision, enqueue_recalculation
from .services.alerts import recalculate
from .services.approvals import approve
from .services.discussions import artifact
from .services.external_sources import seed_sources, sync_source, validate_url, public_addresses, CollectionError
from .services.planning import evaluate
from .models import utc_iso


@asynccontextmanager
async def lifespan(app):
    assert_migrated()
    with SessionLocal() as db:
        bootstrap_accounts(db)
        seed_sources(db)
    yield
    await close_clients()


app = FastAPI(title="Bio Multi-Agent ERP", version="1.0.0", lifespan=lifespan)
api = APIRouter(prefix="/api/v1")


@app.get("/health")
def health():
    assert_migrated()
    return {"status": "ready"}


@api.get("/settings")
def settings(db=Depends(get_db)):
    auth = bool(setting("SESSION_SECRET") and db.scalar(select(User.id).limit(1)))
    return {"setup_required": not auth, "auth_configured": auth, "llm": public_settings(), "planning_as_of": planning_date(), "external_collection": {"configured": True, "limitations": "Public rolling feeds do not guarantee supply-chain coverage. Relevance requires human confirmation."}}


@api.post("/settings/test-provider")
async def test_provider(body: dict, user=Depends(approver)):
    role = body.get("role", "purchasing")
    if role not in public_settings()["roles"]:
        raise HTTPException(422, "Unknown department role")
    try:
        result = await generate_json(role, [{"role": "system", "content": "Connectivity test. Return role as assigned, strategy_id='connection-test', version=1, proposal={candidate_ids:[],summary:'연결 확인'}, impacts=[],reasons=[],evidence_refs=[],change_requests=[],position='needs_information',recommendations=[]."}, {"role": "user", "content": f"Assigned role: {role}. No procurement decision is requested."}], DepartmentTurn)
    except ProviderError as exc:
        raise HTTPException(503, detail={"code": exc.code, "message": exc.message, "role": role})
    return {"status": "connected", "role": role, "response": result}


@api.post("/auth/login")
def login(body: Login, response: Response, db=Depends(get_db)):
    if not setting("SESSION_SECRET"):
        raise HTTPException(503, detail={"code": "setup_required", "message": "Configure SESSION_SECRET and initial account environment variables"})
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or len(body.password) > 1024 or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = secrets.token_urlsafe(48)
    db.add(Session(token_hash=token_hash(token), user_id=user.id, expires_at=now() + timedelta(hours=12)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=setting("COOKIE_SECURE", "false").lower() == "true", samesite="strict", max_age=43200, path="/")
    return {"user": public_user(user)}


@api.get("/auth/me")
def me(user=Depends(current_user)):
    return {"user": public_user(user)}


@api.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(mutation_user), db=Depends(get_db)):
    row = db.get(Session, token_hash(request.cookies.get(COOKIE, "")))
    if row:
        db.delete(row)
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"status": "logged_out"}


@api.get("/scenarios")
def scenarios(db=Depends(get_db)):
    return [{**s, "revision": db.get(Scenario, s["id"]).revision if db.get(Scenario, s["id"]) else s.get("revision", 1)} for s in list_scenarios()]


def merged_issues(db, state):
    existing = {v["id"] for v in state["issues"]}
    return state["issues"] + [r.data for r in db.scalars(select(ExternalIssue).order_by(ExternalIssue.id)) if r.id not in existing]


@api.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, db=Depends(get_db)):
    try:
        state = snapshot(db, scenario_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        state = snapshot(db, scenario_id)
    state["issues"] = merged_issues(db, state)
    return state


@api.get("/scenarios/{scenario_id}/planning")
@api.post("/scenarios/{scenario_id}/evaluate")
def planning(scenario_id: str, db=Depends(get_db)):
    return recalculate(db, scenario_id)


@api.get("/scenarios/{scenario_id}/alerts")
def scenario_alerts(scenario_id: str, db=Depends(get_db)):
    recalculate(db, scenario_id)
    return [{**r.data, "id": r.id, "status": r.status, "acknowledgement": r.acknowledgement} for r in db.scalars(select(Alert).where(Alert.scenario_id == scenario_id))]


@api.get("/alerts")
def alerts(scenario_id: str = "baseline", db=Depends(get_db)):
    return scenario_alerts(scenario_id, db)


@api.post("/planning/recalculate", status_code=202)
def enqueue_planning(body: dict, user=Depends(mutation_user), db=Depends(get_db)):
    scenario_id = body.get("scenario_id", "baseline")
    ensure_scenario(db, scenario_id)
    enqueue_recalculation(db, scenario_id)
    db.commit()
    return {"status": "queued", "scenario_id": scenario_id}


@api.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, body: dict, user=Depends(mutation_user), db=Depends(get_db)):
    row = db.get(Alert, alert_id)
    if not row:
        raise HTTPException(404, "Alert not found")
    row.acknowledgement = {"actor": user.email, "at": now().isoformat(), "reason": body.get("reason", "")}
    audit(db, user.email, "alert.acknowledge", row.scenario_id, after={"id": row.id, **row.acknowledgement})
    db.commit()
    return {**row.data, "id": row.id, "acknowledgement": row.acknowledgement}


def run_view(db, run, full=True):
    result = {"id": run.id, "scenario_id": run.scenario_id, "status": run.status, "snapshot_revision": run.snapshot_revision, "created_at": utc_iso(run.created_at), "error": run.error, "progress": run.progress}
    if full:
        artifacts = db.scalars(select(RunArtifact).where(RunArtifact.run_id == run.id).order_by(RunArtifact.sequence)).all()
        recommendations = sorted(db.scalars(select(Recommendation).where(Recommendation.run_id == run.id)), key=lambda row: row.data.get("rank") or 999)
        result.update(messages=[{**a.data, "id": a.id} for a in artifacts if a.kind == "message"], strategies=[{**a.data, "id": a.id} for a in artifacts if a.kind == "strategy"], validations=[{**a.data, "id": a.id} for a in artifacts if a.kind == "validation"], events=[{"id": a.id, "sequence": a.sequence, "type": a.kind, "data": a.data} for a in artifacts], recommendations=[{**r.data, "id": r.id, "candidate_id": r.candidate_id, "status": r.status, "revision": 1, "snapshot_revision": r.snapshot_revision} for r in recommendations], snapshot=run.snapshot, calculation=run.calculation)
    return result


@api.get("/scenarios/{scenario_id}/discussions")
def list_discussions(scenario_id: str, db=Depends(get_db)):
    ensure_scenario(db, scenario_id)
    db.commit()
    return [run_view(db, r, False) for r in db.scalars(select(DiscussionRun).where(DiscussionRun.scenario_id == scenario_id).order_by(DiscussionRun.created_at.desc()))]


@api.post("/scenarios/{scenario_id}/discussions", status_code=202)
def create_discussion(scenario_id: str, body: DiscussionInput, user=Depends(mutation_user), db=Depends(get_db)):
    try:
        require_configuration()
    except ProviderError as exc:
        raise HTTPException(503, detail={"code": exc.code, "message": exc.message, "role": exc.role})
    state = snapshot(db, scenario_id)
    if state["revision"] != body.expected_revision:
        raise HTTPException(409, detail={"code": "stale", "message": "ERP revision changed", "current_revision": state["revision"]})
    calculation = evaluate(state, as_of=planning_date())
    calculation["review_rounds"] = review_rounds()
    if body.alert_id:
        alert = db.get(Alert, body.alert_id)
        if not alert or alert.scenario_id != scenario_id:
            raise HTTPException(422, "Unknown alert_id for this scenario")
    run = DiscussionRun(scenario_id=scenario_id, snapshot_revision=state["revision"], snapshot=state, calculation=calculation, progress={})
    db.add(run)
    db.flush()
    db.add(Job(kind="discussion", scenario_id=scenario_id, payload={"run_id": run.id}))
    artifact(db, run.id, "status", {"status": "queued"})
    audit(db, user.email, "discussion.create", scenario_id, after={"id": run.id, "snapshot_revision": run.snapshot_revision})
    db.commit()
    return run_view(db, run)


@api.get("/discussions/{run_id}")
def get_discussion(run_id: str, db=Depends(get_db)):
    run = db.get(DiscussionRun, run_id)
    if not run:
        raise HTTPException(404, "Discussion not found")
    return run_view(db, run)


@api.get("/discussions/{run_id}/snapshot")
def get_snapshot(run_id: str, db=Depends(get_db)):
    run = db.get(DiscussionRun, run_id)
    if not run:
        raise HTTPException(404, "Discussion not found")
    return {"snapshot": run.snapshot, "calculation": run.calculation}


@api.get("/discussions/{run_id}/events")
async def discussion_events(run_id: str, request: Request, last_event_id: str | None = Header(None)):
    with SessionLocal() as db:
        if not db.get(DiscussionRun, run_id):
            raise HTTPException(404, "Discussion not found")
    try:
        start = int(last_event_id or request.query_params.get("after", "0"))
    except ValueError:
        raise HTTPException(422, "Last-Event-ID must be an integer sequence")
    async def stream():
        sequence = start
        while not await request.is_disconnected():
            with SessionLocal() as db:
                rows = db.scalars(select(RunArtifact).where(RunArtifact.run_id == run_id, RunArtifact.sequence > sequence).order_by(RunArtifact.sequence)).all()
                run = db.get(DiscussionRun, run_id)
                events = [(r.sequence, {"id": r.id, "type": r.kind, "data": r.data}) for r in rows]
                terminal = run.status in {"completed", "awaiting_review", "failed", "stale"}
            for sequence, payload in events:
                yield f"id: {sequence}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if terminal:
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.post("/recommendations/{recommendation_id}/approve")
async def approve_recommendation(recommendation_id: str, body: ApprovalInput, idempotency_key: str | None = Header(None), user=Depends(approver), db=Depends(get_db)):
    return await approve(db, recommendation_id, body, idempotency_key, user)


@api.get("/external-sources")
def sources(db=Depends(get_db)):
    return [r.data for r in db.scalars(select(ExternalSource))]


async def source_value(body, previous=None):
    allowed = {"id", "revision", "kind", "display_name", "url", "enabled", "supplier_id", "official_domain", "ownership_verified", "poll_interval_minutes"}
    if set(body) - allowed:
        raise HTTPException(422, "Unknown external source fields")
    data = {**(previous or {}), **body}
    if data.get("kind") not in {"rss", "openfda"} or not data.get("display_name") or not data.get("url"):
        raise HTTPException(422, "kind, display_name and public HTTPS url are required")
    if data["kind"] == "openfda" and data["url"] != "https://api.fda.gov/drug/enforcement.json":
        raise HTTPException(422, "openFDA uses the fixed official enforcement endpoint")
    try:
        host = validate_url(data["url"])
        if data.get("enabled", True) and (not previous or data["url"] != previous["url"] or not previous.get("enabled")):
            host, _ = await public_addresses(data["url"])
    except Exception as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, CollectionError) else "Source DNS validation failed")
    if data.get("official_domain") != host or not data.get("ownership_verified"):
        raise HTTPException(422, "Approver must verify source ownership and matching official_domain")
    interval = data.get("poll_interval_minutes", 1440 if data["kind"] == "openfda" else 720)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise HTTPException(422, "poll_interval_minutes must be a positive integer")
    data.update(poll_interval_minutes=interval, enabled=data.get("enabled", True), supplier_id=data.get("supplier_id"))
    return data


@api.post("/external-sources", status_code=201)
async def add_source(body: dict, user=Depends(approver), db=Depends(get_db)):
    data = await source_value(body)
    source_id = uid()
    data.update(id=source_id, revision=1, last_success=None, last_error=None, stale=True)
    db.add(ExternalSource(id=source_id, data=data))
    audit(db, user.email, "external_source.create", after=data)
    db.commit()
    return data


@api.patch("/external-sources/{source_id}")
async def edit_source(source_id: str, body: dict, user=Depends(approver), db=Depends(get_db)):
    row = db.get(ExternalSource, source_id)
    if not row:
        raise HTTPException(404, "Source not found")
    if body.get("revision") != row.revision:
        raise HTTPException(409, "Source revision conflict")
    before = copy.deepcopy(row.data)
    value = await source_value(body, before)
    value.update(id=row.id, revision=row.revision + 1)
    from sqlalchemy import update
    result = db.execute(update(ExternalSource).where(ExternalSource.id == source_id, ExternalSource.revision == body["revision"]).values(revision=value["revision"], data=value))
    if result.rowcount != 1:
        raise HTTPException(409, "Source revision conflict")
    audit(db, user.email, "external_source.update", before=before, after=value)
    db.commit()
    return value


@api.post("/external-sources/{source_id}/sync")
async def source_sync(source_id: str, user=Depends(approver), db=Depends(get_db)):
    if not db.get(ExternalSource, source_id):
        raise HTTPException(404, "Source not found")
    return await sync_source(source_id)


@api.get("/external-sources/{source_id}/runs")
def source_runs(source_id: str, db=Depends(get_db)):
    return [{"id": r.id, "source_id": r.source_id, "status": r.status, "started_at": utc_iso(r.started_at), **r.data} for r in db.scalars(select(CollectionRun).where(CollectionRun.source_id == source_id).order_by(CollectionRun.started_at.desc()).limit(100))]


@api.get("/issues")
def issues(scenario_id: str | None = None, db=Depends(get_db)):
    return merged_issues(db, snapshot(db, scenario_id)) if scenario_id else [r.data for r in db.scalars(select(ExternalIssue))]


@api.get("/issues/{issue_id}")
def issue_detail(issue_id: str, scenario_id: str | None = None, db=Depends(get_db)):
    row = db.get(ExternalIssue, issue_id)
    if row:
        return {**row.data, "evidence_versions": [{"id": e.id, "created_at": utc_iso(e.created_at), "data": e.data} for e in db.scalars(select(IssueEvidence).where(IssueEvidence.issue_id == issue_id).order_by(IssueEvidence.created_at))], "suggested_links": []}
    if scenario_id:
        value = next((v for v in snapshot(db, scenario_id)["issues"] if v["id"] == issue_id), None)
        if value:
            return {**value, "evidence_versions": [], "suggested_links": value.get("suggested_links", [])}
    raise HTTPException(404, "Issue not found")


@api.post("/scenarios/{scenario_id}/issues/{issue_id}/links")
def link_issue(scenario_id: str, issue_id: str, body: dict, user=Depends(mutation_user), db=Depends(get_db)):
    state = snapshot(db, scenario_id)
    current = next((v for v in state["issues"] if v["id"] == issue_id), None)
    external = db.get(ExternalIssue, issue_id)
    if current is None and external is None:
        raise HTTPException(404, "Issue not found")
    source = current or external.data
    status = body.get("verification_status")
    if status not in {"unverified", "relevance_unconfirmed", "supply_impact_confirmed", "quality_impact_confirmed", "cleared"}:
        raise HTTPException(422, "Invalid verification status")
    if status in {"quality_impact_confirmed", "cleared"} and user.role != "approver":
        raise HTTPException(403, "Approver role required for quality impact or clearance")
    if not body.get("reason") or not body.get("evidence_refs"):
        raise HTTPException(422, "Reason and evidence_refs required")
    from .services.discussions import all_ids
    allowed = all_ids(state) | {e.id for e in db.scalars(select(IssueEvidence).where(IssueEvidence.issue_id == issue_id))}
    if not set(body["evidence_refs"]).issubset(allowed):
        raise HTTPException(422, "Unknown evidence reference")
    target = {k: body.get(k) for k in ("material_id", "supplier_id", "lot_id", "purchase_order_id") if body.get(k)}
    if not target:
        raise HTTPException(422, "Specify an ERP target")
    refs = {"material_id": "materials", "supplier_id": "suppliers", "lot_id": "lots", "purchase_order_id": "purchase_orders"}
    for key, value in target.items():
        if not any(r["id"] == value for r in state[refs[key]]):
            raise HTTPException(422, f"Unknown {key}")
    if not source.get("is_synthetic", source.get("source_kind") == "synthetic") and state.get("is_synthetic") and body.get("demo_association") is not True:
        raise HTTPException(422, "Real notices linked to synthetic ERP require demo_association=true")
    delay = body.get("delay_days")
    if delay is not None and (not isinstance(delay, int) or isinstance(delay, bool) or delay < 0):
        raise HTTPException(422, "delay_days must be a nonnegative integer or null")
    link = {"id": uid(), **target, "verification_status": status, "reason": body["reason"], "evidence_refs": body["evidence_refs"], "delay_days": delay, "demo_association": bool(body.get("demo_association")), "confirmed_by": user.email, "confirmed_at": now().isoformat()}
    value = {**source, **target, "verification_status": status, "delay_days": delay, "links": [*source.get("links", []), link], "revision": current["revision"] if current else 1}
    result = mutate(db, scenario_id, "issues", value, user.email, issue_id if current else None)
    if status in {"quality_impact_confirmed", "supply_impact_confirmed", "cleared"}:
        for order in state["purchase_orders"]:
            if not target.get("material_id") or order.get("material_id") == target["material_id"]:
                audit(db, user.email, "purchase_order.review_required", scenario_id, after={"id": order["id"], "issue_id": issue_id, "verification_status": status})
        db.commit()
    return result


@api.post("/issues/{issue_id}/links")
def global_link_issue(issue_id: str, body: dict, scenario_id: str, user=Depends(mutation_user), db=Depends(get_db)):
    return link_issue(scenario_id, issue_id, body, user, db)


@api.get("/scenarios/{scenario_id}/audit")
def audit_history(scenario_id: str, user=Depends(current_user), db=Depends(get_db)):
    return [{"id": r.id, "actor": r.actor, "action": r.action, "created_at": utc_iso(r.created_at), "before": r.before, "after": r.after} for r in db.scalars(select(AuditEvent).where(AuditEvent.scenario_id == scenario_id).order_by(AuditEvent.created_at.desc()).limit(200))]


def canonical_collection(value):
    collection = value.replace("-", "_")
    if collection not in COLLECTIONS:
        raise HTTPException(404, "Unknown ERP collection")
    return collection


@api.get("/scenarios/{scenario_id}/{collection}")
def list_records(scenario_id: str, collection: str, db=Depends(get_db)):
    collection = canonical_collection(collection)
    state = snapshot(db, scenario_id)
    db.commit()
    return merged_issues(db, state) if collection == "issues" else state[collection]


@api.get("/scenarios/{scenario_id}/{collection}/{record_id}")
def get_record(scenario_id: str, collection: str, record_id: str, db=Depends(get_db)):
    records = list_records(scenario_id, collection, db)
    value = next((v for v in records if v["id"] == record_id), None)
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


def check_erp_permissions(collection, body, user):
    if collection == "budgets" and user.role != "approver":
        raise HTTPException(403, "Only approver may change purchase budgets")
    if collection == "purchase_orders" and body.get("status", "approved") == "approved" and user.role != "approver":
        raise HTTPException(403, "Only approver may register approved purchase orders")
    impact_fields = {"links", "delay_days", "material_id", "supplier_id", "lot_id", "purchase_order_id"}
    if collection == "issues" and (body.get("verification_status") not in {None, "unverified", "relevance_unconfirmed"} or impact_fields.intersection(body)):
        raise HTTPException(422, "Use issue links workflow to confirm impacts and associate ERP targets")


@api.post("/scenarios/{scenario_id}/{collection}", status_code=201)
def create_record(scenario_id: str, collection: str, body: dict, user=Depends(mutation_user), db=Depends(get_db)):
    collection = canonical_collection(collection)
    check_erp_permissions(collection, body, user)
    return mutate(db, scenario_id, collection, body, user.email)


@api.patch("/scenarios/{scenario_id}/{collection}/{record_id}")
def patch_record(scenario_id: str, collection: str, record_id: str, body: dict, user=Depends(mutation_user), db=Depends(get_db)):
    collection = canonical_collection(collection)
    check_erp_permissions(collection, body, user)
    return mutate(db, scenario_id, collection, body, user.email, record_id)


@api.get("/discussions")
def global_discussions(scenario_id: str = "baseline", db=Depends(get_db)):
    return list_discussions(scenario_id, db)


@api.post("/discussions", status_code=202)
def global_create_discussion(body: dict, user=Depends(mutation_user), db=Depends(get_db)):
    value = dict(body)
    scenario_id = value.pop("scenario_id", "baseline")
    try:
        request = DiscussionInput.model_validate(value)
    except Exception:
        raise HTTPException(422, "expected_revision and optional alert_id are required")
    return create_discussion(scenario_id, request, user, db)


@api.get("/{collection}")
def global_records(collection: str, scenario_id: str = "baseline", db=Depends(get_db)):
    return list_records(scenario_id, collection, db)


@api.post("/{collection}", status_code=201)
def global_create_record(collection: str, body: dict, scenario_id: str = "baseline", user=Depends(mutation_user), db=Depends(get_db)):
    return create_record(scenario_id, collection, body, user, db)


@api.get("/{collection}/{record_id}")
def global_record(collection: str, record_id: str, scenario_id: str = "baseline", db=Depends(get_db)):
    return get_record(scenario_id, collection, record_id, db)


@api.patch("/{collection}/{record_id}")
def global_patch_record(collection: str, record_id: str, body: dict, scenario_id: str = "baseline", user=Depends(mutation_user), db=Depends(get_db)):
    return patch_record(scenario_id, collection, record_id, body, user, db)


app.include_router(api)
