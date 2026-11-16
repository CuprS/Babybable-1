# Session 12 retest: email_service.send_email retries on HTTP 429 with backoff (max 4 attempts), unit-level with mocked transport
import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, "/app/backend")
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
    monkeypatch.setenv("EMERGENT_EMAIL_KEY", "k")
    monkeypatch.setenv("EMAIL_FROM_NAME", "Babybabel")
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
