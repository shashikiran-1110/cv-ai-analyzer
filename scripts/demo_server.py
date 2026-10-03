"""Demo server: the real app with every external service faked locally (no network needed).

    python scripts/demo_server.py [port]        # default 8765

- Job portals (LinkedIn, Remotive, RemoteOK, Arbeitnow, Jobicy, Himalayas, The Muse, Greenhouse, Lever, Ashby,
  Adzuna) answer with canned data in each API's real response format, so the full ingestion pipeline
  (filters, dedupe, ranking) runs for real. Wellfound URLs return 403, like the real site usually does.
- AI settings: provider OpenAI, key `sk-good`, model `gpt-5.6-luna` (anything else is rejected).
  The fake model deliberately returns one fabricated evidence quote in deep checks so you can see the
  server-side verification downgrade it.
- Adzuna: App ID `demo`, any App Key.
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

import os  # noqa: E402
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(__file__).resolve().parent.parent}/data/demo.db")
import httpx  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402

from app import config, linkedin, main  # noqa: E402
from app.net import safe_fetch  # noqa: E402
from app.jobmodel import Job  # noqa: E402
from app.sources import aggregate  # noqa: E402
from app.sources.sample import sample_jobs  # noqa: E402

config.OPENAI_BASE_URL = f"http://127.0.0.1:{PORT}/fake-openai/v1"
NOW = datetime.now(timezone.utc)
SAMPLES = sample_jobs()


def iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def html(desc: str) -> str:
    out = []
    for line in desc.splitlines():
        line = line.strip()
        if line.startswith("•"):
            out.append(f"<li>{line[1:].strip()}</li>")
        elif line:
            out.append(f"<p>{line}</p>")
    return "".join(out)


def pick(i: int):
    return SAMPLES[i % len(SAMPLES)]


# ---------- fake LinkedIn ----------
async def fake_linkedin(title, location, count, hours=None, on_progress=None, client=None, **kw):
    print("linkedin search:", title, location, count, hours, {k: v for k, v in kw.items() if k != "warnings"}, flush=True)
    out = []
    for i in range(count):
        s = pick(i)
        if on_progress:
            await on_progress("searching", i + 1, count)
        await asyncio.sleep(0.03)
        out.append(Job(id=str(4000 + i), title=s.title, company=f"{s.company} (LI {i})", location=s.location,
                       url=f"https://www.linkedin.com/jobs/view/{4000 + i}", posted=iso(i), seniority="Mid-Senior level",
                       description=s.description if i % 9 != 8 else "", employment_type=s.employment_type))
    for i in range(count):
        if on_progress:
            await on_progress("details", i + 1, count)
        await asyncio.sleep(0.01)
    return out


async def fake_probe(client=None):
    return {"ok": True, "message": "LinkedIn is reachable (demo)."}

linkedin.search_jobs = fake_linkedin
linkedin.probe = fake_probe


# ---------- fake portal APIs (real response shapes) ----------
def portal(request: httpx.Request) -> httpx.Response:
    h, path, p = request.url.host, request.url.path, request.url.params
    if h == "remotive.com":
        return httpx.Response(200, json={"jobs": [{"id": 100 + i, "url": f"https://remotive.com/j/{i}", "title": s.title,
            "company_name": s.company + " Remote", "candidate_required_location": "Worldwide", "publication_date": iso(5 + i)[:19],
            "description": html(s.description), "job_type": "full_time", "tags": []} for i, s in enumerate(SAMPLES)]})
    if h == "remoteok.com":
        return httpx.Response(200, json=[{"legal": "demo"}] + [{"id": str(200 + i), "position": s.title, "company": s.company,
            "location": "Remote", "date": iso(10 + i), "description": html(s.description), "tags": [],
            "url": f"https://remoteok.com/remote-jobs/{200 + i}"} for i, s in enumerate(SAMPLES[:8])])
    if h == "www.arbeitnow.com":
        return httpx.Response(200, json={"data": [{"slug": f"an-{i}", "company_name": s.company + " GmbH", "title": s.title,
            "description": html(s.description), "remote": i % 2 == 0, "url": f"https://arbeitnow.com/{i}", "tags": [],
            "job_types": ["full time"], "location": "Berlin" if i % 2 else "London", "created_at": int((NOW - timedelta(hours=20)).timestamp())}
            for i, s in enumerate(SAMPLES)], "links": {"next": None}})
    if h == "jobicy.com":
        return httpx.Response(200, json={"jobs": [{"id": 300 + i, "url": f"https://jobicy.com/{i}", "jobTitle": s.title,
            "companyName": s.company + " Labs", "jobGeo": "Europe", "jobType": ["full-time"], "pubDate": iso(30)[:19].replace("T", " "),
            "jobDescription": html(s.description), "jobLevel": "Mid"} for i, s in enumerate(SAMPLES[:6])]})
    if h == "himalayas.app":
        return httpx.Response(200, json={"jobs": [{"title": s.title, "companyName": s.company + " Co", "locationRestrictions": ["United Kingdom"],
            "description": html(s.description), "pubDate": int((NOW - timedelta(hours=40)).timestamp()), "applicationLink": f"https://himalayas.app/j/{i}",
            "guid": f"g{i}", "employmentType": "Full Time", "seniority": ["Mid-level"], "categories": []} for i, s in enumerate(SAMPLES[:6])]})
    if h == "www.themuse.com":
        page = int(p.get("page", 0))
        rows = [] if page > 0 else [{"id": 500 + i, "name": s.title, "contents": html(s.description), "publication_date": iso(50),
            "locations": [{"name": "London, United Kingdom"}], "levels": [{"name": "Mid Level"}], "company": {"name": s.company + " Group"},
            "refs": {"landing_page": f"https://themuse.com/j/{i}"}} for i, s in enumerate(SAMPLES[:6])]
        return httpx.Response(200, json={"results": rows, "page_count": 1})
    if h == "boards-api.greenhouse.io":
        slug = path.split("/")[3]
        return httpx.Response(200, json={"jobs": [{"id": 600 + i, "title": s.title, "location": {"name": "London"},
            "absolute_url": f"https://boards.greenhouse.io/{slug}/jobs/{600 + i}", "updated_at": iso(12),
            "content": html(s.description).replace("<", "&lt;").replace(">", "&gt;")} for i, s in enumerate(SAMPLES[:5])]})
    if h == "api.lever.co":
        slug = path.split("/")[3]
        if slug == "missing":
            return httpx.Response(404)
        return httpx.Response(200, json=[{"id": f"lv{i}", "text": s.title, "categories": {"location": "London", "commitment": "Full-time"},
            "descriptionPlain": s.description, "lists": [], "hostedUrl": f"https://jobs.lever.co/{slug}/lv{i}",
            "createdAt": int((NOW - timedelta(hours=8)).timestamp() * 1000), "workplaceType": "hybrid"} for i, s in enumerate(SAMPLES[:5])])
    if h == "api.ashbyhq.com":
        return httpx.Response(200, json={"jobs": [{"id": f"as{i}", "title": s.title, "location": "Remote - UK", "isRemote": True,
            "descriptionPlain": s.description, "publishedAt": iso(15), "jobUrl": f"https://jobs.ashbyhq.com/x/as{i}",
            "employmentType": "FullTime"} for i, s in enumerate(SAMPLES[:5])]})
    if h == "api.adzuna.com":
        if p.get("app_id") != "demo":
            return httpx.Response(401, json={"exception": "AUTH_FAIL"})
        return httpx.Response(200, json={"results": [{"id": f"az{i}", "title": s.title, "description": s.description[:480] + "…",
            "company": {"display_name": s.company + " Ltd"}, "location": {"display_name": "London, UK"}, "created": iso(3),
            "redirect_url": f"https://adzuna.example/{i}", "contract_time": "full_time"} for i, s in enumerate(SAMPLES[:8])]})
    if h.endswith("wellfound.com"):
        return httpx.Response(403, text="<html>Please verify you are a human</html>")
    # any other URL: a career page with schema.org JobPosting
    s = SAMPLES[0]
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": s.title, "description": html(s.description),
          "hiringOrganization": {"@type": "Organization", "name": "Career Page Co"}, "datePosted": NOW.date().isoformat(),
          "jobLocation": {"address": {"addressLocality": "London", "addressCountry": "GB"}}}
    return httpx.Response(200, text=f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body></body></html>')


_real_client = httpx.AsyncClient


class _HttpxProxy:
    """Stands in for the httpx module inside one app module only, routing its clients to a mock transport."""
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(httpx, name)

    def AsyncClient(self, **kw):
        kw.pop("transport", None)
        return _real_client(transport=httpx.MockTransport(self._handler), **kw)


aggregate.httpx = _HttpxProxy(portal)                                          # source aggregator
main.httpx = _HttpxProxy(lambda r: httpx.Response(200, text="ok"))            # connection check


async def _demo_resolve(host, port):   # offline DNS: every hostname is "public"; IP literals are still checked
    return ["93.184.216.34"]

safe_fetch.resolve = _demo_resolve


# ---------- fake OpenAI ----------
@main.app.get("/fake-openai/v1/models/{model}")
async def fm(model: str, request: Request):
    key = request.headers.get("authorization", "")
    if key != "Bearer sk-good":
        return JSONResponse({"error": {"message": f"Incorrect API key provided: {key[7:]}"}}, 401)
    if model != "gpt-5.6-luna":
        return JSONResponse({"error": {"message": f"The model `{model}` does not exist"}}, 404)
    return {"id": model}


def _deep_answer(prompt: str) -> dict:
    """Deep Verifier v2 protocol: judge the listed requirement ids. Deliberately includes one fabricated quote and
    one real-but-irrelevant quote so the server-side verification is visible in the demo."""
    resume = prompt.split("<resume>", 1)[-1].split("</resume>", 1)[0]
    lines = [l.strip() for l in resume.splitlines() if len(l.split()) >= 6]
    reqs = re.findall(r"^- \[(r\d+)\] \((?:must|nice)\) (.+)$", prompt, re.M)
    out = []
    for i, (rid, text) in enumerate(reqs):
        words = set(re.findall(r"[a-z]{3,}", text.lower()))
        quote = next((l for l in lines if words & set(re.findall(r"[a-z]{3,}", l.lower()))), "")
        if i == 1:
            out.append({"id": rid, "status": "met", "evidence": "Led a global team of 40 engineers across five continents",
                        "note": "(demo: fabricated quote, will be rejected)"})
        elif i == 2 and lines:
            out.append({"id": rid, "status": "met", "evidence": lines[-1][:120], "note": "(demo: real but unrelated quote)"})
        elif quote:
            out.append({"id": rid, "status": "met", "evidence": " ".join(quote.split()[:20]), "note": "Shown on the resume."})
        else:
            out.append({"id": rid, "status": "missing", "evidence": "", "note": "Not shown on the resume."})
    return {"verdict": "possible", "summary": "Demo assessment of the engine's requirement checklist.", "assessments": out}


def _extract_answer(prompt: str) -> dict:
    """Requirement extractor protocol: the posting's bullet lines, plus one invented item the server must drop."""
    job = prompt.split("<job>", 1)[-1].split("</job>", 1)[0]
    items, section = [], "must"
    for line in job.splitlines():
        t = line.strip()
        if re.match(r"(?i)^(nice to have|preferred|bonus)", t):
            section = "nice"
        if re.match(r"^[-•*]\s+", t):
            items.append({"text": re.sub(r"^[-•*]\s+", "", t), "importance": section, "kind": "skill", "years": 0})
    items.append({"text": "Security clearance at TS/SCI level", "importance": "must", "kind": "other", "years": 0})
    return {"requirements": items[:25]}


def _json_reply(obj: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(obj)}}], "usage": {"prompt_tokens": 900, "completion_tokens": 200}}


def _calls(*calls) -> dict:
    tc = [{"id": f"call_{i}_{n}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": tc}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 120}}


def _agent_reply(body: dict) -> dict:
    """Scripted agents: tailoring (with one fabricated edit the claim guard must catch) and the coach."""
    names = {t["function"]["name"] for t in body["tools"]}
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    turns = len(tool_msgs)
    if "propose_edit" in names:
        outputs = [json.loads(m["content"]) for m in tool_msgs if m["content"].startswith("{")]
        section = next((o for o in outputs if "items" in o), {"items": []})
        bullets = [b for it in section["items"] for b in it["bullets"]]
        answered = any("user_answer" in o for o in outputs)
        if turns == 0:
            return _calls(("get_job_requirements", {}), ("get_profile_section", {"section": "experience"}))
        if not bullets:
            return _calls(("finish", {"summary": "No experience bullets found to tailor."}))
        b1 = bullets[0]
        if turns == 2:
            faithful = b1["text"].replace("Built", "Designed and built", 1)
            calls = [("propose_edit", {"bullet_id": b1["id"], "new_text": faithful, "rationale": "Leads with ownership of the pipeline design.",
                                       "requirement_ids": ["r1"]})]
            if len(bullets) > 1:
                calls.append(("propose_edit", {"bullet_id": bullets[1]["id"], "new_text": "Ran Kubernetes clusters for Spark at Google",
                                               "rationale": "(demo: fabricated on purpose; the claim guard must block it)", "requirement_ids": ["r2"]}))
            return _calls(*calls)
        if not answered:
            return _calls(("ask_user", {"question": "Did these pipelines have a measurable result (e.g. faster runs, lower cost)? Give a number if you know it."}))
        ans = next(o["user_answer"] for o in outputs if "user_answer" in o)
        num = re.search(r"\d+\s*%", ans)
        text = b1["text"].replace("Built", "Designed and built", 1).rstrip(".") + (f", cutting processing time by {num.group(0).replace(' ', '')}" if num else ", cutting processing time by [X%]")
        if not any(m.get("tool_calls") and any(c["function"]["name"] == "rescore" for c in m["tool_calls"]) for m in body["messages"] if m.get("role") == "assistant"):
            return _calls(("propose_edit", {"bullet_id": b1["id"], "new_text": text, "rationale": "Adds the result you gave.", "requirement_ids": ["r1"]}),
                          ("rescore", {"edit_ids": ["e1"]}))
        return _calls(("finish", {"summary": "Made your pipeline ownership explicit and added the result you gave. One suggested edit was blocked by the claim guard."}))
    # coach
    if turns == 0:
        return _calls(("get_market_stats", {}), ("list_jobs", {"filter": "near_miss", "sort": "score", "limit": 5}))
    if turns == 2:
        stats = json.loads(tool_msgs[0]["content"])
        gap = (stats.get("top_skill_gaps") or [{"skill": "Kubernetes"}])[0]["skill"]
        return _calls(("what_if", {"add_skills": [gap], "add_years": 0}))
    stats, near, wi = (json.loads(m["content"]) for m in tool_msgs[:3])
    gap = wi["added_skills"][0] if wi["added_skills"] else "a top skill"
    text = (f"**Where you stand:** {stats['qualifying']} of {stats['job_count']} jobs qualify (threshold {stats['threshold']}%).\n\n"
            f"- {near['count']} job(s) are near misses (within 15 points).\n"
            f"- Adding **{gap}** would take you from {wi['qualifying_before']} to {wi['qualifying_after']} qualifying jobs.\n"
            f"- Demo: this sentence claims 99 recruiters viewed your profile, a number the app can't back up.")
    return {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 1500, "completion_tokens": 150}}


@main.app.post("/fake-openai/v1/chat/completions")
async def fc(request: Request):
    body = await request.json()
    if request.headers.get("authorization") != "Bearer sk-good":
        return JSONResponse({"error": {"message": "bad key"}}, 401)
    user = body["messages"][-1]["content"]
    if body.get("stream"):
        reply = f"## Reply\n\nYou asked: **{user[:60]}**\n\n- Point one\n- Point two\n\n<script>alert('xss')</script>"

        async def gen():
            for i in range(0, len(reply), 12):
                yield "data: " + json.dumps({"choices": [{"delta": {"content": reply[i:i + 12]}}]}) + "\n\n"
                await asyncio.sleep(0.02)
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    if body.get("tools"):
        return _agent_reply(body)
    fmt = ((body.get("response_format") or {}).get("json_schema") or {}).get("name")
    if fmt == "Plan":
        intent = re.search(r"<intent>(.*?)</intent>", user, re.S).group(1)
        base = re.split(r"\b(?:in|near|or remote|,)\b", intent.lower())[0].strip().title() or "Data Engineer"
        return _json_reply({"title": base, "alt_titles": [f"{base} II", "Analytics Engineer", "Big Data Engineer", "Florist"],
                            "exclude_titles": ["Sales Engineer"], "seniority": [], "location": "London" if "london" in intent.lower() else "",
                            "workplace": ["hybrid"] if "hybrid" in intent.lower() else [], "keywords": ["Python", "SQL", "Spark"],
                            "note": "Demo plan: one unrelated title (Florist) is included to show it gets dropped."})
    if fmt == "Questions":
        ids = re.findall(r"^- (r\d+) · (\w+) · (.+)$", user, re.M)
        qs = [{"id": f"x{i}", "question": f"Tell me about a time you used: {t[:80]}", "requirement_id": rid,
               "focus": "gap" if st != "met" else "strength", "what_good_looks_like": "A specific example with your actions and a result."}
              for i, (rid, st, t) in enumerate(ids[:5])] or [{"id": "x", "question": "Walk me through a project you're proud of.",
                                                              "requirement_id": "", "focus": "general", "what_good_looks_like": "STAR"}]
        return _json_reply({"questions": qs})
    if fmt == "Feedback":
        return _json_reply({"scores": {"structure": 3, "specificity": 2, "relevance": 4},
                            "strengths": ["Relevant example"], "improvements": ["Add the result and a number", "Say what *you* did"],
                            "stronger_answer": "At Acme Analytics I built ETL pipelines in Python and SQL on AWS and orchestrated them with Airflow, "
                                               "which cut processing time by 35% for the analytics team."})
    everything = "\n".join(str(m.get("content", "")) for m in body["messages"])
    if "Requirements to judge" in user or "has no clearly structured requirement list" in user:
        await asyncio.sleep(0.3)
        return {"choices": [{"message": {"content": json.dumps(_deep_answer(everything))}}]}
    if "List the candidate requirements" in user:
        await asyncio.sleep(0.2)
        return {"choices": [{"message": {"content": json.dumps(_extract_answer(user))}}]}
    out = {"summary": "AI: strong data-engineering profile; main gap is container orchestration.",
           "strengths": ["AI strength: solid Python/SQL/AWS match"], "improvements": ["AI: quantify pipeline impact"],
           "skills_to_learn": [{"skill": "Kubernetes", "why": "Asked in most postings.", "how": "Deploy a small app on kind."}]}
    return {"choices": [{"message": {"content": json.dumps(out)}}]}


rs = main.app.router.routes
fake_routes = [r for r in rs if getattr(r, "path", "").startswith("/fake-openai")]
for r in fake_routes:
    rs.remove(r)
rs[:0] = fake_routes

if __name__ == "__main__":
    import uvicorn
    print(f"Demo server (all external services faked) at http://localhost:{PORT}", flush=True)
    uvicorn.run(main.app, host="127.0.0.1", port=PORT, log_level="warning")
