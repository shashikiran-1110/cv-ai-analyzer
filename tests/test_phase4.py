"""Phase 4: ontology relations + domain packs, gates, requirement matrix fields."""
from app import gates, matcher, ontology
from app import skills as sk
from tests.test_api import _analyzed, client  # noqa: F401  (fixture reuse)


def _p(text, years=5, corrections=None):
    return matcher.ResumeProfile.build(text, years, corrections=corrections)


def test_ontology_names_exist_and_credit_rules():
    names = {x["name"] for x in sk.all_skills()}
    for k, vs in ontology.IMPLIES.items():
        assert k in names and all(v in names for v in vs), k
    assert all(n in names for g in ontology.RELATED for n in g)
    owned = {"Django", "MySQL"}
    assert ontology.credit("Python", owned) == (1.0, "implied", "Django")
    assert ontology.credit("PostgreSQL", owned) == (0.5, "related", "MySQL")
    assert ontology.credit("SQL", owned)[1] == "implied"                     # MySQL ⇒ SQL
    assert ontology.credit("Kubernetes", owned) == (0.0, "missing", "")


def test_related_skill_gets_partial_credit_with_explanation():
    job = {"id": "1", "title": "Backend Engineer",
           "description": "Requirements\n- Strong PostgreSQL experience\n- Python services\n" + "We build things. " * 15}
    r = matcher.score_job(job, _p("Experience\nBuilt Django apps on MySQL for 5 years at Acme."))
    rows = {q["text"]: q for q in r["requirements"]}
    pg = rows["Strong PostgreSQL experience"]
    assert pg["status"] == "partial" and pg["how"] == "related skill" and "MySQL" in pg["via"][0]
    py = rows["Python services"]
    assert py["status"] == "met" and py["how"] == "implied skill" and "Django" in py["evidence"]
    assert {x["skill"] for x in r["related_skills"]} >= {"PostgreSQL", "Python"}


def test_domain_packs_extract_non_tech_without_tech_false_positives():
    nurse = sk.extract_skills("Registered nurse, ICU. BLS and ACLS certified. Medication administration and patient triage.")
    assert {"Nursing", "Critical Care", "BLS/ACLS", "Medication Administration", "Triage"} <= nurse
    assert sk.extract_skills("We triage incoming bugs; pre-tax benefits and payroll deduction; framing the problem.") == set()
    acct = sk.extract_skills("Month-end close, bank reconciliations, accounts payable and VAT returns in Xero")
    assert {"Reconciliation", "Accounts Payable", "Tax", "Bookkeeping"} <= acct


def test_gate_detection():
    desc = ("You must be authorized to work in the US. We are unable to sponsor visas.\n"
            "Active TS/SCI clearance required.\nActive RN license required.\nFluent German is required.\n"
            "Spanish is a plus.\nThis role is fully on-site in Austin.")
    found = {g["type"]: g for g in gates.detect(desc)}
    assert found["authorization"]["need"] == "US" and found["authorization"]["no_sponsorship"]
    assert found["clearance"]["need"] == "TS/SCI"
    assert found["license"]["need"] == "Registered Nurse licence"
    langs = [g["need"] for g in gates.detect(desc) if g["type"] == "language"]
    assert langs == ["German"]                                                # "a plus" isn't a gate
    assert "onsite" in found
    assert gates.detect("Great team, remote friendly, Python and SQL.") == []


def test_gate_evaluation_pass_fail_unknown():
    g = gates.detect("Must be authorized to work in the UK; no visa sponsorship.\nActive RN license required.\n"
                     "Fluent French required.")
    unknown = {x["type"]: x["status"] for x in gates.evaluate(g, "Nurse. Languages: English", None)}
    assert unknown == {"authorization": "unknown", "license": "fail", "language": "fail"}
    ok = {x["type"]: x["status"] for x in gates.evaluate(
        g, "Registered nurse with active RN license (NMC registration).",
        {"work_countries": ["UK"], "languages": ["French"]})}
    assert ok == {"authorization": "pass", "license": "pass", "language": "pass"}
    bad = gates.evaluate(g, "", {"work_countries": ["US"], "needs_sponsorship": True})
    assert bad[0]["status"] == "fail" and "no sponsorship" in bad[0]["reason"]


def test_gates_shape_qualifying_but_not_score():
    desc = ("Requirements\n- Python and SQL\n- AWS\nActive TS/SCI clearance required.\n" + "Team text. " * 20)
    job = {"id": "1", "title": "Data Engineer", "description": desc}
    prof = _p("Experience\nData Engineer, Jan 2018 - Present\nBuilt ETL in Python and SQL on AWS.")
    r = matcher.score_job(job, prof)
    assert r["gates_failed"] == ["security clearance"] and r["score"] >= 60
    plain = matcher.score_job({**job, "description": desc.replace("Active TS/SCI clearance required.\n", "")}, prof)
    assert abs(plain["score"] - r["score"]) <= 2                             # gates don't move the score
    agg = matcher.aggregate([r, plain], prof, 60)
    assert agg["qualifying"] == 1 and agg["score_qualifying"] == 2 and agg["gate_failed"] == 1
    assert agg["gate_breakdown"] == {"security clearance": 1}
    cleared = _p("Experience\nData Engineer, Jan 2018 - Present\nBuilt ETL in Python and SQL on AWS.",
                 corrections={"eligibility": {"clearance": "TS/SCI"}})
    assert matcher.score_job(job, cleared)["gates_failed"] == []


async def test_eligibility_round_trip_and_rescore(client, resume_pdf):  # noqa: F811
    async with client as c:
        a = await _analyzed(c, resume_pdf)
        r = await c.patch(f"/api/profiles/{a['resume_id']}", json={"eligibility": {
            "work_countries": ["UK"], "needs_sponsorship": False, "languages": ["German", " "], "relocate": True}})
        assert r.status_code == 200, r.text
        assert r.json()["corrections"]["eligibility"] == {"work_countries": ["UK"], "needs_sponsorship": False,
                                                          "languages": ["German"], "relocate": True}
        bad = await c.patch(f"/api/profiles/{a['resume_id']}", json={"eligibility": {"work_countries": ["Mars"]}})
        assert bad.status_code == 422
        rs = (await c.post(f"/api/analysis/{a['analysis_id']}/rescore", json={})).json()
        assert "gates" in rs["jobs"][0] and "gate_failed" in rs["summary"]


def test_calibration_fit_and_apply(tmp_path, monkeypatch):
    """Synthetic data only checks the maths; real coefficients need ≥ 300 human-labelled pairs."""
    import json as _json
    import random
    from app import calibration
    rnd = random.Random(7)
    rows = []
    for _ in range(300):
        x = {k: rnd.random() for k in calibration.FEATURES}
        rows.append((x, int(x["skills"] + x["requirements"] > 1.0)))
    cal = calibration.fit(rows, steps=600)
    assert cal["coef"]["skills"] > 1 and cal["coef"]["requirements"] > 1 and abs(cal["coef"]["semantic"]) < 1
    f = tmp_path / "cal.json"
    f.write_text(_json.dumps({**cal, "pairs": 10}))
    assert calibration.load(str(f)) is None                               # too few pairs: ignored
    f.write_text(_json.dumps({**cal, "pairs": 300}))
    calibration.load.cache_clear()
    loaded = calibration.load(str(f))
    assert loaded and calibration.apply({k: 1.0 for k in calibration.FEATURES}, loaded) > 0.9
    calibration.load.cache_clear()
    assert calibration.load() is None                                    # nothing shipped in app/data


def test_esco_onet_loader_on_fixture(tmp_path):
    import csv as _csv
    from scripts import load_ontology as lo
    esco = tmp_path / "skills_en.csv"
    with esco.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=["conceptUri", "preferredLabel", "altLabels"])
        w.writeheader()
        w.writerow({"conceptUri": "u1", "preferredLabel": "PostgreSQL", "altLabels": "postgre sql\npostgres database"})
        w.writerow({"conceptUri": "u2", "preferredLabel": "MySQL", "altLabels": "my sql"})
        w.writerow({"conceptUri": "u3", "preferredLabel": "basket weaving", "altLabels": "weaving baskets"})
    rel = tmp_path / "rel.csv"
    with rel.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=["originalSkillUri", "relatedSkillUri", "relationType"])
        w.writeheader()
        w.writerow({"originalSkillUri": "u1", "relatedSkillUri": "u2", "relationType": "optional"})
    out = tmp_path / "onto"
    assert lo.main(["--esco", str(esco), "--esco-relations", str(rel), "--out", str(out)]) == 0
    import json as _json
    aliases = _json.loads((out / "aliases.json").read_text())
    assert aliases == {"MySQL": ["my sql"], "PostgreSQL": ["postgre sql", "postgres database"]}   # unmapped concept skipped
    assert _json.loads((out / "related.json").read_text()) == [["MySQL", "PostgreSQL"]]
