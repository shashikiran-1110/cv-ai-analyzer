"""Regression tests for ROADMAP §2 defects (one or more per defect). D1 lives in test_ssrf.py."""
from datetime import date

from app import resume

TODAY = date(2026, 10, 4)


# ---------- D2 / D3: experience ----------
def test_d2_education_dates_are_not_work_experience():
    t = "Education\nB.Tech, XYZ University, 2018 - 2022\nExperience\nData Annotator, Auditoria, Jan 2024 - Present"
    assert abs(resume.estimate_years(t, TODAY) - 2.75) <= 0.1
    no_headings = "B.Tech, XYZ University, 2018 - 2022\nData Annotator, Auditoria, Jan 2024 - Present"
    assert abs(resume.estimate_years(no_headings, TODAY) - 2.75) <= 0.1


def test_d3_short_roles_count_in_months():
    e = resume.experience("Experience\nIntern, Acme, Jun 2023 - Aug 2023", TODAY)
    assert e["months"] == 3 and e["precision"] == "month"


def test_experience_formats_and_spans():
    e = resume.experience("Work Experience\nDev 06/2020 - 12/2021\nDev 2022-03 to 2023-02\nAnalyst, Sep '23 – Present", TODAY)
    assert e["months"] == 19 + 12 + 38
    assert [s["start"] for s in e["spans"]] == ["2020-06", "2022-03", "2023-09"] and e["spans"][-1]["end"] == "present"
    assert e["method"] == "experience section"


def test_projects_and_education_sections_excluded():
    t = ("Projects\nThesis project 2019 - 2021\nExperience\nEngineer, Acme, Jan 2022 - Dec 2022\n"
         "Education\nMSc, Some University, 2016 - 2018")
    assert resume.experience(t, TODAY)["months"] == 12


def test_year_only_ranges_are_flagged_low_precision():
    e = resume.experience("Experience\nEngineer, Acme, 2019 - 2021", TODAY)
    assert e["months"] == 36 and e["precision"] == "year"


# ---------- D4 / D5 / D6: skills & degrees ----------
import pytest  # noqa: E402

from app import matcher, skills  # noqa: E402


def test_d4_everyday_words_are_not_skills():
    assert skills.extract_skills("Spring 2023 internship, swift turnaround, guard rails, we go agile") == set()


@pytest.mark.parametrize("text,want", [
    ("Java with Spring and Hibernate", {"Java", "Spring"}), ("Spring Boot microservices", {"Spring", "Microservices"}),
    ("iOS apps in Swift", {"iOS", "Swift"}), ("Ruby on Rails", {"Ruby", "Rails"}),
    ("Agile teams using Scrum", {"Agile", "Scrum"}), ("Big data with Spark and Hadoop", {"Spark", "Hadoop"}),
    ("Summer 2022 intern; spring semester 2021", set()), ("a spark of creativity", set()),
])
def test_d4_context_rules_keep_real_mentions(text, want):
    assert skills.extract_skills(text) == want


@pytest.mark.parametrize("text,req,neg", [
    ("No Java experience required", set(), {"Java"}),
    ("Java experience is not required", set(), {"Java"}),
    ("Experience with Python, not Java", {"Python"}, {"Java"}),
    ("No prior experience required; must know Python", {"Python"}, set()),
    ("Python and SQL (no prior Spark experience needed)", {"Python", "SQL"}, {"Spark"}),
    ("Java required. No Java 7 though", {"Java"}, set()),          # one positive mention is enough
])
def test_d5_negated_requirements(text, req, neg):
    assert skills.extract_posting_skills(text) == (req, neg)


def test_d5_negated_skill_is_not_a_requirement_or_gap():
    desc = ("Requirements\n• Strong Python and SQL\n• No Java experience required, we'll teach you\n"
            "• 2+ years of experience building data pipelines\n" + "We value curiosity. " * 5)
    p = matcher.ResumeProfile.build("Data engineer. Python, SQL, Airflow.\nExperience\nAcme, Jan 2020 - Present", 5)
    r = matcher.score_job({"id": "1", "title": "Data Engineer", "description": desc}, p)
    assert "Java" not in r["missing_skills"] and "Java" not in r["required_missing"] and r["negated_skills"] == ["Java"]
    assert not any("Java" in q["text"] for q in r["requirements"])


@pytest.mark.parametrize("text,level", [
    ("Certified Scrum Master", None), ("Master Data Management", None), ("mastered Excel", None),
    ("master branch merges", None), ("Ms. Jane Doe", None), ("MSc Computer Science", "Master's"),
    ("Master's degree in Statistics", "Master's"), ("Masters in Data Science", "Master's"),
    ("Master of Science, Physics", "Master's"), ("MBA, 2015", "Master's"), ("M.S. in CS", "Master's"),
    ("B.Tech in CSE", "Bachelor's"), ("PhD candidate", "PhD"),
])
def test_d6_degree_requires_degree_context(text, level):
    assert matcher.education_level(text) == level


def test_d6_scrum_master_line_is_not_a_degree_requirement():
    assert matcher.required_education([("Certified Scrum Master preferred", False)])[0] is None


# ---------- D7 / D8 / D9: location, dedupe, LinkedIn count ----------
import httpx  # noqa: E402

from app import linkedin  # noqa: E402
from app.jobmodel import Job  # noqa: E402
from app.sources import BY_ID, JobQuery, aggregate  # noqa: E402


@pytest.mark.parametrize("user,job_loc,remote,ok", [
    ("US", "Brussels", None, False), ("India", "Indianapolis", None, False),
    ("US", "Remote - US", True, True), ("US", "Austin, TX", None, True), ("UK", "Manchester", None, True),
    ("London", "Manchester, UK", None, False), ("London", "London, England", None, True),
    ("London", "Remote (UK only)", True, True), ("London", "Remote - Ukraine", True, False),
])
def test_d7_location_whole_words(user, job_loc, remote, ok):
    assert aggregate.location_ok(Job(id="1", title="t", location=job_loc, remote=remote), JobQuery(title="x", location=user)) is ok


def test_d8_dedupe_keeps_different_cities_and_merges_near_duplicates():
    a = Job(id="a", title="Software Engineer", company="Google", location="London", source="greenhouse")
    b = Job(id="b", title="Software Engineer", company="Google", location="New York", source="lever")
    assert len(aggregate.dedupe([a, b])) == 2
    d = ("About the role: you'll design and run the batch and streaming pipelines behind our analytics platform. "
         "Requirements: 5+ years of experience in data engineering, strong Python and SQL, experience with Airflow, Spark "
         "and Kafka, hands-on AWS (S3, Glue, Redshift) and data modeling. Nice to have: Kubernetes, Terraform, dbt. "
         "We offer hybrid working from our London office, private health insurance and a learning budget.")
    s1 = Job(id="c", title="Senior Data Engineer", company="Acme", location="London", description=d, source="remotive")
    s2 = Job(id="d", title="Sr. Data Engineer", company="Acme Ltd", location="London, UK", description=d + " Apply today.", source="linkedin")
    out = aggregate.dedupe([s1, s2])
    assert len(out) == 1 and set(out[0].sources) == {"linkedin", "remotive"}
    other = Job(id="e", title="Data Analyst", company="Acme", location="London", description="Dashboards in Tableau and Excel. " * 12)
    assert len(aggregate.dedupe([s1, other])) == 2


def _cards(start, titles):
    return "".join(
        f'<li><div class="base-card" data-entity-urn="urn:li:jobPosting:{start + i}">'
        f'<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/x-{start + i}"></a>'
        f'<h3 class="base-search-card__title">{t}</h3><h4 class="base-search-card__subtitle">Co{start + i}</h4>'
        f'<span class="job-search-card__location">London</span></div></li>' for i, t in enumerate(titles))


async def test_d9_linkedin_overfetches_cards_and_details_only_survivors():
    pages = {0: ["Data Engineer", "Sales Manager", "Nurse", "Barista", "Chef", "Driver", "Data Engineer II", "Cook", "Clerk", "Tutor"],
             10: ["Accountant", "Senior Data Engineer", "Teacher", "Pilot", "Baker", "Florist", "Data Engineer", "Guard", "Plumber", "Vet"]}
    detail_ids = []

    def handler(request):
        if "seeMoreJobPostings" in request.url.path:
            start = int(request.url.params["start"])
            return httpx.Response(200, text=_cards(start, pages.get(start, [])))
        detail_ids.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, text='<div class="show-more-less-html__markup"><p>Requirements</p><ul><li>Python</li></ul></div>')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        jobs = await BY_ID["linkedin"].fetch(JobQuery(title="Data Engineer", location="London", count=4), c)
    assert [j.title for j in jobs] == ["Data Engineer", "Data Engineer II", "Senior Data Engineer", "Data Engineer"]
    assert sorted(detail_ids) == sorted(j.id for j in jobs)      # no detail requests for irrelevant cards


async def test_d9_card_cap_is_respected():
    calls = []

    def handler(request):
        calls.append(int(request.url.params.get("start", -1)))
        return httpx.Response(200, text=_cards(calls[-1] + 1000, ["Nurse"] * 10))   # never relevant
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        warnings = []
        jobs = await linkedin.search_jobs("Data Engineer", "", 10, client=c, warnings=warnings,
                                          prefilter=lambda j: "data" in j.title.lower())
    assert jobs == [] and len(calls) == 3                      # ceil(10 × 2.5) = 25 cards → 3 pages, then stop
    assert "none matched" in warnings[0]


# ---------- D12 / D13 / D14 ----------
from app import assistant, config, insights, llm  # noqa: E402


def test_d12_prompt_weights_come_from_the_matcher():
    sp = assistant.system_prompt()
    assert matcher.weights_sentence() in sp and "60%" not in sp and "{weights}" not in sp
    assert all(f"{round(v * 100)}%" in sp for v in matcher.W.values())
    assert "LinkedIn postings" not in insights.PROMPT


def test_d13_server_key_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-secret")
    monkeypatch.delenv("ALLOW_SERVER_KEY_ANON", raising=False)
    assert config.ai_provider() is None and llm.resolve({}) is None
    monkeypatch.setenv("ALLOW_SERVER_KEY_ANON", "true")
    cfg = llm.resolve({})
    assert cfg and cfg.provider == "openai" and cfg.source == "server"


async def test_d13_api_does_not_expose_server_key_by_default(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app import main
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-secret")
    monkeypatch.delenv("ALLOW_SERVER_KEY_ANON", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.get("/api/config")).json()["server_ai"] is None
        assert (await c.post("/api/ai/verify")).json()["ok"] is False


def test_d14_requirement_lines_computed_once(monkeypatch):
    calls = []
    real = matcher.requirement_lines
    monkeypatch.setattr(matcher, "requirement_lines", lambda d: calls.append(1) or real(d))
    p = matcher.ResumeProfile.build("Python developer", 3)
    matcher.score_job({"id": "1", "title": "Dev", "description": "Requirements\n• Strong Python skills required\n" * 3}, p)
    assert len(calls) == 1


# ---------- fairness (ROADMAP §14.2), found by the eval harness ----------
from app.resume import strip_identity  # noqa: E402


@pytest.mark.parametrize("text,want", [
    ("James Smith\nhe/him\nSummary: x", "Summary: x"),
    ("Jane Doe - Data Engineer\nExperience", "Data Engineer\nExperience"),
    ("Jordan Lee | jordan.lee@example.com | +44 7700 900123\nPronouns: they/them\nSkills", "Skills"),
    ("Ruby Patel\nshe/her\nPython developer", "Python developer"),
    ("DATA ENGINEER\nExperience", "DATA ENGINEER\nExperience"),
    ("Mary-Jane O'Neil | Registered Nurse\nExperience", "Registered Nurse\nExperience"),
])
def test_identity_is_stripped_but_headline_kept(text, want):
    assert strip_identity(text) == want


def test_names_never_change_scores_or_skills():
    body = "\nExperience\nData Engineer, Acme, Jan 2021 - Present\nBuilt ETL in Python and SQL on AWS."
    job = {"id": "1", "title": "Data Engineer", "description": "Requirements\n• Strong Python and SQL skills\n• Ruby or Go a plus\n" * 2}
    scores = set()
    for name in ["James Smith", "Wei Zhang", "Ruby Patel", "José García", "Priya Raghunathan"]:
        p = matcher.ResumeProfile.build(name + body, 5)
        assert "Ruby" not in p.skills
        scores.add(matcher.score_job(job, p)["score"])
    assert len(scores) == 1


def test_eval_harness_has_no_regressions():
    from eval import run
    assert run.main(["--check"]) == 0


def test_eval_gate_detects_regressions(monkeypatch):
    from eval import run
    base = {"skills.f1": 0.90, "experience.mae_months": 0.0, "location.accuracy": 0.8}
    assert run.compare({"skills.f1": 0.895, "experience.mae_months": 0.4, "location.accuracy": 0.8}, base) == []  # within tolerance
    regs = run.compare({"skills.f1": 0.85, "experience.mae_months": 2.0, "location.accuracy": 0.75}, base)
    assert len(regs) == 3 and any("skills.f1" in r for r in regs)
    monkeypatch.setattr(run, "suite_location", lambda: {"metrics": {"accuracy": 0.1, "cases": 20}, "failures": []})
    monkeypatch.setitem(run.SUITES, "location", run.suite_location)
    assert run.main(["--check", "--suite", "location"]) == 1


async def test_prelabel_verifies_quotes(monkeypatch):
    import json as _json
    from eval.labeling import prelabel
    answer = {"label": "possible", "rationale": "r", "requirements": [
        {"text": "Python", "importance": "must", "status": "met", "quote": "Built ETL in Python and SQL on AWS"},
        {"text": "Kafka", "importance": "must", "status": "met", "quote": "Ran Kafka at scale"}]}
    real = httpx.AsyncClient
    monkeypatch.setattr(llm, "_client", lambda: real(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": _json.dumps(answer)}}]}))))
    out = await prelabel.label_one(llm.LLMConfig("openai", "sk-test-123456", "m"),
                                   {"id": "p1", "resume": "Experience\nBuilt ETL in Python and SQL on AWS.", "job_title": "DE",
                                    "job_description": "Python, Kafka"})
    reqs = out["prelabel"]["requirements"]
    assert out["reviewed"] is False and reqs[0]["quote_verified"] and not reqs[1]["quote_verified"]
