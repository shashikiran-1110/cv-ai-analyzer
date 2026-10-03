"""Skill taxonomy: canonical name -> (category, aliases). Matching is whole-word, case-insensitive."""
from __future__ import annotations

import re
from functools import lru_cache

_RAW: dict[str, dict[str, list[str]]] = {
    "Languages": {
        "Python": ["python"], "Java": ["java"], "JavaScript": ["javascript", "js", "ecmascript"],
        "TypeScript": ["typescript"], "C++": ["c++"], "C#": ["c#"], "Go": ["golang", "go lang"],
        "Rust": ["rust"], "Ruby": ["ruby"], "PHP": ["php"], "Swift": ["swift"], "Kotlin": ["kotlin"],
        "Scala": ["scala"], "R": ["r programming", "rstudio", "r language"], "SQL": ["sql"],
        "Bash": ["bash", "shell scripting", "shell script"], "MATLAB": ["matlab"], "Perl": ["perl"],
        "C": ["c programming", "c language"], "Dart": ["dart"], "Objective-C": ["objective-c"],
    },
    "Web & Frameworks": {
        "React": ["react", "react.js", "reactjs"], "Angular": ["angular", "angularjs"],
        "Vue": ["vue", "vue.js", "vuejs"], "Next.js": ["next.js", "nextjs"],
        "Node.js": ["node.js", "nodejs", "node"], "Express": ["express.js", "expressjs"],
        "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"],
        "Spring": ["spring", "spring boot", "springboot"], ".NET": [".net", "dotnet", "asp.net"],
        "Rails": ["ruby on rails", "rails"], "Laravel": ["laravel"], "HTML": ["html", "html5"],
        "CSS": ["css", "css3", "sass", "scss"], "Tailwind": ["tailwind", "tailwindcss"],
        "GraphQL": ["graphql"], "REST APIs": ["rest", "restful", "rest api", "rest apis", "restful apis"],
        "Microservices": ["microservices", "microservice"], "gRPC": ["grpc"],
        "React Native": ["react native"], "Flutter": ["flutter"],
    },
    "Cloud & DevOps": {
        "AWS": ["aws", "amazon web services"], "Azure": ["azure"], "GCP": ["gcp", "google cloud"],
        "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"], "Terraform": ["terraform"],
        "Ansible": ["ansible"], "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous delivery",
                                          "continuous deployment"],
        "Jenkins": ["jenkins"], "GitHub Actions": ["github actions"], "GitLab CI": ["gitlab ci"],
        "Linux": ["linux", "unix"], "Git": ["git", "github", "gitlab", "bitbucket"],
        "Serverless": ["serverless", "lambda"], "Prometheus": ["prometheus"], "Grafana": ["grafana"],
        "Datadog": ["datadog"], "Observability": ["observability", "monitoring"],
        "Networking": ["tcp/ip", "networking", "dns", "load balancing"], "Security": ["cybersecurity", "infosec", "owasp"],
    },
    "Data & ML": {
        "Machine Learning": ["machine learning", "ml"], "Deep Learning": ["deep learning"],
        "NLP": ["nlp", "natural language processing"], "Computer Vision": ["computer vision"],
        "LLMs": ["llm", "llms", "large language models", "generative ai", "genai", "gen ai"],
        "TensorFlow": ["tensorflow"], "PyTorch": ["pytorch"], "scikit-learn": ["scikit-learn", "sklearn"],
        "Pandas": ["pandas"], "NumPy": ["numpy"], "Spark": ["spark", "pyspark"], "Hadoop": ["hadoop"],
        "Kafka": ["kafka"], "Airflow": ["airflow"], "dbt": ["dbt"], "Snowflake": ["snowflake"],
        "BigQuery": ["bigquery"], "Redshift": ["redshift"], "Databricks": ["databricks"],
        "ETL": ["etl", "elt", "data pipelines", "data pipeline"], "Data Modeling": ["data modeling", "data modelling"],
        "Statistics": ["statistics", "statistical analysis", "statistical"], "A/B Testing": ["a/b testing", "ab testing", "experimentation"],
        "Tableau": ["tableau"], "Power BI": ["power bi", "powerbi"], "Looker": ["looker"],
        "Excel": ["excel", "microsoft excel", "spreadsheets"], "Data Visualization": ["data visualization", "data visualisation"],
        "MLOps": ["mlops"],
    },
    "Databases": {
        "PostgreSQL": ["postgresql", "postgres"], "MySQL": ["mysql"], "MongoDB": ["mongodb", "mongo"],
        "Redis": ["redis"], "Elasticsearch": ["elasticsearch", "elastic search", "opensearch"],
        "DynamoDB": ["dynamodb"], "Cassandra": ["cassandra"], "Oracle": ["oracle"],
        "SQL Server": ["sql server", "mssql", "t-sql"], "NoSQL": ["nosql"],
    },
    "Engineering Practices": {
        "Agile": ["agile"], "Scrum": ["scrum"], "Kanban": ["kanban"], "TDD": ["tdd", "test-driven development"],
        "Unit Testing": ["unit testing", "unit tests", "pytest", "junit", "jest"],
        "System Design": ["system design", "distributed systems", "scalability"],
        "Code Review": ["code review", "code reviews"], "Jira": ["jira"],
        "OOP": ["oop", "object-oriented", "object oriented"], "Data Structures": ["data structures", "algorithms"],
        "API Design": ["api design", "apis"], "QA Automation": ["selenium", "cypress", "playwright", "test automation"],
    },
    "Business & Product": {
        "Project Management": ["project management", "pmp"], "Product Management": ["product management", "product roadmap"],
        "Stakeholder Management": ["stakeholder management", "stakeholders"], "Roadmapping": ["roadmap", "roadmapping"],
        "Salesforce": ["salesforce"], "CRM": ["crm", "hubspot"], "SEO": ["seo", "search engine optimization"],
        "Google Analytics": ["google analytics", "ga4"], "Content Marketing": ["content marketing", "content strategy"],
        "Digital Marketing": ["digital marketing", "performance marketing", "sem", "ppc"],
        "Financial Modeling": ["financial modeling", "financial modelling", "financial analysis"],
        "Accounting": ["accounting", "gaap", "ifrs"], "Budgeting": ["budgeting", "forecasting"],
        "Customer Success": ["customer success", "account management"], "Sales": ["b2b sales", "sales", "lead generation"],
        "Recruiting": ["recruiting", "talent acquisition", "sourcing"], "Figma": ["figma"],
        "UX Design": ["ux", "user experience", "ui/ux", "user research"], "Business Analysis": ["business analysis", "requirements gathering"],
        "SAP": ["sap"], "Supply Chain": ["supply chain", "logistics", "procurement"],
        "Compliance": ["compliance", "regulatory", "gdpr", "hipaa", "sox"],
    },
    "Professional Skills": {
        "Communication": ["communication", "communication skills", "written communication", "verbal communication"],
        "Leadership": ["leadership", "team lead", "people management", "mentoring", "mentorship"],
        "Problem Solving": ["problem solving", "problem-solving", "analytical skills", "critical thinking"],
        "Collaboration": ["collaboration", "cross-functional", "teamwork", "team player"],
        "Presentation": ["presentation skills", "public speaking", "presentations"],
        "Time Management": ["time management", "prioritization"],
    },
}

# Skills so generic they should never alone drive a high score; counted at half weight.
SOFT_CATEGORY = "Professional Skills"


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, str, re.Pattern]]:
    out = []
    for category, skills in _RAW.items():
        for canon, aliases in skills.items():
            # short canonical names ("R", "Go", "C") are ambiguous words; they match only via explicit aliases
            names = aliases + ([canon] if len(canon) > 2 else [])
            alts = sorted({a.lower() for a in names}, key=len, reverse=True)
            body = "|".join(re.escape(a) for a in alts)
            pat = re.compile(rf"(?<![A-Za-z0-9_+#.]){body}(?![A-Za-z0-9_+#]|\.[A-Za-z0-9])", re.IGNORECASE)
            out.append((canon, category, pat))
    return out


def category_of(skill: str) -> str:
    for cat, skills in _RAW.items():
        if skill in skills:
            return cat
    return "Other"


def extract_skills(text: str) -> set[str]:
    return {canon for canon, _, pat in _compiled() if pat.search(text)}
