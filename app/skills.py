"""Skill taxonomy: canonical name -> (category, aliases). Matching is whole-word, case-insensitive."""
from __future__ import annotations

import re
from functools import lru_cache

_RAW: dict[str, dict[str, list[str]]] = {
    "Languages": {
        "Python": ["python"], "Java": ["java"], "JavaScript": ["javascript", "js", "ecmascript"],
        "TypeScript": ["typescript"], "C++": ["c++"], "C#": ["c#"], "Go": ["golang", "go lang"],
        "Rust": ["rust"], "Ruby": ["ruby programming", "ruby language"], "PHP": ["php"], "Swift": ["swift programming", "swift language"], "Kotlin": ["kotlin"],
        "Scala": ["scala"], "R": ["r programming", "rstudio", "r language"], "SQL": ["sql"],
        "Bash": ["bash", "shell scripting", "shell script"], "MATLAB": ["matlab"], "Perl": ["perl"],
        "C": ["c programming", "c language"], "Dart": ["dart"], "Objective-C": ["objective-c"],
        "Elixir": ["elixir"], "Haskell": ["haskell"], "Clojure": ["clojure"], "Solidity": ["solidity"],
        "Groovy": ["groovy"], "VBA": ["vba"], "Lua": ["lua"], "Julia": ["julia language"],
    },
    "Mobile": {
        "iOS": ["ios"], "Android": ["android"], "SwiftUI": ["swiftui"], "Jetpack Compose": ["jetpack compose"],
        "Xamarin": ["xamarin"],
    },
    "Web & Frameworks": {
        "React": ["re:react(?!\\s+(?:to|quickly|fast|swiftly|calmly))", "react.js", "reactjs"], "Angular": ["angular", "angularjs"],
        "Vue": ["vue", "vue.js", "vuejs"], "Next.js": ["next.js", "nextjs"],
        "Node.js": ["node.js", "nodejs", "node js"], "Express": ["express.js", "expressjs"],
        "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"],
        "Spring": ["spring boot", "springboot", "spring framework", "spring mvc", "spring cloud"], ".NET": [".net", "dotnet", "asp.net"],
        "Rails": ["ruby on rails"], "Laravel": ["laravel"], "HTML": ["html", "html5"],
        "CSS": ["css", "css3", "sass", "scss"], "Tailwind": ["tailwind", "tailwindcss"],
        "GraphQL": ["graphql"], "REST APIs": ["restful", "rest api", "rest apis", "restful apis", "re:rest(?:ful)?\\s*(?:/\\s*graphql\\s*)?(?:api|apis|services|web services|endpoints)"],
        "Microservices": ["microservices", "microservice"], "gRPC": ["grpc"],
        "React Native": ["react native"], "Flutter": ["flutter"], "Svelte": ["svelte", "sveltekit"],
        "Redux": ["redux"], "jQuery": ["jquery"], "Webpack": ["webpack"], "WebSockets": ["websockets", "websocket"],
        "Accessibility": ["accessibility", "wcag", "a11y"],
    },
    "Cloud & DevOps": {
        "AWS": ["aws", "amazon web services"], "Azure": ["azure"], "GCP": ["gcp", "google cloud"],
        "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"], "Terraform": ["terraform"],
        "Ansible": ["ansible"], "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous delivery",
                                          "continuous deployment"],
        "Jenkins": ["jenkins"], "GitHub Actions": ["github actions"], "GitLab CI": ["gitlab ci"],
        "Linux": ["linux", "unix"], "Git": ["git", "github", "gitlab", "bitbucket"],
        "Serverless": ["serverless", "aws lambda", "lambda functions"], "Prometheus": ["prometheus"], "Grafana": ["grafana"],
        "Datadog": ["datadog"], "Observability": ["observability", "monitoring"],
        "Networking": ["tcp/ip", "networking", "dns", "load balancing"], "Security": ["cybersecurity", "infosec", "owasp"],
        "CloudFormation": ["cloudformation"], "Pulumi": ["pulumi"], "Helm": ["helm charts", "helm"], "Argo CD": ["argocd", "argo cd"],
        "Istio": ["istio", "service mesh"], "Nginx": ["nginx"], "OpenShift": ["openshift"], "Vault": ["hashicorp vault"],
        "IAM": ["iam", "identity and access management"], "SIEM": ["siem", "splunk"], "Penetration Testing": ["penetration testing", "pentesting", "pen testing"],
    },
    "Data & ML": {
        "Machine Learning": ["machine learning", "ml"], "Deep Learning": ["deep learning"],
        "NLP": ["nlp", "natural language processing"], "Computer Vision": ["computer vision"],
        "LLMs": ["llm", "llms", "large language models", "generative ai", "genai", "gen ai"],
        "TensorFlow": ["tensorflow"], "PyTorch": ["pytorch"], "scikit-learn": ["scikit-learn", "sklearn"],
        "Pandas": ["pandas"], "NumPy": ["numpy"], "Spark": ["pyspark", "apache spark", "spark sql", "spark streaming"], "Hadoop": ["hadoop"],
        "Kafka": ["kafka"], "Airflow": ["airflow"], "dbt": ["dbt"], "Snowflake": ["snowflake"],
        "BigQuery": ["bigquery"], "Redshift": ["redshift"], "Databricks": ["databricks"],
        "ETL": ["etl", "elt", "data pipelines", "data pipeline"], "Data Modeling": ["data modeling", "data modelling"],
        "Statistics": ["statistics", "statistical analysis", "statistical"], "A/B Testing": ["a/b testing", "ab testing", "experimentation"],
        "Tableau": ["tableau"], "Power BI": ["power bi", "powerbi"], "Looker": ["looker"],
        "Excel": ["re:excel(?!\\s+(?:in|at|as|when|with|under)\\b)", "microsoft excel", "ms excel", "spreadsheets"], "Data Visualization": ["data visualization", "data visualisation"],
        "MLOps": ["mlops"], "MLflow": ["mlflow"], "Kubeflow": ["kubeflow"], "Hugging Face": ["hugging face", "huggingface", "transformers library"],
        "LangChain": ["langchain", "llamaindex"], "RAG": ["rag", "retrieval-augmented generation", "retrieval augmented generation"],
        "Vector Databases": ["vector database", "vector databases", "pinecone", "weaviate", "pgvector", "faiss"],
        "Prompt Engineering": ["prompt engineering"], "Flink": ["flink"], "Apache Beam": ["apache beam"], "Hive": ["apache hive", "hiveql"],
        "Presto/Trino": ["presto", "trino", "athena"], "Delta Lake": ["delta lake", "lakehouse"], "Fivetran": ["fivetran", "airbyte"],
        "Kinesis": ["kinesis"], "AWS Glue": ["aws glue"], "EMR": ["amazon emr", "aws emr"], "SageMaker": ["sagemaker"],
        "Vertex AI": ["vertex ai"], "Azure Data Factory": ["azure data factory", "adf"], "DAX": ["dax", "power query"],
        "SAS": ["sas"], "SPSS": ["spss"], "Stata": ["stata"], "Forecasting Models": ["time series", "forecasting models"],
    },
    "Databases": {
        "PostgreSQL": ["postgresql", "postgres"], "MySQL": ["mysql"], "MongoDB": ["mongodb", "mongo"],
        "Redis": ["redis"], "Elasticsearch": ["elasticsearch", "elastic search", "opensearch"],
        "DynamoDB": ["dynamodb"], "Cassandra": ["cassandra"], "Oracle": ["oracle"],
        "SQL Server": ["sql server", "mssql", "t-sql"], "NoSQL": ["nosql"], "Neo4j": ["neo4j", "graph database"],
        "Firebase": ["firebase", "firestore"], "SQLite": ["sqlite"], "Cosmos DB": ["cosmos db", "cosmosdb"], "Supabase": ["supabase"],
    },
    "Engineering Practices": {
        "Agile": ["agile methodology", "agile methodologies", "agile development", "agile practices", "agile/scrum"], "Scrum": ["scrum"], "Kanban": ["kanban"], "TDD": ["tdd", "test-driven development"],
        "Unit Testing": ["unit testing", "unit tests", "pytest", "junit", "jest"],
        "System Design": ["system design", "distributed systems", "scalability"],
        "Code Review": ["code review", "code reviews"], "Jira": ["jira"],
        "OOP": ["oop", "object-oriented", "object oriented"], "Data Structures": ["data structures", "algorithms"],
        "API Design": ["api design", "apis"], "QA Automation": ["selenium", "cypress", "playwright", "test automation"],
        "Design Patterns": ["design patterns", "solid principles", "domain-driven design", "ddd"],
        "Event-Driven Architecture": ["event-driven", "event driven", "pub/sub", "message queues", "rabbitmq", "sqs"],
        "Performance Optimization": ["performance optimization", "performance tuning", "profiling"],
    },
    "Business & Product": {
        "Project Management": ["project management", "pmp"], "Product Management": ["product management", "product roadmap"],
        "Stakeholder Management": ["stakeholder management", "stakeholders"], "Roadmapping": ["roadmap", "roadmapping"],
        "Salesforce": ["salesforce"], "CRM": ["crm", "hubspot"], "SEO": ["seo", "search engine optimization"],
        "Google Analytics": ["google analytics", "ga4"], "Content Marketing": ["content marketing", "content strategy"],
        "Digital Marketing": ["digital marketing", "performance marketing", "sem", "ppc"],
        "Financial Modeling": ["financial modeling", "financial modelling", "financial analysis"],
        "Accounting": ["accounting", "gaap", "ifrs"], "Budgeting": ["budgeting", "forecasting"],
        "Customer Success": ["customer success", "account management"], "Sales": ["b2b sales", "saas sales", "sales experience", "quota", "lead generation", "business development", "pipeline generation"],
        "Recruiting": ["recruiting", "talent acquisition", "candidate sourcing"], "Figma": ["figma"],
        "UX Design": ["ux", "user experience", "ui/ux", "user research"], "Business Analysis": ["business analysis", "requirements gathering"],
        "SAP": ["sap"], "Supply Chain": ["supply chain", "logistics", "procurement"],
        "Compliance": ["compliance", "gdpr", "hipaa", "sox", "soc 2", "iso 27001"],
        "OKRs": ["okrs", "okr"], "Product Analytics": ["product analytics", "amplitude", "mixpanel"],
        "Marketing Automation": ["marketing automation", "marketo", "mailchimp", "braze"],
        "Paid Social": ["paid social", "meta ads", "facebook ads", "linkedin ads", "google ads"],
        "Copywriting": ["copywriting", "copy writing"], "Negotiation": ["negotiation"],
        "Customer Support": ["customer support", "customer service", "zendesk", "intercom"],
        "Six Sigma": ["six sigma", "lean six sigma", "lean manufacturing"], "PRINCE2": ["prince2"], "ITIL": ["itil"],
        "ERP": ["erp", "netsuite", "oracle erp", "workday"], "Bookkeeping": ["bookkeeping", "quickbooks", "xero"],
        "Patient Care": ["patient care", "clinical care", "bedside"], "EHR": ["ehr", "emr", "electronic health records", "epic systems", "cerner"],
        "Adobe Creative Suite": ["adobe creative suite", "photoshop", "illustrator", "indesign", "after effects"],
        "Prototyping": ["prototyping", "wireframing", "wireframes"], "Design Systems": ["design systems", "design system"],
        "Sketch": ["sketch app"], "Certifications": ["aws certified", "azure certified", "cka", "cissp", "cpa", "cfa", "acca"],
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

NO_CANON_ALIAS = {"Sales", "Recruiting", "Sketch", "Certifications", "Prototyping",
                  "Swift", "Ruby", "Spring", "Rails", "Spark", "Agile"}

# ROADMAP D4: everyday words that are also skills count only with a context word within ±CONTEXT_WINDOW tokens.
CONTEXT_WINDOW = 8
AMBIGUOUS: dict[str, tuple[list[str], set[str]]] = {
    "Spring": (["spring"], {"java", "boot", "framework", "mvc", "kotlin", "jpa", "hibernate", "microservices", "maven",
                            "gradle", "j2ee", "jee", "beans", "security", "cloud", "data"}),
    "Swift": (["swift"], {"ios", "xcode", "apple", "cocoa", "objective-c", "swiftui", "uikit", "macos", "watchos",
                          "ipados", "cocoapods", "kotlin", "mobile", "app", "apps"}),
    "Rails": (["rails"], {"ruby", "activerecord", "rspec", "rubocop", "sidekiq", "ror", "gem", "gems", "postgresql"}),
    "Agile": (["agile"], {"scrum", "kanban", "sprint", "sprints", "methodology", "methodologies", "practices", "ceremonies",
                          "development", "delivery", "environment", "jira", "safe", "retrospectives", "standups",
                          "stand-ups", "team", "teams", "framework", "coach", "squads"}),
    "Ruby": (["ruby"], {"rails", "gem", "gems", "rspec", "rubocop", "sinatra", "programming", "developer", "engineer",
                        "language", "bundler", "rake", "ror", "erb", "python", "java", "javascript", "php", "go"}),
    "Spark": (["spark"], {"apache", "hadoop", "databricks", "scala", "etl", "streaming", "sql", "emr", "hive", "kafka",
                          "data", "rdd", "dataframes", "dataframe", "pipelines", "big", "airflow", "python", "glue"}),
}
_SEASON_YEAR = re.compile(r"\b(?:spring|summer|fall|autumn|winter)\s+(?:term\s+|semester\s+|of\s+)?'?\d{2,4}\b", re.I)
_TOKEN = re.compile(r"[a-z0-9+#][a-z0-9+#.\-]*", re.I)

# ROADMAP D5: negation cues (clause-bounded) for skills in job postings.
_CLAUSE_BREAK = re.compile(r"[.;:!?\n•]|\bbut\b|\bhowever\b|\bwhereas\b", re.I)
_NEG_BEFORE = {"no", "not", "without", "never", "non", "nor"}
_NEG_AFTER = re.compile(r"^\W*(?:\w+\W+){0,4}?(?:is\s+|are\s+)?(?:not|n't)\s+(?:required|needed|necessary|a requirement|mandatory)", re.I)

# Skills so generic they should never alone drive a high score; counted at half weight.
SOFT_CATEGORY = "Professional Skills"


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, str, re.Pattern]]:
    out = []
    for category, skills in _RAW.items():
        for canon, aliases in skills.items():
            # short canonical names ("R", "Go", "C") are ambiguous words; they match only via explicit aliases
            # skills whose canonical name is also an everyday word match only via their explicit aliases
            auto = len(canon) > 2 and canon not in NO_CANON_ALIAS and not any(a.startswith("re:") for a in aliases)
            names = aliases + ([canon] if auto else [])
            alts = sorted({a.lower() for a in names}, key=len, reverse=True)
            if not alts:
                continue
            # aliases prefixed "re:" are raw regexes (used to exclude common false positives)
            body = "|".join(a[3:] if a.startswith("re:") else re.escape(a) for a in alts)
            # group the alternation so the boundary guards apply to every alias, not just the first/last
            pat = re.compile(rf"(?<![A-Za-z0-9_+#.])(?:{body})(?![A-Za-z0-9_+#]|\.[A-Za-z0-9])", re.IGNORECASE)
            out.append((canon, category, pat))
    return out


def category_of(skill: str) -> str:
    for cat, skills in _RAW.items():
        if skill in skills:
            return cat
    return "Other"


@lru_cache(maxsize=1)
def _ambiguous_compiled() -> list[tuple[str, re.Pattern, set[str]]]:
    return [(canon, re.compile(rf"(?<![A-Za-z0-9_+#.])(?:{'|'.join(map(re.escape, words))})(?![A-Za-z0-9_+#])", re.I), ctx)
            for canon, (words, ctx) in AMBIGUOUS.items()]


def _has_context(text: str, start: int, end: int, ctx: set[str]) -> bool:
    before = _TOKEN.findall(text[max(0, start - 200):start])[-CONTEXT_WINDOW:]
    after = _TOKEN.findall(text[end:end + 200])[:CONTEXT_WINDOW]
    return any(t.lower().strip(".-") in ctx for t in before + after)


def _matches(text: str) -> list[tuple[str, int, int]]:
    """Every (skill, start, end) occurrence, after removing season-year phrases and applying context rules."""
    clean = _SEASON_YEAR.sub(lambda m: " " * len(m.group(0)), text)   # keep offsets stable
    out = [(canon, m.start(), m.end()) for canon, _, pat in _compiled() for m in pat.finditer(clean)]
    for canon, pat, ctx in _ambiguous_compiled():
        out += [(canon, m.start(), m.end()) for m in pat.finditer(clean) if _has_context(clean, m.start(), m.end(), ctx)]
    return out


def _negated(text: str, start: int, end: int) -> bool:
    clause_start = max([m.end() for m in _CLAUSE_BREAK.finditer(text, 0, start)] or [0])
    before = [t.lower() for t in _TOKEN.findall(text[clause_start:start])][-6:]
    if any(t in _NEG_BEFORE or t.endswith("n't") for t in before):
        return True
    nxt = _CLAUSE_BREAK.search(text, end)
    return bool(_NEG_AFTER.match(text[end: nxt.start() if nxt else len(text)]))


def extract_skills(text: str) -> set[str]:
    """Skills mentioned anywhere (used for resumes)."""
    return {canon for canon, _, _ in _matches(text)}


def extract_posting_skills(text: str) -> tuple[set[str], set[str]]:
    """(required-or-mentioned skills, negated skills) for job-posting text.

    A skill is negated (“No Java experience required”) only if *every* mention of it is negated."""
    seen: dict[str, bool] = {}
    for canon, start, end in _matches(text):
        neg = _negated(text, start, end)
        seen[canon] = seen.get(canon, True) and neg
    return {k for k, neg in seen.items() if not neg}, {k for k, neg in seen.items() if neg}


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    out = {}
    for skills in _RAW.values():
        for canon, aliases in skills.items():
            out[canon.lower()] = canon
            for a in aliases:
                if not a.startswith("re:"):
                    out.setdefault(a.lower(), canon)
    return out


def canonical(name: str) -> str | None:
    """Map a user-typed skill (any alias, any case) to its canonical name, or None if unknown."""
    return _lookup().get(name.strip().lower())


def all_skills() -> list[dict]:
    return sorted(({"name": n, "category": c} for c, sk in _RAW.items() for n in sk), key=lambda x: x["name"].lower())
