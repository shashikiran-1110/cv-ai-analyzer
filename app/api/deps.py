"""Shared request helpers for routers."""
from __future__ import annotations

from fastapi import HTTPException, Request


def owner(request: Request) -> str:
    return getattr(request.state, "owner", "")


def user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def require_user(request: Request) -> dict:
    u = user(request)
    if not u:
        raise HTTPException(401, "Sign in to use this (it needs an email address).")
    return u
