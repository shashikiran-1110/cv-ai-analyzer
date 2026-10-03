"""Built-in SAMPLE postings (fictional companies) so the app can be tried without network access.
Always labelled as sample data in the UI."""
from __future__ import annotations

from ..jobmodel import Job

_R = [
    ("Senior Data Engineer", "Northwind Analytics", "London, UK", "Full-time", """About the role
You'll design and run the batch and streaming pipelines behind our analytics platform.
Requirements
• 5+ years of experience in data engineering
• Strong Python and SQL
• Experience with Airflow, Spark and Kafka
• Hands-on with AWS (S3, Glue, Redshift) and data modeling
• Bachelor's degree in Computer Science or a related field
Nice to have
• Kubernetes and Terraform
• dbt and Snowflake"""),
    ("Data Engineer", "Blue Harbor Bank", "Remote (Europe)", "Full-time", """What you'll do
Build reliable ETL pipelines and data products for risk and finance teams.
What we're looking for
• 3+ years of experience building data pipelines
• Python, SQL and Spark
• Experience with Snowflake or BigQuery
• Git, CI/CD and unit testing
• Clear communication with stakeholders
Bonus
• Kafka, Airflow, Terraform"""),
    ("Analytics Engineer", "Tidewater Retail", "Manchester, UK", "Full-time", """Responsibilities
Own our dbt project and the semantic layer used by 200+ analysts.
Requirements
• 3+ years of experience in analytics engineering or BI
• Expert SQL and dbt
• Looker or Tableau
• Data modeling (star schemas) and testing
Nice to have
• Python, Airflow, BigQuery"""),
    ("Machine Learning Engineer", "Lumen Health AI", "Remote", "Full-time", """The role
Ship and monitor ML models that triage clinical documents.
Requirements
• 4+ years of experience in machine learning engineering
• Python, PyTorch or TensorFlow, scikit-learn
• NLP and LLMs in production
• Docker, Kubernetes and MLOps practices
• Master's degree in Computer Science, Statistics or similar
Preferred
• AWS SageMaker, Airflow"""),
    ("Backend Software Engineer (Python)", "Cobalt Payments", "Berlin, Germany", "Full-time", """About you
• 3+ years of professional experience building backend services
• Python with Django or FastAPI
• PostgreSQL and Redis
• REST APIs, microservices and system design
• Docker, CI/CD, unit testing, code review
Nice to have
• Kafka, Kubernetes, AWS"""),
    ("Frontend Engineer (React)", "Pixel & Pine", "Remote (worldwide)", "Contract", """Requirements
• 3+ years of experience with React and TypeScript
• HTML, CSS, accessibility and responsive design
• GraphQL or REST APIs
• Jest or Playwright testing
Nice to have
• Next.js, Figma"""),
    ("Full Stack Engineer", "Orbit Logistics", "Amsterdam, Netherlands", "Full-time", """You will
Build features end to end across our React frontend and Node.js services.
Requirements
• 4+ years of experience
• JavaScript/TypeScript, React, Node.js
• PostgreSQL or MongoDB
• AWS or GCP, Docker
• Agile/Scrum teamwork and communication"""),
    ("Data Scientist", "Meridian Insurance", "London, UK", "Full-time", """Requirements
• 3+ years of experience in data science
• Python (Pandas, NumPy, scikit-learn) and SQL
• Statistics, A/B testing and experimentation
• Data visualization (Tableau or Power BI)
• Master's degree or PhD in a quantitative field
Nice to have
• Spark, Databricks, deep learning"""),
    ("Data Analyst", "Greenfield Energy", "Bristol, UK", "Full-time", """What you'll need
• 2+ years of experience as a data analyst
• SQL and Excel
• Power BI or Tableau
• Statistics and stakeholder management
• Strong presentation skills
Bonus
• Python, Google Analytics"""),
    ("DevOps Engineer", "Stratus Cloudworks", "Remote (EMEA)", "Full-time", """Requirements
• 4+ years of experience in DevOps or SRE
• AWS or Azure, Terraform, Ansible
• Docker and Kubernetes
• CI/CD with GitHub Actions or Jenkins
• Linux, networking, Prometheus and Grafana observability
• Bash and Python scripting"""),
    ("Product Manager, Data Platform", "Northwind Analytics", "London, UK", "Full-time", """Requirements
• 4+ years of product management experience
• Roadmapping and stakeholder management
• Comfortable with SQL and data concepts
• Agile/Scrum, Jira
• Excellent communication and presentation skills"""),
    ("QA Automation Engineer", "Brightline Software", "Remote", "Full-time", """Requirements
• 3+ years in test automation
• Playwright, Cypress or Selenium
• JavaScript or Python
• CI/CD and Git
• API testing (REST)"""),
    ("Junior Data Engineer", "Kestrel Mobility", "Leeds, UK", "Full-time", """Requirements
• 0-2 years of experience (graduates welcome)
• Python and SQL
• Interest in Airflow, dbt and cloud (GCP)
• Git and unit testing
• Bachelor's degree in a STEM subject"""),
    ("Digital Marketing Manager", "Fable & Fern", "Remote (UK)", "Full-time", """Requirements
• 5+ years in digital marketing
• SEO, PPC/SEM and content marketing
• Google Analytics (GA4) and HubSpot CRM
• Budgeting and stakeholder management
• Excellent written communication"""),
]


def sample_jobs() -> list[Job]:
    return [Job(id=f"sample-{i}", title=t, company=c, location=loc, url="", posted="", description=d,
                employment_type=et, remote=("remote" in loc.lower()) or None, source="sample")
            for i, (t, c, loc, et, d) in enumerate(_R, 1)]
