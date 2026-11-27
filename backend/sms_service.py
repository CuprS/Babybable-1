"""Text messages (session reminders and phone-number codes).

SMS_PROVIDER=twilio   Twilio's HTTP API — TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM
                      (your Twilio number in +15551234567 form, or a Messaging Service SID "MG…").
(unset)               Text messages are switched off: the app hides the option and nothing is sent.

Twilio handles STOP / HELP replies for you, as US carriers require. Only numbers the person has
confirmed with a code are ever texted, and only with their consent.
"""
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def sms_available() -> bool:
    if os.environ.get("SMS_PROVIDER", "").strip().lower() != "twilio":
        return False
    return all(os.environ.get(k, "").strip() for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))


def normalize_phone(raw: str) -> Optional[str]:
    """'(512) 555-0199' -> '+15125550199'. US/Canada numbers may skip the +1; others need +country.
    Returns None for anything that isn't a plausible phone number."""
    s = (raw or "").strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not plus:
        if len(digits) == 10:
            digits = "1" + digits
        elif not (len(digits) == 11 and digits.startswith("1")):
            return None
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        return None
    return "+" + digits


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """'+15125550199' -> '•••• 0199', for showing back to its owner."""
    return f"•••• {phone[-4:]}" if phone else None


async def send_sms(to: str, body: str) -> bool:
    """Send one text. Never raises; returns True if the provider accepted it."""
    if not sms_available():
        logger.warning("Text not sent: SMS_PROVIDER isn't set up")
        return False
    sid = os.environ["TWILIO_ACCOUNT_SID"].strip()
    token = os.environ["TWILIO_AUTH_TOKEN"].strip()
    sender = os.environ["TWILIO_FROM"].strip()
    data = {"To": to, "Body": body[:600]}
    data["MessagingServiceSid" if sender.startswith("MG") else "From"] = sender
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(TWILIO_URL.format(sid=sid), data=data, auth=(sid, token))
        if resp.status_code >= 400:
            logger.error(f"Text send failed: {resp.status_code} {resp.text[:300]}")
            return False
        return True
    except Exception as e:  # network etc.
        logger.error(f"Text send error: {e}")
        return False
