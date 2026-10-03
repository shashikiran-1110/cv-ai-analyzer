"""Accounts (ROADMAP §10.2): optional email magic-link sign-in. Anonymous use keeps working; signing in moves the
browser's anonymous work to the account, unlocks email digests, and keeps data for USER_RETENTION_DAYS."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from ..runtime import mailer, ratelimit
from ..storage import db
from .deps import owner, user

router = APIRouter()
SESSION_COOKIE = "cvm_session"
SESSION_DAYS = 30
TOKEN_MINUTES = 15
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-zA-Z]{2,24}$")
_cache: dict[str, tuple[float, Optional[dict]]] = {}


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(token: str) -> Optional[dict]:
    """User for a session cookie (cached for 60 s)."""
    if not token or len(token) > 100:
        return None
    hit = _cache.get(token)
    if hit and hit[0] > time.time():
        return hit[1]
    with db.engine().connect() as c:
        row = c.execute(select(db.users.c.id, db.users.c.email, db.sessions.c.expires_at)
                        .select_from(db.sessions.join(db.users, db.sessions.c.user_id == db.users.c.id))
                        .where(db.sessions.c.token_hash == _h(token))).first()
    u = {"id": row.id, "email": row.email} if row and row.expires_at > time.time() else None
    _cache[token] = (time.time() + 60, u)
    if len(_cache) > 5000:
        _cache.clear()
    return u


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)


def _base_url(request: Request) -> str:
    return (os.getenv("PUBLIC_URL") or str(request.base_url)).rstrip("/")


@router.post("/api/auth/request")
async def request_link(body: LoginRequest, request: Request):
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    ratelimit.check(request, "auth")
    token = secrets.token_urlsafe(32)

    def store():
        with db.engine().begin() as c:
            c.execute(delete(db.login_tokens).where(db.login_tokens.c.expires_at < time.time()))
            c.execute(insert(db.login_tokens).values(token_hash=_h(token), email=email, anon_owner=owner(request),
                                                     expires_at=time.time() + TOKEN_MINUTES * 60, used=0))
    await run_in_threadpool(store)
    link = f"{_base_url(request)}/api/auth/verify?token={token}"
    await run_in_threadpool(mailer.send, email, "Your CV Match Analyzer sign-in link",
                            f"Sign in to CV Match Analyzer:\n\n{link}\n\nThe link works once and expires in {TOKEN_MINUTES} minutes. "
                            "If you didn't ask for it, ignore this email.")
    out = {"sent": True, "delivery": "email" if mailer.configured() else "console"}
    if os.getenv("DEV_LOGIN_LINKS", "false").lower() == "true":
        out["dev_link"] = link          # local/demo only: no mail server, show the link in the UI
    return out


@router.get("/api/auth/verify")
async def verify_link(token: str, request: Request):
    def go() -> Optional[str]:
        now = time.time()
        with db.engine().begin() as c:
            row = c.execute(select(db.login_tokens).where(db.login_tokens.c.token_hash == _h(token))).mappings().first()
            if not row or row["used"] or row["expires_at"] < now:
                return None
            c.execute(update(db.login_tokens).where(db.login_tokens.c.token_hash == _h(token)).values(used=1))
            u = c.execute(select(db.users).where(db.users.c.email == row["email"])).mappings().first()
            uid = u["id"] if u else uuid.uuid4().hex
            if u:
                c.execute(update(db.users).where(db.users.c.id == uid).values(last_login=now))
            else:
                c.execute(insert(db.users).values(id=uid, email=row["email"], created_at=now, last_login=now))
            sess = secrets.token_urlsafe(32)
            c.execute(insert(db.sessions).values(token_hash=_h(sess), user_id=uid, created_at=now,
                                                 expires_at=now + SESSION_DAYS * 86400))
        for anon in {row["anon_owner"], owner(request)}:
            if anon and not anon.startswith("u:"):
                db.reassign_owner(anon, f"u:{uid}")
        return sess
    sess = await run_in_threadpool(go)
    if not sess:
        return RedirectResponse("/settings?signin=expired", status_code=303)
    resp = RedirectResponse("/settings?signin=ok", status_code=303)
    resp.set_cookie(SESSION_COOKIE, sess, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=os.getenv("COOKIE_SECURE", "false").lower() == "true")
    return resp


@router.get("/api/me")
async def me(request: Request):
    u = user(request)
    return {"user": u, "kind": "user" if u else "anonymous", "email_delivery": "email" if mailer.configured() else "console",
            "retention_days": float(os.getenv("USER_RETENTION_DAYS", "365")) if u else float(os.getenv("ANON_RETENTION_DAYS", "7"))}


@router.post("/api/auth/logout")
async def logout(request: Request):
    tok = request.cookies.get(SESSION_COOKIE, "")
    if tok:
        def go():
            with db.engine().begin() as c:
                c.execute(delete(db.sessions).where(db.sessions.c.token_hash == _h(tok)))
        await run_in_threadpool(go)
        _cache.pop(tok, None)
    resp = RedirectResponse("/settings", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
