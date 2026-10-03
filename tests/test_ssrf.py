"""ROADMAP D1: user-supplied job URLs must never reach the server's own network."""
import httpx
import pytest

from app.net import safe_fetch
from app.net.safe_fetch import UnsafeURL, check_url, safe_get
from app.sources import BY_ID, JobQuery
from app.sources.base import SourceError

BLOCKED = [
    "http://127.0.0.1/api/config", "http://127.0.0.1:8000/api/config", "http://localhost/", "http://LOCALHOST./x",
    "http://10.0.0.1/", "http://192.168.1.10/", "http://172.20.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.1/", "http://0.0.0.0/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[::ffff:7f00:1]/",
    "http://[fe80::1]/", "http://[2002:7f00:1::]/", "http://internal.corp.example/", "http://metadata.example/",
    "http://rebind.example/", "http://example.com:22/", "http://example.com:8080/", "ftp://example.com/",
    "file:///etc/passwd", "http:///nohost", "http://app.internal/", "http://printer.local/",
]


@pytest.mark.parametrize("url", BLOCKED)
async def test_blocked_urls(url):
    with pytest.raises(UnsafeURL):
        await check_url(url)


@pytest.mark.parametrize("url", ["https://example.com/jobs/1", "http://example.com:80/x", "https://example.com:443/",
                                 "https://jobs.lever.co/acme/123", "https://[2606:4700:4700::1111]/"])
async def test_public_urls_allowed(url):
    await check_url(url)


async def test_redirect_to_private_is_blocked_at_the_hop():
    hits = []

    def handler(request):
        hits.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text="SECRET")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(UnsafeURL):
            await safe_get(c, "https://example.com/job")
    assert hits == ["https://example.com/job"]          # the private address was never requested


async def test_redirect_chain_limit_and_size_cap(monkeypatch):
    def loop(request):
        return httpx.Response(302, headers={"location": "/again"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(loop)) as c:
        with pytest.raises(UnsafeURL, match="redirects"):
            await safe_get(c, "https://example.com/start")
    monkeypatch.setattr(safe_fetch, "MAX_BYTES", 1000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x" * 5000))) as c:
        with pytest.raises(UnsafeURL, match="too large"):
            await safe_get(c, "https://example.com/big")


async def test_public_redirect_followed():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.org/new"})
        return httpx.Response(200, text="ok")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await safe_get(c, "https://example.com/old")
    assert r.status == 200 and r.url == "https://example.org/new" and r.text == "ok"


async def test_url_source_rejects_internal_targets_without_requesting_them():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, text='{"max_jobs": 100}')
    q = JobQuery(title="x", urls=["http://127.0.0.1:8000/api/config", "http://169.254.169.254/latest/meta-data/"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(SourceError) as e:
            await BY_ID["urls"].fetch(q, c)
    msg = str(e.value).lower()
    assert requested == []
    assert "port" in msg and "public website" in msg     # 127.0.0.1:8000 → bad port; metadata IP → not public


async def test_non_job_pages_are_not_imported_as_descriptions():
    page = "<html><head><title>Admin</title></head><body><main>" + "<p>internal dashboard metrics and logs</p>" * 40 + "</main></body></html>"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=page))) as c:
        with pytest.raises(SourceError, match="Couldn't find a job posting"):
            await BY_ID["urls"].fetch(JobQuery(title="x", urls=["https://example.com/admin"]), c)


async def test_api_end_to_end_ssrf_attempt(monkeypatch):
    """The exact repro from the roadmap: the server must not call itself."""
    from httpx import ASGITransport, AsyncClient
    from app import main
    from app.sources import aggregate
    real = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text="should never be fetched")
    monkeypatch.setattr(aggregate, "httpx", type("H", (), {"AsyncClient": staticmethod(lambda **kw: real(transport=httpx.MockTransport(handler))),
                                                          "Timeout": httpx.Timeout}))
    import asyncio
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t") as c:
        sid = (await c.post("/api/search", json={"title": "data engineer", "sources": ["urls"],
                                                 "urls": ["http://127.0.0.1:8000/api/config"]})).json()["search_id"]
        for _ in range(50):
            s = (await c.get(f"/api/search/{sid}")).json()
            if s["status"] != "running":
                break
            await asyncio.sleep(0.02)
    assert seen == [] and s["status"] == "error" and "port" in s["error"].lower()
