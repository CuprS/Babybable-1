"""Spots contact details and outside-payment requests in chat messages.

Before a family and a tutor have a paid booking together, sharing a phone number, email, home
address, outside app or payment handle moves the conversation somewhere Babybabel can't protect
it — a common first step in scams and in grooming. We don't block it (people share details for
good reasons too); the sender is asked to confirm, the message is labelled for the recipient, and
it goes into the admin review queue.

This is a best-effort net, not a guarantee: it errs towards warning on borderline text.
"""
import re

LABELS = {
    "phone": "a phone number",
    "email": "an email address",
    "address": "a street address",
    "payment": "an outside payment method",
    "app": "another messaging app",
    "link": "a link to another website",
}

_PHONE_CANDIDATE = re.compile(r"(?<![\w$])\+?\(?\d[\d\s().\-]{5,22}\d(?!\w)")
_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$|^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")
_TIME_RANGE = re.compile(r"^\d{1,2}[.:]\d{2}\s*-\s*\d{1,2}[.:]\d{2}$")
_SHORT_PHONE = re.compile(r"(?<!\d)\d{3}[\s.\-]\d{4}(?!\d)")
_PHONE_WORDS = re.compile(r"\b(?:call|text|ring|phone|cell|mobile|number|reach)\b[^.\n]{0,25}?\d{7,}", re.I)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
_EMAIL_SPELLED = re.compile(
    r"[\w.+-]+\s*(?:\(at\)|\[at\]|\{at\}|\sat\s)\s*[\w-]+\s*(?:\(dot\)|\[dot\]|\{dot\}|\sdot\s|\.)\s*"
    r"(?:com|net|org|edu|co|uk|ca|io|me|us|de|fr|es)\b", re.I)
_EMAIL_DOMAINS = re.compile(r"\b(?:gmail|yahoo|hotmail|outlook|icloud|aol|protonmail|proton)\s*(?:\.|dot)\s*com\b", re.I)

_STREET_TYPES = (r"street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|way|place|pl|terrace|"
                 r"circle|cir|parkway|pkwy|highway|hwy|square|sq|crescent|close|calle|rue|strasse|straße")
_ADDRESS = re.compile(rf"\b\d{{1,6}}[a-z]?\s+(?:[A-Za-z0-9.'\-]+\s+){{0,4}}(?:{_STREET_TYPES})\b\.?", re.I)
_UNIT = re.compile(r"\b(?:apt|apartment|suite|unit)\.?\s*#?\s*\d+[a-z]?\b", re.I)
_ZIP_WITH_STATE = re.compile(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")

_PAYMENT = re.compile(
    r"\b(?:venmo|cash\s?app|paypal|zelle|wise\.com|revolut|western\s+union|moneygram|wire\s+transfer|bank\s+transfer|"
    r"gift\s?cards?|itunes\s+cards?|bitcoin|btc|ethereum|crypto|usdt|tether|apple\s+pay\s+me|"
    r"routing\s+number|account\s+number|sort\s+code|iban)\b"
    r"|(?<![\w$])\$[A-Za-z][A-Za-z0-9_\-]{2,}"  # Cash App $cashtag (not "$40")
    r"|\bpay\s+(?:me|you|us)\s+(?:directly|outside|off\s+the\s+(?:app|site)|in\s+cash|cash|privately)\b"
    r"|\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?(?:app|site|babybabel)\b",
    re.I)
_APPS = re.compile(r"\b(?:whats\s?app|telegram|signal\s+app|on\s+signal|wechat|snapchat|snap\s+me|kik|viber|"
                   r"instagram|insta|facebook\s+messenger|messenger|discord|skype)\b", re.I)
_LINK = re.compile(r"\bhttps?://\S+|\bwww\.\S+|\b[\w-]+\.(?:com|net|org|me|io|app|ly|link|co)(?:/\S*)?\b", re.I)
_OUR_SITE = re.compile(r"(?:^|\.)babybabel\.(?:com|co)\b", re.I)


def _digits(s: str) -> int:
    return sum(c.isdigit() for c in s)


def _has_phone(text: str) -> bool:
    for m in _PHONE_CANDIDATE.finditer(text):
        s = m.group(0).strip()
        if _DATE.match(s) or _TIME_RANGE.match(s):
            continue
        if 9 <= _digits(s) <= 15:
            return True
    if _SHORT_PHONE.search(text) or _PHONE_WORDS.search(text):
        return True
    # Digits spelled out or spaced to dodge filters, e.g. "five five five one two three four".
    words = re.findall(r"\b(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)\b", text, re.I)
    return len(words) >= 7


def _has_link(text: str) -> bool:
    for m in _LINK.finditer(text):
        url = m.group(0)
        if _EMAIL.search(url) or _OUR_SITE.search(url):
            continue
        return True
    return False


def detect_contact_info(text: str) -> list[str]:
    """The kinds of off-platform detail in `text`, in LABELS order (empty if none)."""
    if not text:
        return []
    found = set()
    if _EMAIL.search(text) or _EMAIL_SPELLED.search(text) or _EMAIL_DOMAINS.search(text):
        found.add("email")
    without_emails = _EMAIL.sub(" ", text)
    if _has_phone(without_emails):
        found.add("phone")
    if _ADDRESS.search(text) or _UNIT.search(text) or _ZIP_WITH_STATE.search(text):
        found.add("address")
    if _PAYMENT.search(text):
        found.add("payment")
    if _APPS.search(text):
        found.add("app")
    if _has_link(without_emails):
        found.add("link")
    return [k for k in LABELS if k in found]


def describe(kinds: list[str]) -> str:
    """'a phone number and an email address'."""
    names = [LABELS[k] for k in kinds if k in LABELS]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
