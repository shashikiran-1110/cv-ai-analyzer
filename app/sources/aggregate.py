"""Run sources concurrently, then normalize → filter → dedupe → rank → pick a fair spread."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import defaultdict
from typing import Awaitable, Callable, Optional

import httpx

from ..jobmodel import Job
from ..textutil import age_hours
from ..runtime import metrics
from .base import UA, JobQuery, Source, SourceError

log = logging.getLogger("sources")

NOISE = set("senior sr junior jr lead principal staff associate intern internship mid level i ii iii iv v "
            "remote hybrid contract contractor freelance fulltime full time part the and of for a an in at to with "
            "m f d w x h".split())
SYN = {"developer": "engineer", "dev": "engineer", "programmer": "engineer", "engineering": "engineer",
       "swe": "software", "sde": "software", "js": "javascript", "golang": "go", "k8s": "kubernetes",
       "analytics": "analyst", "scientist": "science", "designers": "designer", "mgr": "manager",
       "management": "manager", "administrator": "admin", "ops": "operations"}
PHRASES = [(r"front[\s-]*end", "frontend"), (r"back[\s-]*end", "backend"), (r"full[\s-]*stack", "fullstack"),
           (r"\bml\b", "machine learning"), (r"\bsre\b", "site reliability"), (r"\bqa\b", "quality assurance"),
           (r"\bui\s*/\s*ux\b", "ux"), (r"\bdev\s*ops\b", "devops"), (r"\bdata\s*base", "database")]
ANYWHERE = {"remote", "anywhere", "worldwide", "global"}
REGIONS = {
    "europe": "uk united kingdom england london manchester ireland dublin germany berlin munich france paris spain madrid "
              "barcelona netherlands amsterdam belgium portugal lisbon italy milan poland warsaw sweden stockholm denmark "
              "norway finland switzerland zurich austria vienna czech prague romania greece estonia",
    "emea": "uk united kingdom london ireland germany france spain netherlands poland portugal italy uae dubai israel "
            "south africa egypt nigeria kenya sweden",
    "north america": "usa us united states new york san francisco california texas austin seattle boston chicago canada "
                     "toronto vancouver montreal",
    "americas": "usa us united states canada brazil mexico argentina colombia chile",
    "apac": "india bangalore bengaluru mumbai delhi hyderabad pune chennai singapore australia sydney melbourne japan "
            "tokyo philippines vietnam indonesia malaysia new zealand",
    "asia": "india bangalore bengaluru hyderabad singapore japan philippines vietnam indonesia malaysia",
    "latam": "brazil mexico argentina colombia chile peru",
}
COUNTRIES = {
    "united kingdom": ["uk", "u.k.", "united kingdom", "england", "scotland", "wales", "great britain", "britain", "gb"],
    "united states": ["us", "u.s.", "usa", "united states", "america"],
    "germany": ["germany", "deutschland", "de"], "france": ["france"], "spain": ["spain"], "netherlands": ["netherlands", "holland"],
    "ireland": ["ireland"], "india": ["india"], "canada": ["canada"], "australia": ["australia"], "singapore": ["singapore"],
    "poland": ["poland"], "portugal": ["portugal"], "italy": ["italy"], "sweden": ["sweden"], "switzerland": ["switzerland"],
}
CITY_COUNTRY = {
    **dict.fromkeys("london manchester birmingham leeds bristol edinburgh glasgow cambridge oxford liverpool belfast".split(), "united kingdom"),
    **dict.fromkeys(["new york", "san francisco", "seattle", "austin", "boston", "chicago", "los angeles", "denver", "atlanta",
                     "washington", "miami", "dallas", "california", "texas"], "united states"),
    **dict.fromkeys("berlin munich hamburg frankfurt cologne".split(), "germany"), "paris": "france", "lyon": "france",
    "madrid": "spain", "barcelona": "spain", "amsterdam": "netherlands", "rotterdam": "netherlands", "dublin": "ireland",
    **dict.fromkeys("bangalore bengaluru mumbai delhi hyderabad pune chennai gurgaon noida kolkata".split(), "india"),
    "toronto": "canada", "vancouver": "canada", "montreal": "canada", "sydney": "australia", "melbourne": "australia",
    "warsaw": "poland", "krakow": "poland", "lisbon": "portugal", "porto": "portugal", "milan": "italy", "rome": "italy",
    "stockholm": "sweden", "zurich": "switzerland", "geneva": "switzerland",
}


def _has_word(hay: str, word: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", hay) is not None


def _countries_for(parts: list[str]) -> set[str]:
    out = set()
    for p in parts:
        if p in CITY_COUNTRY:
            out.add(CITY_COUNTRY[p])
        for c, names in COUNTRIES.items():
            if p == c or p in names:
                out.add(c)
    return out


SOURCE_PRIORITY = {"greenhouse": 0, "lever": 0, "ashby": 0, "url": 1, "linkedin": 2, "manual": 1, "adzuna": 4}
TYPE_MAP = {"full_time": ("full", "permanent"), "part_time": ("part",), "contract": ("contract", "freelance"),
            "temporary": ("temporary", "temp"), "internship": ("intern",)}


def norm_tokens(text: str) -> list[str]:
    t = text.lower()
    for pat, rep in PHRASES:
        t = re.sub(pat, rep, t)
    return [SYN.get(w, w) for w in re.findall(r"[a-z0-9+#]+", t)]


def core_tokens(title: str) -> list[str]:
    seen, out = set(), []
    for w in norm_tokens(title):
        if w not in NOISE and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def query_relevance(job: Job, q: JobQuery) -> float:
    """Best relevance over the query title and the planner's alternative titles; 0 for an excluded title."""
    tt = set(norm_tokens(job.title))
    for ex in q.exclude_titles:
        ex_core = core_tokens(ex)
        if ex_core and set(ex_core) <= tt:
            return 0.0
    return max([relevance(job, core_tokens(q.title))] + [relevance(job, core_tokens(t)) for t in q.alt_titles[:12]])


def relevance(job: Job, core: list[str]) -> float:
    if not core:
        return 1.0
    tt = set(norm_tokens(job.title))
    hits = sum(t in tt for t in core) / len(core)
    if hits >= 1:
        return 1.0
    ctx = set(norm_tokens(" ".join(map(str, job.tags)) + " " + job.description[:800]))
    soft = sum(t in ctx for t in core if t not in tt) / len(core)
    return min(1.0, hits + 0.4 * soft)


def _is_remote(job: Job) -> Optional[bool]:
    if job.remote is not None:
        return job.remote
    return True if "remote" in job.location.lower() else None


def location_ok(job: Job, q: JobQuery) -> bool:
    """Whole-word location matching (ROADMAP D7): "US" must not match "Brussels", "India" not "Indianapolis"."""
    loc = q.location.strip().lower()
    if not loc:
        return True
    jl = job.location.lower()
    remote = _is_remote(job)
    if loc in ANYWHERE:
        return loc != "remote" or bool(remote)
    parts = [p.strip() for p in re.split(r"[,/|]", loc) if len(p.strip()) >= 2]
    if any(_has_word(jl, p) for p in parts):
        return True
    # the user typed a country: accept that country's name variants and its known cities
    user_countries = {c for p in parts for c, names in COUNTRIES.items() if p == c or p in names}
    for c in user_countries:
        if any(_has_word(jl, n) for n in COUNTRIES[c]) or any(_has_word(jl, city) for city, cc in CITY_COUNTRY.items() if cc == c):
            return True
    if not remote:
        return False
    if not jl or any(_has_word(jl, w) for w in ("worldwide", "anywhere", "global")) or jl.strip() in ("remote", "remote (worldwide)"):
        return True
    for country in _countries_for(parts):       # remote job restricted to the user's country
        if any(_has_word(jl, n) for n in COUNTRIES[country]):
            return True
    for region, members in REGIONS.items():
        if _has_word(jl, region) and any(_has_word(members, p) for p in parts):
            return True
    return False


def filters_ok(job: Job, q: JobQuery) -> tuple[bool, str]:
    if q.hours:
        age = age_hours(job.posted)
        if age is not None and age > q.hours + 6:
            return False, "older than time range"
    if not location_ok(job, q):
        return False, "location"
    if q.workplace:
        wp, r = set(q.workplace), _is_remote(job)
        if r is True and "remote" not in wp:
            return False, "workplace"
        if r is False and wp == {"remote"}:
            return False, "workplace"
    if q.job_types and job.employment_type:
        et = job.employment_type.lower()
        known = [code for code, keys in TYPE_MAP.items() if any(k in et for k in keys)]
        if known and not set(known) & set(q.job_types):
            return False, "job type"
    if q.experience:
        t = job.title.lower()
        exp = set(q.experience)
        if re.search(r"\b(senior|sr\.?|lead|principal|staff|head of|director)\b", t) and exp <= {"internship", "entry"}:
            return False, "experience"
        if re.search(r"\b(intern|internship|junior|jr\.?|graduate|trainee)\b", t) and exp <= {"mid_senior", "director", "executive"}:
            return False, "experience"
    return True, ""


def _norm_company(c: str) -> str:
    c = re.sub(r"\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|plc|sa|ag|bv)\b\.?", "", c.lower())
    return re.sub(r"[^a-z0-9]", "", c)


def _city_key(job: Job) -> str:
    loc = job.location.lower()
    if not loc.strip() or (_is_remote(job) and re.search(r"remote|worldwide|anywhere|global", loc)):
        return "remote"
    return re.sub(r"[^a-z0-9]", "", re.split(r"[,;(/|-]", loc)[0])


def simhash(text: str) -> int:
    """64-bit SimHash over word 3-shingles (near-duplicate descriptions differ by few bits)."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < 3:
        return 0
    v = [0] * 64
    for i in range(len(words) - 2):
        h = int.from_bytes(hashlib.md5(" ".join(words[i:i + 3]).encode()).digest()[:8], "big")
        for b in range(64):
            v[b] += 1 if h >> b & 1 else -1
    return sum(1 << b for b in range(64) if v[b] > 0)


def _merge(g: list[Job]) -> Job:
    g.sort(key=lambda j: (SOURCE_PRIORITY.get(j.source, 3), -len(j.description)))
    best = g[0]
    longest = max(g, key=lambda j: len(j.description))
    if len(longest.description) > len(best.description) + 200:
        best.description = longest.description
    best.sources = sorted({s for j in g for s in (j.sources or [j.source])}, key=lambda s: SOURCE_PRIORITY.get(s, 3))
    return best


def dedupe(jobs: list[Job]) -> list[Job]:
    """ROADMAP D8: same company + title + city is one posting; then near-identical descriptions
    (SimHash distance ≤ 3) at the same company and city are merged too (reposts with tweaked titles)."""
    groups: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        comp = _norm_company(j.company)
        key = (f"{comp}|{re.sub(r'[^a-z0-9]', '', j.title.lower())}|{_city_key(j)}" if comp else f"url|{j.url or j.id}")
        groups[key].append(j)
    merged = [_merge(g) for g in groups.values()]
    out: list[Job] = []
    hashes: list[tuple[str, int]] = []
    for j in merged:
        comp, h = f"{_norm_company(j.company)}|{_city_key(j)}", simhash(j.description) if len(j.description) >= 200 else 0
        dup = next((i for i, (k, hh) in enumerate(hashes) if comp == k and h and hh and bin(h ^ hh).count("1") <= 3), None)
        if dup is None:
            out.append(j)
            hashes.append((comp, h))
        else:
            out[dup] = _merge([out[dup], j])
    return out


def rank_score(job: Job, rel: float, q: JobQuery) -> float:
    completeness = min(len(job.description) / 1500, 1.0)
    age = age_hours(job.posted)
    horizon = q.hours or 24 * 30
    recency = 0.5 if age is None else max(0.0, 1 - age / horizon)
    return 0.55 * rel + 0.30 * completeness + 0.15 * recency


def pick(scored: list[tuple[float, Job]], count: int) -> list[Job]:
    """Round-robin across sources (best first) so one big source can't crowd out the rest."""
    by_src: dict[str, list[tuple[float, Job]]] = defaultdict(list)
    for s, j in scored:
        by_src[j.source].append((s, j))
    for lst in by_src.values():
        lst.sort(key=lambda x: -x[0])
    order = sorted(by_src, key=lambda k: -by_src[k][0][0])
    out: list[Job] = []
    while len(out) < count and any(by_src[k] for k in order):
        for k in order:
            if by_src[k] and len(out) < count:
                out.append(by_src[k].pop(0)[1])
    return out


JOB_SOURCE = {"urls": "url"}  # source plugin id -> Job.source tag (URL imports may also yield LinkedIn jobs)

StatsCb = Callable[[dict], Awaitable[None]]


async def run(q: JobQuery, sources: list[Source], on_update: Optional[StatsCb] = None,
              client: Optional[httpx.AsyncClient] = None) -> tuple[list[Job], dict, list[str]]:
    own = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                         timeout=httpx.Timeout(25, connect=10), follow_redirects=True)
    stats = {s.id: {"id": s.id, "name": s.name, "status": "running", "fetched": 0, "kept": 0, "message": "",
                    "progress": None} for s in sources}
    warnings: list[str] = []

    async def push():
        if on_update:
            await on_update(stats)

    async def run_one(src: Source) -> list[Job]:
        st = stats[src.id]
        try:
            if src.id == "linkedin":
                async def lp(stage, done, total):
                    st["progress"] = {"stage": stage, "done": done, "total": total}
                    await push()
                jobs = await asyncio.wait_for(src.fetch(q, client, lp), src.timeout)
            else:
                jobs = await asyncio.wait_for(src.fetch(q, client), src.timeout)
            st.update(status="done", fetched=len(jobs))
            metrics.inc("source_fetch_total", source=src.id, outcome="ok")
            metrics.inc("source_jobs_total", len(jobs), source=src.id, stage="fetched")
            for j in jobs:
                for w in j.extra.pop("_warnings", []):
                    warnings.append(f"{src.name}: {w}")
                    st["message"] = (st["message"] + " " + w).strip()
                if not j.source:
                    j.source = src.id
            return jobs
        except asyncio.TimeoutError:
            metrics.inc("source_fetch_total", source=src.id, outcome="timeout")
            st.update(status="error", message=f"{src.name} took too long to respond (timeout).")
        except SourceError as e:
            metrics.inc("source_fetch_total", source=src.id, outcome=e.kind)
            st.update(status="error", message=str(e), kind=e.kind)
        except Exception as e:  # a broken source must never break the search
            log.exception("source %s failed", src.id)
            st.update(status="error", message=f"{src.name} failed unexpectedly ({type(e).__name__}).")
        finally:
            await push()
        return []

    try:
        await push()
        results = await asyncio.gather(*(run_one(s) for s in sources))
    finally:
        if own:
            await client.aclose()

    core = core_tokens(q.title)
    user_chosen = {"urls", "manual"}           # the user picked these postings: never filtered out
    threshold = 0.75 if q.strict else 0.5
    candidates: list[tuple[float, Job]] = []
    for src, jobs in zip(sources, results):
        kept = 0
        for j in jobs:
            if not j.title:
                continue
            rel = query_relevance(j, q) if (q.alt_titles or q.exclude_titles) else relevance(j, core)
            if src.id not in user_chosen and rel < threshold and (q.strict or src.id != "linkedin"):
                continue
            ok, _ = filters_ok(j, q) if src.id not in user_chosen else (True, "")
            if not ok:
                continue
            j.extra["relevance"] = round(rel, 2)
            candidates.append((rank_score(j, rel, q), j))
            kept += 1
        stats[src.id]["kept"] = kept
    unique = {id(j) for j in dedupe([j for _, j in candidates])}
    deduped = [(s, j) for s, j in candidates if id(j) in unique]
    final = pick(deduped, q.count)
    for s in sources:
        stats[s.id]["selected"] = sum(1 for j in final if j.source == JOB_SOURCE.get(s.id, s.id))
    await push()
    return final, stats, warnings
