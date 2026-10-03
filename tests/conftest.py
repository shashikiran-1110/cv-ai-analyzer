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
