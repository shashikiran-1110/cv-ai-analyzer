from datetime import date

from app import matcher, resume, skills
from tests.conftest import RESUME_LINES

TEXT = "\n".join(RESUME_LINES)

JOB_DESC = (
    "About the role\nBuild data pipelines on AWS using Python and SQL.\n"
    "Requirements\n- 5+ years of experience in data engineering\n- Strong Python and SQL\n"
    "- Experience with Airflow and Spark\n- Excellent communication\n"
    "Nice to have\n- Kubernetes\n- Terraform\n"
)


def profile():
    return matcher.ResumeProfile.build(TEXT, resume.estimate_years(TEXT, date(2026, 10, 1)))


def test_skill_extraction_edge_cases():
    got = skills.extract_skills("We use C++, C#, Node.js, .NET and Go (golang). Not java-script. Javascript ok. React.js")
    assert {"C++", "C#", "Node.js", ".NET", "Go", "JavaScript", "React"} <= got
    assert "Java" not in skills.extract_skills("experienced with JavaScript only")
    assert "R" not in skills.extract_skills("our R&D team and r e a l")
    assert "Go" not in skills.extract_skills("ready to go the extra mile")


def test_preferred_split_and_weights():
    req, pref = matcher.split_requirements(JOB_DESC)
    assert "Kubernetes" in pref and "Kubernetes" not in req
    r = matcher.score_job({"id": "1", "title": "Senior Data Engineer", "description": JOB_DESC}, profile())
    assert {"Python", "SQL", "Airflow", "Spark", "AWS"} <= set(r["matched_skills"])
    assert set(r["missing_skills"]) == {"Kubernetes", "Terraform"}
    assert r["required_missing"] == []          # preferred skills aren't "required"
    assert r["required_years"] == 5.0 and not r["required_years_inferred"]
    assert r["score"] >= 80


def test_unrelated_job_scores_low():
    desc = ("We need a Registered Nurse for our pediatric ward. Provide patient care, administer medication, "
            "document patient records and collaborate with physicians. Nursing license required. " * 3)
    r = matcher.score_job({"id": "2", "title": "Registered Nurse", "description": desc}, profile())
    assert r["score"] < 40


def test_missing_description_is_capped_and_flagged():
    r = matcher.score_job({"id": "3", "title": "Data Engineer", "description": ""}, profile())
    assert r["confidence"] == "low" and r["score"] <= 45


def test_experience_inference_from_title():
    assert matcher.required_years("Senior Developer", "") == (5.0, True)
    assert matcher.required_years("Junior Developer", "") == (0.0, True)
    assert matcher.required_years("Developer", "3-5 years of professional experience") == (3.0, False)
    assert matcher.required_years("Developer", "") == (None, True)


def test_estimate_years_merges_overlaps():
    t = "A Co 2015 - 2018\nB Co 2017 – 2020\nC Co Mar 2021 - Present"
    assert resume.estimate_years(t, date(2026, 1, 1)) == 5 + 5  # 2015-2020 and 2021-2026
    assert resume.estimate_years("I have 8+ years of experience", date(2026, 1, 1)) == 8


def test_aggregate_counts():
    p = profile()
    jobs = [{"id": str(i), "title": "Data Engineer", "description": JOB_DESC} for i in range(4)]
    res = [matcher.score_job(j, p) for j in jobs]
    agg = matcher.aggregate(res, p, 60)
    assert agg["job_count"] == 4 and agg["qualifying"] == 4
    assert agg["skill_gaps"][0]["jobs"] == 4
    assert {g["skill"] for g in agg["skill_gaps"]} == {"Kubernetes", "Terraform"}
    assert sum(agg["distribution"]) == 4
