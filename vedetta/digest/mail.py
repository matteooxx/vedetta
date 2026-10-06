"""Sending the digest over SMTP.

Credentials come from the environment only, never from configuration or the
repository. A send failure is raised, not swallowed: an unsent digest is the one
failure the operator cannot discover by reading the digest.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class MailNotConfigured(RuntimeError):
    pass


def send(subject: str, body: str, settings: dict) -> str:
    host = os.environ.get("VEDETTA_SMTP_HOST") or settings.get("host")
    port = int(os.environ.get("VEDETTA_SMTP_PORT") or settings.get("port") or 587)
    user = os.environ.get("VEDETTA_SMTP_USER") or settings.get("user")
    password = os.environ.get("VEDETTA_SMTP_PASSWORD")
    sender = os.environ.get("VEDETTA_MAIL_FROM") or settings.get("sender") or user
    recipients = settings.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    env_to = os.environ.get("VEDETTA_MAIL_TO")
    if env_to:
        recipients = [r.strip() for r in env_to.split(",") if r.strip()]

    missing = [n for n, v in (("host", host), ("sender", sender), ("recipients", recipients)) if not v]
    if missing:
        raise MailNotConfigured("missing: " + ", ".join(missing))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if settings.get("starttls", True):
            smtp.starttls()
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)
    return f"sent to {len(recipients)} recipient(s) via {host}:{port}"
