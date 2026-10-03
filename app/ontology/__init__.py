"""Skill ontology (ROADMAP §6.4): relations on top of the taxonomy in `app.skills`.

- implies: having the left skill shows the right one (Django ⇒ Python). Full credit, shown as "implied by Django".
- related: substitutes from the same family (React ~ Vue, PostgreSQL ~ MySQL). Partial credit (RELATED_CREDIT),
  shown as "partial: you have MySQL (related)".
Optional ESCO/O*NET data (scripts/load_ontology.py) adds alternative labels when present; the engine works without.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

RELATED_CREDIT = 0.5
DATA = Path(__file__).resolve().parent.parent / "data" / "ontology"

IMPLIES: dict[str, list[str]] = {
    "Django": ["Python"], "Flask": ["Python"], "FastAPI": ["Python"], "Pandas": ["Python"], "NumPy": ["Python"],
    "scikit-learn": ["Python", "Machine Learning"], "PyTorch": ["Deep Learning"], "TensorFlow": ["Deep Learning"],
    "Hugging Face": ["Deep Learning", "NLP"], "Deep Learning": ["Machine Learning"], "NLP": ["Machine Learning"],
    "Computer Vision": ["Machine Learning"], "LangChain": ["LLMs"], "RAG": ["LLMs"],
    "Spring": ["Java"], "Rails": ["Ruby"], "Laravel": ["PHP"], "Express": ["Node.js"], "Node.js": ["JavaScript"],
    "React": ["JavaScript"], "Vue": ["JavaScript"], "Angular": ["TypeScript"], "Next.js": ["React"], "Redux": ["React"],
    "React Native": ["React"], "jQuery": ["JavaScript"], "TypeScript": ["JavaScript"],
    "SwiftUI": ["Swift", "iOS"], "Jetpack Compose": ["Kotlin", "Android"], "Flutter": ["Dart"],
    "Helm": ["Kubernetes"], "Argo CD": ["Kubernetes"], "OpenShift": ["Kubernetes"], "Kubeflow": ["Kubernetes"],
    "Istio": ["Kubernetes"],
    "dbt": ["SQL"], "BigQuery": ["SQL", "GCP"], "Snowflake": ["SQL"], "Redshift": ["SQL", "AWS"], "PostgreSQL": ["SQL"],
    "MySQL": ["SQL"], "SQL Server": ["SQL"], "Oracle": ["SQL"], "SQLite": ["SQL"], "Presto/Trino": ["SQL"],
    "Databricks": ["Spark"], "SageMaker": ["AWS"], "AWS Glue": ["AWS", "ETL"], "EMR": ["AWS", "Spark"],
    "Kinesis": ["AWS"], "DynamoDB": ["AWS", "NoSQL"], "CloudFormation": ["AWS"], "Vertex AI": ["GCP"],
    "Azure Data Factory": ["Azure", "ETL"], "Cosmos DB": ["Azure", "NoSQL"], "MongoDB": ["NoSQL"], "Cassandra": ["NoSQL"],
    "GitHub Actions": ["CI/CD"], "GitLab CI": ["CI/CD"], "Jenkins": ["CI/CD"], "Scrum": ["Agile"], "Kanban": ["Agile"],
    "TDD": ["Unit Testing"], "Tableau": ["Data Visualization"], "Power BI": ["Data Visualization"],
    "Looker": ["Data Visualization"], "DAX": ["Power BI"], "Bookkeeping": ["Accounting"], "Fivetran": ["ETL"],
    "Airflow": ["ETL"], "Accounts Payable": ["Accounting"], "Accounts Receivable": ["Accounting"],
    "Reconciliation": ["Accounting"], "Auditing": ["Accounting"], "Critical Care": ["Patient Care"],
    "Triage": ["Patient Assessment"], "Medication Administration": ["Patient Care"],
}

RELATED: list[set[str]] = [
    {"React", "Vue", "Angular", "Svelte"}, {"AWS", "Azure", "GCP"},
    {"PostgreSQL", "MySQL", "SQL Server", "Oracle", "SQLite"}, {"MongoDB", "DynamoDB", "Cassandra", "Cosmos DB", "Firebase"},
    {"Kafka", "Kinesis", "Event-Driven Architecture"}, {"Airflow", "Azure Data Factory", "AWS Glue", "Fivetran"},
    {"Snowflake", "BigQuery", "Redshift", "Databricks"}, {"TensorFlow", "PyTorch"}, {"Tableau", "Power BI", "Looker"},
    {"Terraform", "CloudFormation", "Pulumi"}, {"Jenkins", "GitHub Actions", "GitLab CI"},
    {"Prometheus", "Grafana", "Datadog", "Observability"}, {"Java", "Kotlin", "Scala"}, {"C", "C++"},
    {"Django", "Flask", "FastAPI"}, {"Scrum", "Kanban"}, {"Spark", "Flink", "Hadoop", "Apache Beam"},
    {"SAS", "SPSS", "Stata", "R"}, {"Salesforce", "CRM"}, {"Swift", "Objective-C"}, {"React Native", "Flutter"},
    {"MLflow", "Kubeflow", "MLOps", "SageMaker", "Vertex AI"}, {"Project Management", "PRINCE2"}, {"ERP", "SAP"},
    {"Marketing Automation", "CRM"}, {"Paid Social", "Digital Marketing"}, {"Figma", "Sketch"},
    {"Presto/Trino", "Hive"}, {"Elasticsearch", "Vector Databases"}, {"Ansible", "Terraform"},
    {"Accounts Payable", "Accounts Receivable", "Bookkeeping"}, {"Lesson Planning", "Curriculum Development"},
    {"Nursing", "Patient Care"}, {"Contract Drafting", "Corporate Law"},
]


@lru_cache(maxsize=1)
def _implied_closure() -> dict[str, frozenset[str]]:
    out: dict[str, frozenset[str]] = {}

    def walk(s: str, seen: set[str]) -> set[str]:
        for t in IMPLIES.get(s, []):
            if t not in seen:
                seen.add(t)
                walk(t, seen)
        return seen
    for s in IMPLIES:
        out[s] = frozenset(walk(s, set()))
    return out


def implied_by(owned: set[str]) -> dict[str, str]:
    """{implied skill: the owned skill that implies it} for skills not already owned."""
    out: dict[str, str] = {}
    for s in sorted(owned):
        for t in _implied_closure().get(s, ()):
            if t not in owned:
                out.setdefault(t, s)
    return out


@lru_cache(maxsize=1)
def _related_index() -> dict[str, frozenset[str]]:
    idx: dict[str, set[str]] = {}
    for group in RELATED + _extra_related():
        for s in group:
            idx.setdefault(s, set()).update(group - {s})
    return {k: frozenset(v) for k, v in idx.items()}


def _extra_related() -> list[set[str]]:
    f = DATA / "related.json"          # written by scripts/load_ontology.py from ESCO/O*NET when available
    try:
        return [set(g) for g in json.loads(f.read_text())]
    except (OSError, ValueError):
        return []


def credit(skill: str, owned: set[str], implied: Optional[dict[str, str]] = None) -> tuple[float, str, str]:
    """(credit 0-1, how, via) for one required skill: exact | implied | related | missing."""
    if skill in owned:
        return 1.0, "exact", ""
    implied = implied_by(owned) if implied is None else implied
    if skill in implied:
        return 1.0, "implied", implied[skill]
    rel = sorted(_related_index().get(skill, frozenset()) & owned)
    if rel:
        return RELATED_CREDIT, "related", rel[0]
    return 0.0, "missing", ""


def relations_for(skill: str) -> dict:
    return {"implies": sorted(_implied_closure().get(skill, ())), "related": sorted(_related_index().get(skill, ())),
            "implied_by": sorted(s for s, ts in _implied_closure().items() if skill in ts)}
