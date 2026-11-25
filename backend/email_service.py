"""Transactional email (safety alerts, verification and reset codes) with a content guardrail.

EMAIL_PROVIDER=resend  Resend's HTTP API — RESEND_API_KEY, and a verified sender in EMAIL_FROM.
EMAIL_PROVIDER=smtp    Any SMTP server (SES, Postmark, Mailgun, Gmail Workspace…) — SMTP_HOST,
                       SMTP_PORT (587), SMTP_USERNAME, SMTP_PASSWORD, SMTP_SECURITY=starttls|ssl|none.
(unset)                Nothing is sent; a warning is logged instead.

EMAIL_FROM is the sender, e.g. "Babybabel <hello@babybabel.com>". EMAIL_REPLY_TO is optional.
"""
import asyncio
import ipaddress
import logging
import os
import re
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")


def _html_to_text(html: str) -> str:
    """Plain-text alternative for mail clients that don't show HTML."""
    text = re.sub(r"<(br|/p|/tr|/h[1-6])\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def _send_resend(to: str, subject: str, html: str, sender: str, reply_to: str) -> str | None:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        logger.warning("Email not sent: EMAIL_PROVIDER=resend but RESEND_API_KEY is missing")
        return None
    payload = {"from": sender, "to": [to], "subject": subject, "html": html, "text": _html_to_text(html)}
    if reply_to:
        payload["reply_to"] = reply_to
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": str(uuid.uuid4())}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(4):  # back off on provider rate limits so alerts aren't lost
                resp = await client.post(RESEND_API_URL, headers=headers, json=payload)
                if resp.status_code != 429 or attempt == 3:
                    break
                await asyncio.sleep(float(resp.headers.get("Retry-After") or 2 ** attempt))
        resp.raise_for_status()
        return resp.json().get("id")
    except httpx.HTTPStatusError as e:
        try:
            body = e.response.json()
        except ValueError:
            body = {}
        name = body.get("name") or body.get("code") or ""
        if name in ("daily_quota_exceeded", "monthly_quota_exceeded", "rate_limit_exceeded"):
            logger.warning(f"Email paused: {name} ({e.response.status_code}): {body.get('message', '')}")
        else:
            logger.error(f"Email send failed: {e.response.status_code} {e.response.text[:300]}")
    except Exception as e:  # network etc.
        logger.error(f"Email send error: {e}")
    return None


def _send_smtp_sync(to: str, subject: str, html: str, sender: str, reply_to: str) -> str | None:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        logger.warning("Email not sent: EMAIL_PROVIDER=smtp but SMTP_HOST is missing")
        return None
    security = os.environ.get("SMTP_SECURITY", "starttls").strip().lower()
    port = int(os.environ.get("SMTP_PORT") or (465 if security == "ssl" else 587))
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].strip("> ") or None)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(_html_to_text(html))
    msg.add_alternative(html, subtype="html")
    try:
        context = ssl.create_default_context()
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            user = os.environ.get("SMTP_USERNAME", "")
            if user:
                server.login(user, os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
        return msg["Message-ID"]
    except Exception as e:
        logger.error(f"Email send error (SMTP {host}:{port}): {e}")
        return None


async def send_email(*, to: str, subject: str, html: str) -> str | None:
    """Fire-and-forget internal send. Recipients/templates are server-side only (G4).
    Returns the provider's message id, or None if nothing was sent (never raises for
    network/provider errors). Raises ValueError only when the content fails the safety
    guardrail, so callers can fall back to a safer template."""
    _assert_safe_email(subject, html)
    provider = os.environ.get("EMAIL_PROVIDER", "").strip().lower()
    sender = os.environ.get("EMAIL_FROM", "").strip()
    reply_to = os.environ.get("EMAIL_REPLY_TO", "").strip()
    if not provider:
        logger.warning(f"Email not sent (EMAIL_PROVIDER not set): {subject!r} to {to.split('@')[-1]}")
        return None
    if not sender:
        logger.warning("Email not sent: EMAIL_FROM is missing (e.g. \"Babybabel <hello@yourdomain.com>\")")
        return None
    if provider == "resend":
        return await _send_resend(to, subject, html, sender, reply_to)
    if provider == "smtp":
        return await asyncio.to_thread(_send_smtp_sync, to, subject, html, sender, reply_to)
    logger.error(f"Unknown EMAIL_PROVIDER={provider!r} (use 'resend' or 'smtp')")
    return None
