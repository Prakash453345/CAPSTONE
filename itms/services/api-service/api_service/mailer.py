"""Outgoing mail for password-reset codes.

Configure with environment variables (api-service):

    SMTP_HOST       mail server; unset = dev mode (the message is logged instead)
    SMTP_PORT       default 587
    SMTP_USER / SMTP_PASSWORD   optional login
    SMTP_FROM       sender address, default "ITMS <no-reply@localhost>"
    SMTP_STARTTLS   default true; set false for a server that speaks TLS from the
                    first byte (port 465 uses implicit TLS automatically)

Sending never raises: a mail failure is logged and the caller carries on, so
the forgot-password endpoint answers the same whether or not mail went out.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("api-service.mailer")


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
        # Dev mode only: with no mail server configured the code has to go
        # somewhere a developer can read it.
        log.warning("SMTP_HOST not set -- reset code for %s is %s (dev mode)", to, code)
        return
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
