import asyncio
import json
import httpx
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ExternalSource, ExternalIssue, IssueEvidence
from app.services import external_sources as service

RSS = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Official fixture</title><item><guid>notice-1</guid><title>Document revision</title><link>https://example.com/notices/1</link><description>&lt;p&gt;Document amended&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;</description><pubDate>Fri, 23 Oct 2026 12:00:00 +0900</pubDate></item></channel></rss>'''


def source_id(kind):
    with SessionLocal() as db:
        return next(s.id for s in db.scalars(select(ExternalSource)) if s.data["kind"] == kind)


def test_rss_deduplicates_and_preserves_correction_versions(client, monkeypatch):
    body = RSS
    async def fixture_fetch(url, headers=None):
        return 200, {"etag": '"fixture"'}, body, url
    monkeypatch.setattr(service, "fetch", fixture_fetch)
    sid = source_id("rss")
    assert asyncio.run(service.sync_source(sid))["changed"] == 1
    assert asyncio.run(service.sync_source(sid))["changed"] == 0
    body = RSS.replace(b"Document amended", b"Correction published")
    assert asyncio.run(service.sync_source(sid))["changed"] == 1
    with SessionLocal() as db:
        issues = db.scalars(select(ExternalIssue)).all()
        assert len(issues) == 1
        assert issues[0].data["verification_status"] == "relevance_unconfirmed"
        assert issues[0].data["summary"] == "Correction published"
        assert issues[0].data["published_at"] == "2026-10-23T03:00:00+00:00"
        assert len(db.scalars(select(IssueEvidence)).all()) == 2


def test_collection_failure_retains_previous_evidence(client, monkeypatch):
    async def fixture_fetch(url, headers=None):
        return 200, {}, RSS, url
    monkeypatch.setattr(service, "fetch", fixture_fetch)
    sid = source_id("rss")
    asyncio.run(service.sync_source(sid))
    async def unavailable(url, headers=None):
        return 429, {}, b"rate limited", url
    monkeypatch.setattr(service, "fetch", unavailable)
    result = asyncio.run(service.sync_source(sid))
    assert result["status"] == "failed"
    with SessionLocal() as db:
        assert db.scalars(select(ExternalIssue)).one().data["summary"] == "Document amended"
        source = db.get(ExternalSource, sid)
        assert source.data["last_success"] is not None
        assert source.data["stale"] is True
        assert "429" in source.data["last_error"]


def test_openfda_empty_404_and_raw_fields(client, monkeypatch):
    raw = {"recall_number": "R-FIXTURE", "event_id": "E-FIXTURE", "recalling_firm": "Official fixture firm", "product_description": "Fixture product", "reason_for_recall": "Document fixture", "code_info": "Unstructured lot text", "report_date": "20261023", "recall_initiation_date": None, "openfda": {}}
    async def fixture_fetch(url, headers=None):
        return 200, {}, json.dumps({"meta": {"results": {"total": 1}}, "results": [raw]}).encode(), url
    monkeypatch.setattr(service, "fetch", fixture_fetch)
    sid = source_id("openfda")
    result = asyncio.run(service.sync_source(sid))
    assert result["status"] == "completed"
    with SessionLocal() as db:
        issue = db.scalars(select(ExternalIssue)).one()
        assert issue.data["occurred_at"] is None
        assert issue.data["code_info"] == "Unstructured lot text"
        assert issue.data["raw"]["openfda"] == {}
        assert issue.data.get("lot_ids") is None
    async def empty(url, headers=None):
        return 404, {}, b'{"error":{"code":"NOT_FOUND","message":"No matches found!"}}', url
    monkeypatch.setattr(service, "fetch", empty)
    assert asyncio.run(service.sync_source(sid))["status"] == "completed"


def test_private_targets_credentials_and_entities_rejected(client, monkeypatch):
    for url in ("http://example.com/feed", "https://user:password@example.com/feed", "https://localhost/feed", "https://example.com:8443/feed"):
        with pytest.raises(service.CollectionError):
            service.validate_url(url)
    with pytest.raises(service.CollectionError):
        asyncio.run(service.public_addresses("https://127.0.0.1/feed"))
    async def malicious_xml(url, headers=None):
        return 200, {}, b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><title>&x;</title></channel></rss>', url
    monkeypatch.setattr(service, "fetch", malicious_xml)
    result = asyncio.run(service.sync_source(source_id("rss")))
    assert result["status"] == "failed"


def test_fetch_pins_dns_and_rechecks_redirect_targets(client, monkeypatch):
    real_client = httpx.AsyncClient
    real_resolver = service.public_addresses
    observed = []
    async def resolver(url):
        if "127.0.0.1" in url:
            return await real_resolver(url)
        return "example.com", ["93.184.216.34"]
    def handler(request):
        observed.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})
    monkeypatch.setattr(service, "public_addresses", resolver)
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(service.CollectionError):
        asyncio.run(service.fetch("https://example.com/feed"))
    assert len(observed) == 1
    assert observed[0].url.host == "93.184.216.34"
    assert observed[0].headers["host"] == "example.com"
    assert observed[0].extensions["sni_hostname"] == "example.com"
