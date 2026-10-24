import asyncio
import calendar
import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid5, NAMESPACE_URL
import feedparser
import httpx
from defusedxml.ElementTree import fromstring
from sqlalchemy import select, func, update
from ..db import SessionLocal, insert_if_missing
from ..models import ExternalSource, ExternalIssue, IssueEvidence, CollectionRun, SourceRequest, ERPRecord, now, uid
from ..config import setting
from ..models import utc_iso

MAX_BODY = 5 * 1024 * 1024
DEFAULTS = [
    ("openfda", "FDA Drug Enforcement", "https://api.fda.gov/drug/enforcement.json", 1440),
    ("rss", "FDA MedWatch", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/rss.xml", 720),
    ("rss", "Thermo Fisher One Lambda revision notices", "https://www.thermofisher.com/onelambda/us/en/support/rss-feed/jcr:content.rss?key=revision-notices", 720),
]


class CollectionError(Exception):
    pass


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii")
        if host.lower() in {"localhost", "metadata.google.internal"} or host.lower().endswith(".localhost"):
            raise ValueError()
        return host
    except (ValueError, UnicodeError):
        raise CollectionError("Only public HTTPS URLs without credentials on port 443 are allowed") from None


async def public_addresses(url):
    host = validate_url(url)
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise CollectionError("Source resolves to a non-public address")
    addresses.sort(key=lambda address: ":" in address)
    return host, addresses


async def fetch(url, headers=None):
    # Connect to the validated IP itself, not a second DNS lookup; preserve TLS SNI and HTTP Host.
    async with asyncio.timeout(30):
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), trust_env=False, follow_redirects=False) as client:
            for redirect in range(4):
                host, addresses = await public_addresses(url)
                parsed = urlsplit(url)
                address = addresses[0]
                netloc = f"[{address}]" if ":" in address else address
                pinned = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
                request = client.build_request("GET", pinned, headers={**(headers or {}), "Host": host, "User-Agent": "BioERP/1.0 public-source collector"})
                request.extensions["sni_hostname"] = host
                response = await client.send(request, stream=True)
                try:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect == 3 or "location" not in response.headers:
                            raise CollectionError("Source redirect limit exceeded")
                        url = urljoin(url, response.headers["location"])
                        headers = {}  # Never forward validators across origins.
                        continue
                    if response.status_code == 304:
                        return 304, dict(response.headers), b"", url
                    if int(response.headers.get("content-length", "0")) > MAX_BODY:
                        raise CollectionError("Source response exceeds 5 MiB")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BODY:
                            raise CollectionError("Source response exceeds 5 MiB")
                        chunks.append(chunk)
                    return response.status_code, dict(response.headers), b"".join(chunks), url
                finally:
                    await response.aclose()
    raise CollectionError("Unable to fetch source")


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def excerpt(value):
    parser = TextOnly()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())[:1500]


def seed_sources(db):
    quota_lock = str(uuid5(NAMESPACE_URL, "bioerp:openfda-quota-lock"))
    insert_if_missing(db, SourceRequest, {"id": quota_lock, "source_id": "quota_lock", "created_at": datetime(1970, 1, 1, tzinfo=timezone.utc)}, ["id"])
    for kind, name, url, interval in DEFAULTS:
        source_id = str(uuid5(NAMESPACE_URL, url))
        insert_if_missing(db, ExternalSource, {"id": source_id, "revision": 1, "data": {"id": source_id, "kind": kind, "display_name": name, "url": url, "enabled": True, "supplier_id": None, "official_domain": urlsplit(url).hostname, "ownership_verified": True, "poll_interval_minutes": interval, "last_success": None, "last_error": None, "stale": True, "revision": 1}}, ["id"])
    db.commit()


def reserve_fda_request(source_id):
    with SessionLocal() as db:
        # Updating a sentinel serializes global quota accounting on PostgreSQL AND SQLite.
        quota_lock = str(uuid5(NAMESPACE_URL, "bioerp:openfda-quota-lock"))
        result = db.execute(update(SourceRequest).where(SourceRequest.id == quota_lock).values(source_id="quota_lock"))
        if result.rowcount != 1:
            raise CollectionError("Source quota ledger is not initialized; restart the API")
        moment = now()
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        daily = db.scalar(select(func.count()).select_from(SourceRequest).where(SourceRequest.created_at >= start))
        minute = db.scalar(select(func.count()).select_from(SourceRequest).where(SourceRequest.created_at >= moment - timedelta(minutes=1)))
        if daily >= 900 or minute >= 200:
            raise CollectionError("openFDA safety rate limit reached; retry later")
        db.add(SourceRequest(source_id=source_id))
        db.commit()


def fda_date(value):
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat() if value else None
    except (ValueError, TypeError):
        return None


async def collect_fda(source):
    source_id = source.id
    results = {}
    source_updated = None
    async def query(search, skip=0):
        nonlocal source_updated
        reserve_fda_request(source_id)
        params = {"search": search, "sort": "report_date:desc", "limit": "100", "skip": str(skip)}
        if setting("FDA_API_KEY"):
            params["api_key"] = setting("FDA_API_KEY")
        url = str(httpx.URL("https://api.fda.gov/drug/enforcement.json", params=params))
        status, _, body, _ = await fetch(url)
        if status == 404:
            try:
                if json.loads(body).get("error", {}).get("code") == "NOT_FOUND":
                    return {"results": [], "meta": {"results": {"total": 0}}}
            except ValueError:
                pass
        if status != 200:
            raise CollectionError(f"openFDA request failed with HTTP {status}")
        response = json.loads(body)
        if not isinstance(response.get("results"), list):
            raise CollectionError("Invalid openFDA response")
        source_updated = response.get("meta", {}).get("last_updated")
        return response
    async def window(start, end):
        search = f"report_date:[{start:%Y%m%d} TO {end:%Y%m%d}]"
        first = await query(search)
        total = int(first.get("meta", {}).get("results", {}).get("total", 0))
        if total > 25000:
            if start == end:
                raise CollectionError("openFDA single-day result exceeds pagination limit")
            middle = start + (end - start) // 2
            await window(start, middle)
            await window(middle + timedelta(days=1), end)
            return
        for item in first.get("results", []):
            if item.get("recall_number"):
                results[item["recall_number"]] = item
        for skip in range(100, total, 100):
            page = await query(search, skip)
            for item in page["results"]:
                if item.get("recall_number"):
                    results[item["recall_number"]] = item
    end = now().date()
    await window(end - timedelta(days=89), end)
    with SessionLocal() as db:
        tracked = db.scalars(select(ExternalIssue.external_key).where(ExternalIssue.source_id == source_id)).all()
    for key in tracked:
        if key not in results:
            safe = key.replace('"', '').replace('\\', '')
            page = await query(f'recall_number:"{safe}"')
            for item in page.get("results", []):
                if item.get("recall_number"):
                    results[item["recall_number"]] = item
    items = []
    for key, raw in results.items():
        items.append((key, {"source_kind": "openfda", "source_url": "https://api.fda.gov/drug/enforcement.json", "publisher": "U.S. FDA", "published_at": fda_date(raw.get("report_date")), "occurred_at": fda_date(raw.get("recall_initiation_date")), "summary": excerpt(raw.get("reason_for_recall", "")), "title": excerpt(raw.get("product_description", "")), "recall_number": key, "event_id": raw.get("event_id"), "recalling_firm": raw.get("recalling_firm"), "code_info": raw.get("code_info"), "classification": raw.get("classification"), "status": raw.get("status"), "raw": raw}))
    return items, {"source_last_updated": source_updated}


async def collect_rss(source):
    data = source.data
    headers = {k: data[v] for k, v in (("If-None-Match", "etag"), ("If-Modified-Since", "last_modified")) if data.get(v)}
    status, response_headers, body, final_url = await fetch(data["url"], headers)
    if status == 304:
        return [], {"not_modified": True}
    if status != 200:
        raise CollectionError(f"Feed request failed with HTTP {status}")
    # Validate XML with entity expansion/external entities forbidden before permissive feed parsing.
    fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    feed = feedparser.parse(body)
    if feed.bozo and not feed.entries:
        raise CollectionError("Invalid RSS/Atom document")
    items = []
    for entry in feed.entries:
        link = urljoin(final_url, entry.get("link", ""))
        try:
            validate_url(link)
        except CollectionError:
            link = data["url"]
        summary = excerpt(entry.get("summary", entry.get("description", "")))
        key = entry.get("id") or entry.get("guid") or (link if entry.get("link") else None)
        if not key:
            key = hashlib.sha256(json.dumps({"title": entry.get("title"), "summary": summary}, sort_keys=True).encode()).hexdigest()
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        published = datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc).isoformat() if parsed else None
        items.append((str(key)[:500], {"source_kind": "rss", "source_url": link, "publisher": data["display_name"], "published_at": published, "occurred_at": None, "summary": summary, "title": excerpt(entry.get("title", "")), "raw": {"id": entry.get("id"), "link": link, "summary": summary, "summary_html": entry.get("summary", entry.get("description", "")), "title": entry.get("title", ""), "published": entry.get("published")}}))
    ttl = feed.feed.get("ttl")
    updates = {"etag": response_headers.get("etag"), "last_modified": response_headers.get("last-modified")}
    if str(ttl).isdigit():
        updates["feed_ttl_minutes"] = int(ttl)
    return items, updates


async def sync_source(source_id):
    with SessionLocal() as db:
        source = db.get(ExternalSource, source_id)
        if not source:
            raise CollectionError("Source not found")
        run = CollectionRun(source_id=source_id, data={})
        db.add(run)
        db.commit()
        run_id = run.id
        try:
            items, updates = await (collect_fda(source) if source.data["kind"] == "openfda" else collect_rss(source))
            changed = 0
            for key, item in items:
                content_hash = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                row = db.scalar(select(ExternalIssue).where(ExternalIssue.source_id == source_id, ExternalIssue.external_key == key))
                if row and row.content_hash == content_hash:
                    continue
                fetched = now().isoformat()
                item.update(fetched_at=fetched, source_status="available", verification_status="relevance_unconfirmed", source_reliability="official", severity="unknown", is_synthetic=False)
                if row:
                    item["id"] = row.id
                    item["verification_status"] = row.data.get("verification_status", "relevance_unconfirmed")
                    row.data, row.content_hash = item, content_hash
                else:
                    issue_id = uid()
                    item["id"] = issue_id
                    row = ExternalIssue(id=issue_id, source_id=source_id, external_key=key, content_hash=content_hash, data=item)
                    db.add(row)
                    db.flush()
                evidence = IssueEvidence(issue_id=row.id, data=item)
                db.add(evidence)
                db.flush()
                # A corrected source never rewrites old discussion snapshots. Linked ERP evidence
                # advances its own revision, forcing human re-review before any old recommendation.
                from .erp import lock_revision, audit, enqueue_recalculation
                linked = db.scalars(select(ERPRecord).where(ERPRecord.collection == "issues", ERPRecord.record_id == row.id)).all()
                for record in linked:
                    previous = record.data
                    lock_revision(db, record.scenario_id)
                    record.revision += 1
                    record.data = {**previous, **item, "links": previous.get("links", []), "verification_status": previous.get("verification_status", "relevance_unconfirmed"), "revision": record.revision, "latest_source_evidence_id": evidence.id, "source_changed_requires_review": True}
                    for field in ("material_id", "supplier_id", "lot_id", "purchase_order_id", "delay_days"):
                        if field in previous:
                            record.data[field] = previous[field]
                    audit(db, "external_collector", "issue.source_corrected", record.scenario_id, previous, record.data)
                    enqueue_recalculation(db, record.scenario_id)
                    for order in db.scalars(select(ERPRecord).where(ERPRecord.scenario_id == record.scenario_id, ERPRecord.collection == "purchase_orders")):
                        audit(db, "external_collector", "purchase_order.review_required", record.scenario_id, after={"id": order.record_id, "issue_id": row.id})
                changed += 1
            source.data = {**source.data, **updates, "last_success": now().isoformat(), "last_error": None, "stale": False}
            run.status, run.data = "completed", {"received": len(items), "changed": changed, "completed_at": now().isoformat()}
            db.commit()
        except Exception as exc:
            db.rollback()
            source, run = db.get(ExternalSource, source_id), db.get(CollectionRun, run_id)
            message = str(exc) if isinstance(exc, CollectionError) else f"Collection failed ({type(exc).__name__})"
            source.data = {**source.data, "last_error": message, "stale": True}
            run.status, run.data = "failed", {"error": message, "completed_at": now().isoformat()}
            db.commit()
        return {"id": run.id, "source_id": source_id, "status": run.status, "started_at": utc_iso(run.started_at), **run.data}


async def refresh_enabled():
    with SessionLocal() as db:
        ids = [s.id for s in db.scalars(select(ExternalSource)) if s.data.get("enabled")]
    outcomes = []
    for source_id in ids:
        outcomes.append(await sync_source(source_id))
    if any(r["status"] != "completed" for r in outcomes):
        raise CollectionError("Latest external-source verification failed; inspect source runs and retry approval")
    return outcomes
