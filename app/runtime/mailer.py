"""Outgoing email (magic links, watch digests). SMTP when SMTP_HOST is set; otherwise a console mailer that logs
the message and keeps it in OUTBOX (local use, demo and tests). Nothing is ever sent to anyone without SMTP config.

    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_STARTTLS (true)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

log = logging.getLogger("cvmatch.mail")
OUTBOX: list[dict] = []


def configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def send(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    if not configured():
        OUTBOX.append({"to": to, "subject": subject, "text": text})
        del OUTBOX[:-50]
        log.info("console mailer → %s: %s\n%s", to, subject, text)
        return
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "CV Match Analyzer <no-reply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=20) as s:
        if os.getenv("SMTP_STARTTLS", "true").lower() == "true":
            s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        s.send_message(msg)
