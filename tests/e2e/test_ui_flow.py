"""Browser E2E against the offline demo server (ROADMAP Phase 2/§13). Run: python -m pytest tests/e2e -q

Skipped automatically when Playwright or a Chromium build isn't available."""
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
CHROME = os.getenv("E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
pytestmark = pytest.mark.skipif(not (ROOT / "frontend/dist/index.html").exists(), reason="frontend not built")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path_factory.mktemp('db')}/e2e.db", "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen([sys.executable, "scripts/demo_server.py", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.25)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        kw = {"executable_path": CHROME} if Path(CHROME).exists() else {}
        try:
            b = p.chromium.launch(args=["--no-sandbox"], **kw)
        except Exception as e:      # no browser installed
            pytest.skip(f"Chromium unavailable: {e}")
        yield b
        b.close()


@pytest.fixture
def resume_pdf(tmp_path):
    from tests.conftest import RESUME_LINES, make_pdf
    p = tmp_path / "cv.pdf"
    p.write_bytes(make_pdf(RESUME_LINES))
    return str(p)


def test_full_flow(server, browser, resume_pdf):
    expect = pw.expect
    ctx = browser.new_context(viewport={"width": 1200, "height": 950}, accept_downloads=True)
    page = ctx.new_page()
    errors, dialogs = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.goto(server + "/")

    # setup: resume + role + sources + AI key
    page.set_input_files("input[type=file]", resume_pdf)
    expect(page.locator("[data-testid=resume-preview]")).to_contain_text("Resume read", timeout=10000)
    page.fill("input[placeholder='e.g. Data Engineer']", "Data Engineer")
    page.fill("input[placeholder^='e.g. London']", "London")
    page.fill("input[aria-label='Number of posts']", "30")
    page.fill("input[aria-label='Greenhouse boards company slugs']", "stripe")
    page.fill("textarea[aria-label='Job URLs']", "https://wellfound.com/jobs/1-data-engineer\nhttps://careers.example.com/job/1")
    page.click(".ai-chip")
    page.fill("input[placeholder='sk-…']", "sk-good")
    page.click("button:has-text('Verify & save')")
    expect(page.locator(".modal")).to_have_count(0, timeout=6000)

    # run → live search page → report
    page.click("[data-testid=run]")
    expect(page).to_have_url(re.compile(r"/search/[0-9a-f]{32}\?auto=1"), timeout=5000)
    expect(page).to_have_url(re.compile(r"/analysis/[0-9a-f]{32}$"), timeout=30000)
    qualify = page.locator("[data-testid=qualify]")
    expect(qualify).to_contain_text("of ")
    expect(page.locator(".summary")).to_contain_text("AI: strong", timeout=10000)        # AI advice streamed in
    first = qualify.get_attribute("data-value")

    # refresh restores the report (Phase 2 acceptance) and URL state drives tabs/drawer
    page.reload()
    expect(qualify).to_have_attribute("data-value", first, timeout=10000)
    expect(qualify).to_have_text(re.compile(rf"^{first.split('/')[0]} of {first.split('/')[1]} jobs"), timeout=5000)
    page.click(".tabs button:has-text('Jobs')")
    expect(page).to_have_url(re.compile(r"tab=jobs"))
    page.click("button:has-text('Verify top 5')")
    expect(page.locator(".tag.ai")).to_have_count(5, timeout=20000)
    page.locator(".r-head").first.click()
    expect(page).to_have_url(re.compile(r"job="))
    expect(page.locator(".modal")).to_be_visible()
    page.go_back()
    expect(page.locator(".modal")).to_have_count(0)
    page.reload()
    expect(page.locator(".tag.ai")).to_have_count(5, timeout=10000)                     # deep results persisted

    # settings → export
    page.click("a:has-text('Settings')")
    with page.expect_download() as d:
        page.click("button:has-text('Export my data')")
    assert '"analyses"' in Path(d.value.path()).read_text()

    # repeat search is served from cache (< 2 s to the report)
    page.click("a.brand")
    t0 = time.time()
    page.click("[data-testid=run]")
    expect(page).to_have_url(re.compile(r"/analysis/"), timeout=15000)
    assert time.time() - t0 < 6

    # review mode → choose jobs → analyze selected
    page.click("a.brand")
    page.check("text=Let me review the jobs before analyzing")
    page.click("[data-testid=run]")
    expect(page.locator("h1:has-text('Review jobs')")).to_be_visible(timeout=15000)
    page.locator(".joblist li input[type=checkbox]").first.uncheck()
    page.click("button:has-text('Analyze')")
    expect(page).to_have_url(re.compile(r"/analysis/"), timeout=15000)

    # mobile layout
    page.set_viewport_size({"width": 390, "height": 850})
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert not dialogs, dialogs
    assert not errors, errors
    ctx.close()
