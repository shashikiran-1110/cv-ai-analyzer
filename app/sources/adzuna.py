"""Adzuna: official aggregator API (free key from developer.adzuna.com); covers many countries and boards."""
from __future__ import annotations

import math

import httpx

from ..jobmodel import Job
from ..textutil import html_to_text, parse_date
from .base import JobQuery, Source, SourceError, get

COUNTRIES = {"gb", "us", "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "in", "it", "mx", "nl", "nz", "pl", "sg", "za"}


async def adzuna(q: JobQuery, client: httpx.AsyncClient) -> list[Job]:
    cfg = q.adzuna or {}
    app_id, app_key = str(cfg.get("app_id", "")).strip(), str(cfg.get("app_key", "")).strip()
    country = str(cfg.get("country", "gb")).lower().strip()
    if not app_id or not app_key:
        raise SourceError("Adzuna needs an App ID and App Key (free at developer.adzuna.com).", "config")
    if country not in COUNTRIES:
        raise SourceError(f"Adzuna doesn't support country “{country}”.", "config")
    params = {"app_id": app_id, "app_key": app_key, "what": q.title, "results_per_page": 50,
              "sort_by": "date" if q.sort == "recent" else "relevance", "content-type": "application/json"}
    if q.location and q.location.lower() not in ("remote", "anywhere", "worldwide"):
        params["where"] = q.location
    if q.hours:
        params["max_days_old"] = max(1, math.ceil(q.hours / 24))
    out: list[Job] = []
    for page in range(1, min(4, math.ceil(q.count / 50) + 1) + 1):
        try:
            data = await get(client, f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params, name="Adzuna")
        except SourceError as e:
            if out:
                break
            msg = str(e)
            for secret in (app_key, app_id):
                if len(secret) >= 6:  # never blank out ordinary words when the "secret" is tiny
                    msg = msg.replace(secret, "***")
            raise SourceError(msg, e.kind)
        rows = data.get("results", []) or []
        for j in rows:
            sal = ""
            if j.get("salary_min"):
                sal = f"{int(j['salary_min'])}" + (f"–{int(j['salary_max'])}" if j.get("salary_max") else "")
            out.append(Job(
                id=f"adzuna-{j.get('id')}", title=html_to_text(j.get("title")), company=(j.get("company") or {}).get("display_name", ""),
                location=(j.get("location") or {}).get("display_name", ""), url=j.get("redirect_url", ""),
                posted=parse_date(j.get("created")), description=html_to_text(j.get("description")),
                employment_type=(j.get("contract_time") or "").replace("_", " "), salary=sal,
                extra={"truncated": True}, source="adzuna"))
        if len(rows) < 50:
            break
    return out


SOURCES = [Source("adzuna", "Adzuna", "search", "api.adzuna.com", adzuna, needs="adzuna_key",
                  note="Aggregates thousands of boards in 19 countries; descriptions are shortened")]
