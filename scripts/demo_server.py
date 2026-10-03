"""Demo server: the real app, but LinkedIn and the OpenAI API are faked locally.

Lets you try the whole UI offline / without LinkedIn access or a paid key:
    python scripts/demo_server.py [port]        # default 8765
In AI settings use provider OpenAI, key `sk-good`, model `gpt-5.6-luna` (any other key/model is rejected,
which demonstrates the verification errors). Jobs and AI replies are canned sample data.
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from app import config, linkedin, main

config.OPENAI_BASE_URL = f"http://127.0.0.1:{PORT}/fake-openai/v1"
D = "Requirements\n- {y}+ years of experience\n- {s}\n" + "Nice to have\n- Kubernetes\n- Terraform\n" + "Join our team and grow. " * 8
JOBS = [
 ("Senior Data Engineer","Acme","Python, SQL, AWS and Airflow",5),
 ("Data Engineer","Globex","Python, Spark, Kafka and Snowflake",3),
 ("Machine Learning Engineer","Initech","Python, PyTorch, TensorFlow and MLOps, Docker",4),
 ("Analytics Engineer","Hooli","SQL, dbt, Looker and BigQuery",3),
 ("Backend Engineer","Umbrella","Java, Spring, Kubernetes, Kafka and PostgreSQL",5),
 ("Platform Engineer","Stark","Kubernetes, Terraform, AWS, Go and Prometheus",6),
 ("Frontend Developer <img src=x onerror=alert(1)>","Wayne","React, TypeScript, CSS and GraphQL",3),
]
async def fake(title, location, count, hours=None, on_progress=None, client=None, **kw):
    print("search:", title, location, count, hours, kw, flush=True)
    out=[]
    for i in range(count):
        t,c,s,y = JOBS[i % len(JOBS)]
        await on_progress("searching", i+1, count); await asyncio.sleep(0.04)
        out.append(linkedin.Job(id=str(1000+i), title=t, company=f"{c} {i}", location="London", url=f"https://www.linkedin.com/jobs/view/{1000+i}",
            posted="2026-10-01", seniority="Mid-Senior level", description=D.format(y=y, s=s) if i % 9 != 8 else ""))
    for i in range(count):
        await on_progress("details", i+1, count); await asyncio.sleep(0.02)
    return out
linkedin.search_jobs = fake

@main.app.get("/fake-openai/v1/models/{model}")
async def fm(model: str, request: Request):
    key = request.headers.get("authorization", "")
    if key != "Bearer sk-good": return JSONResponse({"error": {"message": f"Incorrect API key provided: {key[7:]}"}}, 401)
    if model != "gpt-5.6-luna": return JSONResponse({"error": {"message": f"The model `{model}` does not exist"}}, 404)
    return {"id": model}

@main.app.post("/fake-openai/v1/chat/completions")
async def fc(request: Request):
    body = await request.json()
    if request.headers.get("authorization") != "Bearer sk-good": return JSONResponse({"error": {"message": "bad key"}}, 401)
    if body.get("stream"):
        user = body["messages"][-1]["content"]
        reply = f"## Reply\n\nYou asked: **{user[:60]}**\n\n- Point one\n- Point two\n\n<script>alert('xss')</script>"
        async def gen():
            for i in range(0, len(reply), 12):
                yield "data: " + json.dumps({"choices":[{"delta":{"content": reply[i:i+12]}}]}) + "\n\n"
                await asyncio.sleep(0.02)
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    out = {"summary":"AI: strong data-engineering profile; main gap is container orchestration.",
           "strengths":["AI strength: solid Python/SQL/AWS match"],"improvements":["AI: quantify pipeline impact"],
           "skills_to_learn":[{"skill":"Kubernetes","why":"Asked in most postings.","how":"Deploy a small app on kind."}]}
    return {"choices":[{"message":{"content": json.dumps(out)}}]}

rs = main.app.router.routes
fake_routes = [r for r in rs if getattr(r, "path", "").startswith("/fake-openai")]
for r in fake_routes: rs.remove(r)
rs[:0] = fake_routes
import uvicorn
print(f"Demo server (fake LinkedIn + fake OpenAI) at http://localhost:{PORT}", flush=True)
uvicorn.run(main.app, host="127.0.0.1", port=PORT, log_level="warning")
