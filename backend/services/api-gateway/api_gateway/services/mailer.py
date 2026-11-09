"""Outgoing mail for password-reset codes.

Configure with environment variables (api-service):

    SMTP_HOST       mail server. If unset, sending fails -- unless AUTH_DEV_LOG_CODES
                    is on, which logs the code instead (local development only)
    SMTP_PORT       default 587
    SMTP_USER / SMTP_PASSWORD   optional login
    SMTP_FROM       sender address, default "ITMS <no-reply@localhost>"
    SMTP_STARTTLS   default true; set false for a server that speaks TLS from the
                    first byte (port 465 uses implicit TLS automatically)

Sending raises MailError when mail can't go out (not configured, or the server
refused), so the caller can tell the person instead of claiming a code was sent.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("api-service.mailer")


class MailError(Exception):
    """The message could not be sent."""


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", "off"}


def send_reset_code(to: str, code: str, minutes: int) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", "ITMS <no-reply@localhost>")
    msg = EmailMessage()
    msg["Subject"] = "Your ITMS password reset code"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(
        f"Your ITMS password reset code is {code}.\n\n"
        f"It expires in {minutes} minutes and works once. "
        "If you didn't ask to reset your password, ignore this message; "
        "your password has not changed.\n"
    )
    if not host:
        if _flag("AUTH_DEV_LOG_CODES", False):
            # Local development only: no mail server, so the code goes where a
            # developer can read it. Never enable this in production.
            log.warning("AUTH_DEV_LOG_CODES: reset code for %s is %s", to, code)
            return
        log.error("cannot send reset code: SMTP_HOST is not set")
        raise MailError("email is not configured")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD", "")
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=15, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        with server:
            if port != 465 and _flag("SMTP_STARTTLS", True):
                server.starttls(context=ctx)
            if user:
                server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("could not send reset code to %s: %s", to, exc)
        raise MailError(str(exc)) from exc
