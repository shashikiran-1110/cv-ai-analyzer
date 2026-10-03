import io
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


RESUME_LINES = [
    "Jane Doe - Data Engineer",
    "Summary: Data engineer with 6 years of experience building data pipelines.",
    "Experience",
    "Acme Analytics, Data Engineer, Jan 2019 - Present",
    "- Built ETL pipelines in Python and SQL on AWS; orchestrated with Airflow.",
    "- Processed terabytes with Spark and Kafka; modeled data in Snowflake and PostgreSQL.",
    "- Used Docker and Git daily; strong communication with stakeholders.",
    "Skills: Python, SQL, AWS, Airflow, Spark, Kafka, Snowflake, PostgreSQL, Docker, Git",
]


@pytest.fixture
def resume_pdf() -> bytes:
    return make_pdf(RESUME_LINES)


FAKE_DNS = {"localhost": ["127.0.0.1"], "internal.corp.example": ["10.0.0.5"],
            "rebind.example": ["93.184.216.34", "127.0.0.1"], "metadata.example": ["169.254.169.254"]}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """No real DNS in tests: unknown hostnames resolve to a public documentation-range address."""
    from app.net import safe_fetch

    async def resolve(host, port):
        return FAKE_DNS.get(host.lower(), ["93.184.216.34"])
    monkeypatch.setattr(safe_fetch, "resolve", resolve)


@pytest.fixture(autouse=True)
def fast_linkedin(monkeypatch):
    """No politeness sleeps between LinkedIn pages in tests."""
    from app import linkedin
    monkeypatch.setattr(linkedin, "PAGE_DELAY", 0)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Fresh database, caches, rate limits and run bus for every test."""
    from app.storage import db
    from app.runtime import ratelimit
    from app.runtime.events import bus
    from app.sources import base
    import os
    pg = os.getenv("TEST_DATABASE_URL")          # e.g. postgresql+psycopg://user@127.0.0.1:5432/cvtest
    if pg:
        db.reset(pg)
        db.meta.drop_all(db.engine())
        db.meta.create_all(db.engine())
    else:
        db.reset(f"sqlite:///{tmp_path}/test.db")
    from app.api import accounts
    accounts._cache.clear()
    ratelimit.reset()
    base.FEED_CACHE.clear()
    bus.runs.clear()
    monkeypatch.setenv("SEARCH_CACHE_TTL", "1800")
    try:
        from app import main
        main.SEARCHES.clear()
        main.ANALYSES.clear()
    except Exception:
        pass
    yield
    db.reset()
