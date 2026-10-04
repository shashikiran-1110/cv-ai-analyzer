"""Saved job links: a persistent list (per browser or account) of posting URLs to fetch on every search.

Links stay until the user discards them. Pasted text of any kind is accepted: every http(s) URL in it is extracted.
Fetching still goes through the SSRF guard (app/net/safe_fetch); here we only reject obviously non-public links early.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..storage import db
from .deps import owner

router = APIRouter()
URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)
MAX_LINKS = 200


def extract_urls(text: str) -> list[str]:
    out = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?)]}>»”’")
        if len(u) <= 2000:
            out.append(u)
    return list(dict.fromkeys(out))


def _plausible(url: str) -> Optional[str]:
    """Reason to reject, or None. (Full DNS + private-address checks happen when the link is fetched.)"""
    u = urlparse(url)
    host = (u.hostname or "").lower().rstrip(".")
    if u.scheme not in ("http", "https") or not host or "." not in host:
        return "not a public web link"
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return "not a public website"
    try:
        if not ipaddress.ip_address(host).is_global:
            return "not a public website"
    except ValueError:
        pass
    return None


class LinksIn(BaseModel):
    urls: list[str] = Field(default=[], max_length=MAX_LINKS)
    text: str = Field(default="", max_length=200_000)


@router.get("/api/links")
async def get_links(request: Request):
    return await run_in_threadpool(db.list_links, owner(request))


@router.post("/api/links")
async def add_links(body: LinksIn, request: Request):
    found = extract_urls(body.text) + [u.strip() for u in body.urls if u.strip()]
    if not found:
        raise HTTPException(422, "No http(s) links found in what you pasted.")
    ok, rejected = [], []
    for u in dict.fromkeys(found):
        why = _plausible(u)
        (rejected.append({"url": u, "reason": why}) if why else ok.append(u))
    before = {x["url"] for x in await run_in_threadpool(db.list_links, owner(request))}
    links = await run_in_threadpool(db.add_links, owner(request), ok, MAX_LINKS)
    after = {x["url"] for x in links}
    added = [u for u in ok if u in after and u not in before]
    return {"links": links, "added": len(added), "duplicates": sum(1 for u in ok if u in before),
            "rejected": rejected, "full": len(after) >= MAX_LINKS and len(added) < len([u for u in ok if u not in before])}


@router.delete("/api/links/{link_id}")
async def delete_link(link_id: int, request: Request):
    n = await run_in_threadpool(db.delete_links, owner(request), link_id)
    if not n:
        raise HTTPException(404, "Link not found.")
    return {"deleted": n}


@router.delete("/api/links")
async def clear_links(request: Request, only: Optional[Literal["ok", "failed", "new"]] = None):
    return {"deleted": await run_in_threadpool(lambda: db.delete_links(owner(request), None, only or ""))}
