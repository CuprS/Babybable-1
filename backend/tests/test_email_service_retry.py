# Session 12 retest: email_service.send_email retries on HTTP 429 with backoff (max 4 attempts), unit-level with mocked transport
import asyncio
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import email_service  # noqa: E402


def _run(responses, monkeypatch):
    calls, sleeps = [], []

    def handler(req):
        calls.append(req)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    real = httpx.AsyncClient
    monkeypatch.setattr(email_service.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(email_service.asyncio, "sleep", fake_sleep)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "Babybabel <alerts@example.com>")
    res = asyncio.run(email_service.send_email(to="delivered@resend.dev", subject="TEST_ s", html="<p>x</p>"))
    return res, calls, sleeps


R429 = httpx.Response(429, json={"code": "rate_limited"})
R429_RA = httpx.Response(429, headers={"Retry-After": "3"}, json={"code": "rate_limited"})
OK = httpx.Response(202, json={"id": "em_1"})


def test_retry_then_success(monkeypatch):
    res, calls, sleeps = _run([R429, R429, OK], monkeypatch)
    assert res == "em_1" and len(calls) == 3 and sleeps == [1.0, 2.0]


def test_gives_up_after_4_attempts(monkeypatch):
    res, calls, sleeps = _run([R429], monkeypatch)
    assert res is None and len(calls) == 4 and sleeps == [1.0, 2.0, 4.0]


def test_honours_retry_after(monkeypatch):
    res, calls, sleeps = _run([R429_RA, OK], monkeypatch)
    assert res == "em_1" and sleeps == [3.0]


def test_no_retry_on_500(monkeypatch):
    res, calls, _ = _run([httpx.Response(500, json={})], monkeypatch)
    assert res is None and len(calls) == 1


def test_sends_to_resend_with_bearer_key(monkeypatch):
    res, calls, _ = _run([OK], monkeypatch)
    req = calls[0]
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["Authorization"] == "Bearer re_test_key"
    body = req.read().decode()
    assert '"from":"Babybabel <alerts@example.com>"' in body.replace(": ", ":") and '"text"' in body


def test_nothing_sent_without_provider(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert asyncio.run(email_service.send_email(to="a@example.com", subject="s", html="<p>x</p>")) is None


def test_smtp_provider(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["addr"] = (host, port)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self, context=None):
            sent["tls"] = True
        def login(self, u, p):
            sent["login"] = u
        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    for k, v in {"EMAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.example.com", "SMTP_USERNAME": "u",
                 "SMTP_PASSWORD": "p", "EMAIL_FROM": "Babybabel <hello@example.com>"}.items():
        monkeypatch.setenv(k, v)
    res = asyncio.run(email_service.send_email(to="a@example.com", subject="Hi", html="<p>Hello</p>"))
    assert res and sent["addr"] == ("smtp.example.com", 587) and sent["tls"] and sent["login"] == "u"
    assert sent["msg"]["To"] == "a@example.com" and sent["msg"].get_body(("plain",)).get_content().strip() == "Hello"
