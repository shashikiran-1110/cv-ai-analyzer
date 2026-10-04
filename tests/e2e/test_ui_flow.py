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
    log = open(tmp_path_factory.mktemp("log") / "server.log", "w")       # a file, so a chatty server never blocks
    proc = subprocess.Popen([sys.executable, "scripts/demo_server.py", str(port)], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.25)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)
    log.close()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        kw = {"executable_path": CHROME} if CHROME and Path(CHROME).is_file() else {}
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
    expect(page.locator(".link-list li")).to_have_count(2, timeout=6000)                 # saved server-side until discarded
    expect(page.locator("textarea[aria-label='Job URLs']")).to_have_value("")
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
    expect(page.locator("[data-testid=strategy]")).to_contain_text("Apply now", timeout=15000)
    expect(page.locator("[data-testid=strategy]")).not_to_contain_text("demo-invented-id")   # invented id dropped by the server
    expect(page.locator("[data-testid=career-report]")).to_contain_text("Analytics Engineer")
    first = qualify.get_attribute("data-value")

    # refresh restores the report (Phase 2 acceptance) and URL state drives tabs/drawer
    page.reload()
    expect(qualify).to_have_attribute("data-value", first, timeout=10000)
    expect(qualify).to_have_text(re.compile(rf"^{first.split('/')[0]} of {first.split('/')[1]} jobs"), timeout=5000)
    page.click(".tabs button:has-text('Jobs')")
    expect(page).to_have_url(re.compile(r"tab=jobs"))
    # jobs analytics: "where you qualify" / near-miss titles open the posting on its portal in a new tab
    link = page.locator("[data-testid=where-qualify] a.q-title").first
    expect(link).to_have_attribute("target", "_blank")
    assert link.get_attribute("href").startswith("http")
    page.click("button:has-text('Verify top 5')")
    expect(page.locator(".tag.ai")).to_have_count(5, timeout=20000)
    page.locator(".r-head").first.click()
    expect(page).to_have_url(re.compile(r"job="))
    expect(page.locator(".modal")).to_be_visible()
    # requirement matrix (Phase 4): rows link to highlighted lines in the posting
    expect(page.locator(".matrix tbody tr").first).to_be_visible()
    page.locator(".matrix tbody tr").first.click()
    expect(page.locator("[data-testid=posting] mark.pl").first).to_be_visible(timeout=5000)
    page.go_back()
    expect(page.locator(".modal")).to_have_count(0)
    page.reload()
    expect(page.locator(".tag.ai")).to_have_count(5, timeout=10000)                     # deep results persisted
    expect(page.locator("[data-testid=ai-spend]")).to_contain_text("call", timeout=5000)  # AI spend is shown

    # AI requirement lists (Phase 3 extractor): invented items are dropped server-side
    page.click("button:has-text('AI requirement lists')")
    expect(page.locator(".toast", has_text="AI requirement lists in use")).to_have_count(1, timeout=15000)

    # hard requirements are reported separately from the score (Phase 4 gates)
    page.click(".tabs button:has-text('Overview')")
    expect(page.locator("[data-testid=gated]")).to_contain_text("hard requirement", timeout=5000)
    page.click(".tabs button:has-text('Jobs')")
    expect(page.locator(".tag.gate").first).to_be_visible()

    # profile review: add a skill the resume doesn't show, save, and the report re-scores with it
    page.click(".tabs button:has-text('Skills')")
    expect(page.locator(".card:has(h2:has-text('Skill gaps')) .learn-head span", has_text="Kubernetes")).to_have_count(1)
    page.click(".tabs button:has-text('Overview')")
    report_url = page.url
    page.click("a:has-text('Review what was read')")
    expect(page.locator("h1#h-profile")).to_be_visible(timeout=10000)
    expect(page.locator(".timeline > li")).to_have_count(1)
    page.fill(".profile-page input[placeholder^='Add a skill']", "Kubernetes")
    page.keyboard.press("Enter")
    page.click("button:has-text('Save corrections')")
    expect(page.locator(".toast", has_text="Profile saved")).to_have_count(1, timeout=5000)
    page.click("a:has-text('Back to report')")
    expect(page).to_have_url(re.compile(r"/analysis/[0-9a-f]{32}"), timeout=5000)
    expect(page).not_to_have_url(re.compile(r"rescore"), timeout=5000)
    page.click(".tabs button:has-text('Skills')")
    expect(page.locator(".card:has(h2:has-text('Skill gaps')) .learn-head span", has_text="Kubernetes")).to_have_count(0, timeout=8000)
    page.goto(report_url)

    # tailoring agent: guarded edits, a question, projected score, .docx export (Phase 5)
    page.click(".tabs button:has-text('Jobs')")
    page.locator(".r-head").first.click()
    page.click("[data-testid=open-tailor]")
    expect(page.locator("h1#h-tailor")).to_be_visible(timeout=10000)
    page.click("[data-testid=start-tailor]")
    expect(page.locator("[data-testid=agent-question]")).to_be_visible(timeout=15000)
    expect(page.locator(".diff.bad .violations")).to_contain_text("Kubernetes")          # fabricated edit is blocked
    page.fill("[data-testid=agent-question] textarea", "Runs got about 35% faster")
    page.click("button:has-text('Send answer')")
    expect(page.locator(".final")).to_contain_text("Summary", timeout=15000)
    expect(page.locator(".diff.on textarea").first).to_have_value(re.compile("35%"))
    expect(page.locator("[data-testid=docx]")).to_be_enabled(timeout=5000)
    with page.expect_download() as dl:
        page.click("[data-testid=docx]")
    assert dl.value.suggested_filename.endswith(".docx")

    # interview practice
    page.go_back()
    expect(page.locator(".modal")).to_be_visible(timeout=5000)
    page.click("a:has-text('Practice interview')")
    page.click("[data-testid=gen-questions]")
    page.locator(".qlist .q").first.click()
    page.fill("textarea[aria-label='Your answer']", "I built ETL pipelines in Python and SQL on AWS with Airflow at Acme Analytics.")
    page.click("[data-testid=get-feedback]")
    expect(page.locator("[data-testid=feedback]").first).to_contain_text("Stronger version", timeout=10000)
    expect(page.locator(".feedback .violations").first).to_contain_text("35%")         # invented number flagged

    # coach with tools: numbers it can't back up are flagged
    page.goto(report_url.split("?")[0] + "?tab=assistant")
    page.fill("textarea[aria-label='Message']", "How can I qualify for more jobs?")
    page.keyboard.press("Enter")
    expect(page.locator(".bubble.assistant")).to_contain_text("Where you stand", timeout=15000)
    expect(page.locator("[data-testid=unverified]")).to_contain_text("99")

    # jobs table: bulk-select two rows and compare them; full job page with the posting beside the analysis
    page.goto(report_url.split("?")[0] + "?tab=jobs")
    boxes = page.locator("table.dt tbody tr input[type=checkbox]")
    boxes.nth(0).check()
    boxes.nth(1).check()
    expect(page.locator(".bulkbar")).to_contain_text("2 selected")
    page.click(".bulkbar button:has-text('Compare')")
    expect(page.locator("h1#h-compare")).to_contain_text("Compare 2 jobs", timeout=5000)
    page.locator(".cmp thead a").first.click()
    expect(page.locator("h1#h-job")).to_be_visible(timeout=5000)
    expect(page.locator(".split [data-testid=posting]")).to_be_visible(timeout=5000)
    page.locator(".matrix tbody tr").first.click()
    # a requirement-status correction re-scores the job and is logged as feedback
    page.locator(".matrix tbody tr").first.locator("select[aria-label='Correct this status']").select_option(index=1)
    expect(page.locator(".toast", has_text="the score was updated")).to_have_count(1, timeout=5000)

    # command palette: jump to a page by typing
    page.keyboard.press("Control+k")
    expect(page.locator(".cmdk")).to_be_visible()
    page.keyboard.type("Reports")
    page.keyboard.press("Enter")
    expect(page.locator("h1#h-reports")).to_be_visible(timeout=5000)
    expect(page.locator(".list > li").first).to_be_visible()

    # Eval Studio: defense invariants and a mock run from the UI
    page.click(".side-nav a:has-text('Eval Studio')")
    expect(page.locator("h1#h-eval")).to_be_visible(timeout=5000)
    page.locator("tr:has-text('llm_safety') button:has-text('Mock')").click()
    expect(page.locator(".toast", has_text="llm_safety")).to_have_count(1, timeout=30000)
    page.click(".tabs button:has-text('Labelling')")
    expect(page.locator(".label-btns")).to_be_visible(timeout=5000)

    # Phase 6: save to tracker, watch this search, kanban, watches, market
    page.goto(report_url.split("?")[0] + "?tab=jobs")
    page.locator(".r-head").first.click()
    page.click("[data-testid=save-tracker]")
    expect(page.locator(".toast", has_text="Saved to your tracker")).to_have_count(1, timeout=5000)
    page.keyboard.press("Escape")
    page.click("[data-testid=watch-search]")
    expect(page.locator(".toast", has_text="Watching this search")).to_have_count(1, timeout=5000)
    page.click(".side-nav a:has-text('Applications')")
    expect(page.locator(".kcol[data-stage=saved] [data-testid=kcard]")).to_have_count(1, timeout=5000)
    page.locator("[data-testid=kcard] button[aria-label='Move right']").first.click()
    expect(page.locator(".kcol[data-stage=applied] [data-testid=kcard]")).to_have_count(1, timeout=5000)
    page.reload()
    expect(page.locator(".kcol[data-stage=applied] [data-testid=kcard]")).to_have_count(1, timeout=5000)   # persisted
    page.click(".side-nav a:has-text('Watches')")
    expect(page.locator("[data-testid=watch]")).to_have_count(1, timeout=5000)
    page.click("[data-testid=watch] button:has-text('Run now')")
    expect(page.locator("[data-testid=watch] .digest")).to_contain_text("new of", timeout=15000)
    page.click(".side-nav a:has-text('Market')")
    page.fill("input[aria-label='Role']", "Data Engineer")
    page.click("button:has-text('Analyse')")
    expect(page.locator("[data-testid=market]")).to_contain_text("postings", timeout=8000)

    # settings: magic-link sign-in (demo shows the link), extension token, export
    page.click(".side-nav a:has-text('Settings')")
    page.fill("input[aria-label='Email']", "demo@example.com")
    page.click("button:has-text('Email me a sign-in link')")
    page.click("[data-testid=dev-link]")
    expect(page.locator("[data-testid=account]")).to_contain_text("Signed in as demo@example.com", timeout=8000)
    page.click("button:has-text('Create extension token')")
    expect(page.locator("[data-testid=ext-token]")).to_contain_text("cvx_")
    with page.expect_download() as d:
        page.click("button:has-text('Export my data')")
    assert '"analyses"' in Path(d.value.path()).read_text()

    # repeat search is served from cache (< 2 s to the report)
    page.click("a.brand")
    t0 = time.time()
    page.click("[data-testid=run]")
    expect(page).to_have_url(re.compile(r"/analysis/"), timeout=15000)
    assert time.time() - t0 < 6

    # search planner: AI plan, unrelated title dropped, plan applied to the form
    page.click("a.brand")
    page.fill("input[aria-label='Describe the role']", "data engineer in London, hybrid")
    page.click("button:has-text('Plan with AI')")
    expect(page.locator("[data-testid=plan]")).to_contain_text("Analytics Engineer", timeout=8000)
    expect(page.locator("[data-testid=plan] .chip.ok", has_text="Florist")).to_have_count(0)
    expect(page.locator("[data-testid=plan]")).to_contain_text("Dropped as a different job: Florist")
    page.click("button:has-text('Use this plan')")
    expect(page.locator(".plan-card")).to_contain_text("Plan active")

    # review mode → choose jobs → analyze selected
    page.click("a.brand")
    page.check("text=Let me review the jobs before analyzing")
    page.click("[data-testid=run]")
    expect(page.locator("h1:has-text('Review jobs')")).to_be_visible(timeout=15000)
    page.locator(".joblist li input[type=checkbox]").first.uncheck()
    page.click("button:has-text('Analyze')")
    expect(page).to_have_url(re.compile(r"/analysis/"), timeout=15000)

    # saved links persist across a reload; Clear session discards this tab's data
    page.goto(server + "/")
    expect(page.locator(".link-list li")).to_have_count(2, timeout=6000)
    page.click("[data-testid=clear-session]")
    page.click("[data-testid=confirm-clear]")
    expect(page.locator(".toast", has_text="Session cleared")).to_have_count(1, timeout=5000)
    expect(page.locator("[data-testid=resume-preview]")).to_have_count(0)
    expect(page.locator("input[placeholder='e.g. Data Engineer']")).to_have_value("")

    # mobile layout
    page.set_viewport_size({"width": 390, "height": 850})
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert not dialogs, dialogs
    assert not errors, errors
    ctx.close()


def test_extension_extractor_reads_jobposting(server, browser):
    """The extension's page reader (extension/extract.js) on a page with schema.org JobPosting, and without."""
    page = browser.new_page()
    ld = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {"@type": "JobPosting", "title": "Data Engineer",
          "description": "<p>Requirements</p><ul><li>Python and SQL</li></ul>" + "<p>more</p>" * 10,
          "hiringOrganization": {"name": "Acme"}, "jobLocation": {"address": {"addressLocality": "London", "addressCountry": "GB"}}}]}
    import json as _json
    page.set_content(f'<html><head><script type="application/ld+json">{_json.dumps(ld)}</script></head><body><h1>x</h1></body></html>')
    page.add_script_tag(path=str(ROOT / "extension/extract.js"))
    job = page.evaluate("cvmExtractJob()")
    assert job["title"] == "Data Engineer" and job["company"] == "Acme" and job["location"] == "London, GB"
    assert "Python and SQL" in job["description"] and job["method"] == "jobposting"
    page.set_content("<html><body><h1>Backend Engineer</h1><main>" + "We need Go and Postgres. " * 20 + "</main></body></html>")
    page.add_script_tag(path=str(ROOT / "extension/extract.js"))
    job = page.evaluate("cvmExtractJob()")
    assert job["title"] == "Backend Engineer" and job["method"] == "page-text" and "Postgres" in job["description"]
    page.close()
