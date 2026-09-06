"""Invite emails over SMTP. When SMTP is not configured, nothing is sent and the
doctor's dashboard shows the activation link to share by hand instead."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from ..config import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    sent: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return {"sent": self.sent, "error": self.error}


def invite_message(first_name: str, doctor_name: str, link: str, days_valid: int) -> tuple[str, str, str]:
    """(subject, plain text, html) for an account-creation email."""
    subject = "Your Tamil Tutor account is ready to set up"
    text = (
        f"Hello {first_name},\n\n"
        f"{doctor_name} has added you to Tamil Tutor. Open this link to choose a\n"
        f"username and password and start practising:\n\n{link}\n\n"
        f"The link works for {days_valid} days. If you did not expect this email, you can ignore it.\n"
    )
    html = f"""
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:540px;margin:auto;padding:24px;color:#1b1f3a">
  <div style="font-size:26px;font-weight:800;margin-bottom:4px">Tamil Tutor</div>
  <div style="color:#6a7195;font-weight:600;margin-bottom:22px">learn · speak · shine</div>
  <p style="font-size:16px">Hello <b>{first_name}</b>,</p>
  <p style="font-size:16px"><b>{doctor_name}</b> has added you to Tamil Tutor. Set up your account to start practising:</p>
  <p style="margin:26px 0">
    <a href="{link}" style="background:#7c6cff;color:#fff;text-decoration:none;font-weight:800;padding:14px 26px;border-radius:999px;display:inline-block">Create my account</a>
  </p>
  <p style="color:#6a7195;font-size:13px">Or paste this link into your browser:<br><a href="{link}">{link}</a></p>
  <p style="color:#6a7195;font-size:13px">The link works for {days_valid} days.</p>
</div>"""
    return subject, text, html


def _send_sync(to: str, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if settings.smtp_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    with server:
        server.ehlo()
        if settings.smtp_tls and not settings.smtp_ssl:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def send_invite(to: str, first_name: str, doctor_name: str, link: str) -> SendResult:
    if not settings.email_configured:
        log.info("SMTP not configured; invite for %s must be shared by hand: %s", to, link)
        return SendResult(False, "Email is not configured (set SMTP_HOST and SMTP_FROM).")
    subject, text, html = invite_message(first_name, doctor_name, link, settings.invite_days)
    try:
        await asyncio.to_thread(_send_sync, to, subject, text, html)
    except Exception as exc:  # noqa: BLE001 - report, never crash the request
        log.exception("invite email to %s failed", to)
        return SendResult(False, f"Email could not be sent: {exc}")
    log.info("invite email sent to %s", to)
    return SendResult(True)
