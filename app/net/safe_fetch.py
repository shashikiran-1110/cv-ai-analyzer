"""Fetch user-supplied URLs without letting them reach the server's own network (SSRF guard, ROADMAP D1).

Rules, checked on the first request and again on every redirect hop:
- only http/https, only ports 80/443 (or none);
- the hostname must resolve, and *every* resolved address must be public (no loopback, private, link-local
  incl. 169.254.169.254 cloud metadata, multicast, reserved, unspecified, CGNAT, or IPv4-mapped IPv6 of those);
- at most MAX_REDIRECTS hops and MAX_BYTES of body.

Residual risk: DNS rebinding between this check and the connection. Hosted deployments should also route
fetches through an egress proxy that denies private ranges (ROADMAP §12).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

ALLOWED_PORTS = {80, 443, None}
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5


class UnsafeURL(Exception):
    """The URL points somewhere the server must not fetch (user-presentable)."""


@dataclass
class Fetched:
    status: int
    url: str
    headers: httpx.Headers
    text: str


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def ip_is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if a.version == 6:
        embedded = a.ipv4_mapped or a.sixtofour      # IPv4 hidden inside IPv6 must pass the IPv4 rules
        if embedded is not None:
            return ip_is_public(str(embedded))
    if a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified:
        return False
    if a.version == 4 and a in _CGNAT:
        return False
    if a.version == 6 and a.is_site_local:
        return False
    return True


async def _system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


# Indirection so tests (and the offline demo) can supply DNS answers.
resolve: Callable[[str, int], Awaitable[list[str]]] = _system_resolve


async def check_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UnsafeURL("Only http(s) links to public websites are allowed.")
    try:
        port = u.port
    except ValueError:
        raise UnsafeURL("That link has an invalid port.")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Only standard web ports (80/443) are allowed.")
    host = u.hostname.rstrip(".").lower()          # canonical form: "LOCALHOST." == "localhost"
    if not host:
        raise UnsafeURL("Only http(s) links to public websites are allowed.")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        addrs = [host]                                   # literal IP: check it directly
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise UnsafeURL("That address isn't a public website.")
        try:
            addrs = await resolve(host, port or (443 if u.scheme == "https" else 80))
        except (OSError, UnicodeError):
            raise UnsafeURL(f"Couldn't resolve {host}.")
    if not addrs or not all(ip_is_public(a) for a in addrs):
        raise UnsafeURL("That address isn't a public website.")


async def safe_get(client: httpx.AsyncClient, url: str, headers: dict | None = None) -> Fetched:
    for _ in range(MAX_REDIRECTS + 1):
        await check_url(url)                               # re-check every hop
        async with client.stream("GET", url, headers=headers, follow_redirects=False) as r:
            if r.is_redirect and "location" in r.headers:
                url = str(r.url.join(r.headers["location"]))
                continue
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise UnsafeURL("That page is too large to import.")
            enc = r.encoding or "utf-8"
            return Fetched(r.status_code, str(r.url), r.headers, bytes(body).decode(enc, errors="replace"))
    raise UnsafeURL("Too many redirects.")
