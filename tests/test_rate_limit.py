"""Tests for the rate-limit wait-and-retry engine wrapper (devsecbuddy/engines/retry.py).

A scorer that hits a rate-limit error (429 / RESOURCE_EXHAUSTED) pauses and retries with
an escalating wait — 30 s, then 60 s, then 90 s, … within the same run — instead of
failing. Tests inject a fake sleep so they run instantly.
"""
from __future__ import annotations

import pytest

from devsecbuddy import RunCancelled
from devsecbuddy.engines import RateLimitRetryEngine, is_rate_limit_error
from devsecbuddy.models import EngineResponse


class _FlakyEngine:
    """Raises a rate-limit error on the first ``fail_times`` complete() calls, then succeeds."""

    name = "fake"
    model = "fake-1"

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self._fail = fail_times
        self._calls = 0
        self._exc = exc or RuntimeError(
            "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED'}}"
        )

    def info(self) -> dict:
        return {"name": "fake", "model": "fake-1"}

    def complete(self, system, prompt, params=None):
        self._calls += 1
        if self._calls <= self._fail:
            raise self._exc
        return EngineResponse(text="SCORE: 70/100", model="fake-1")


def _wrap(inner, **kw):
    # huge poll so each pause is a single sleep we can read off; record the durations
    kw.setdefault("poll_s", 10_000.0)
    waited: list[float] = []
    kw.setdefault("sleep", waited.append)
    return RateLimitRetryEngine(inner, **kw), waited


def test_escalating_wait_30s_per_pause_then_succeeds():
    eng, waited = _wrap(_FlakyEngine(fail_times=3))
    resp = eng.complete("sys", "prompt")
    assert "SCORE" in resp.text                 # eventually succeeded
    assert waited == [30.0, 60.0, 90.0]         # Nth pause waits 30*N (per scorer)


def test_counter_is_per_scorer():
    # a fresh wrapper (the backend builds one per run) starts the escalation over at 30 s
    for _ in range(2):
        eng, waited = _wrap(_FlakyEngine(fail_times=1))
        eng.complete("s", "p")
        assert waited == [30.0]


def test_gives_up_after_max_retries():
    eng, waited = _wrap(_FlakyEngine(fail_times=99), max_retries=3)
    with pytest.raises(Exception) as ei:
        eng.complete("s", "p")
    assert "429" in str(ei.value) or "RESOURCE_EXHAUSTED" in str(ei.value)
    assert waited == [30.0, 60.0, 90.0]         # exactly max_retries pauses, then propagate


def test_non_rate_limit_error_is_not_retried():
    eng, waited = _wrap(_FlakyEngine(fail_times=1, exc=ValueError("bad prompt")))
    with pytest.raises(ValueError):
        eng.complete("s", "p")
    assert waited == []                          # no pause for a non-429 error


def test_detector_covers_provider_shapes():
    class HttpErr(Exception):
        status_code = 429

    assert is_rate_limit_error(HttpErr())
    assert is_rate_limit_error(RuntimeError("429 RESOURCE_EXHAUSTED. Please try again later."))
    assert is_rate_limit_error(RuntimeError("Rate limit exceeded; too many requests"))
    assert is_rate_limit_error(RuntimeError("Quota exhausted"))
    assert not is_rate_limit_error(ValueError("bad input"))
    assert not is_rate_limit_error(RuntimeError("404 not found"))


def test_detector_structured_status_overrides_message_text():
    # The crux: the prompt embeds the candidate's resume, and the SDKs echo the request in
    # the error str(). A non-429 error whose MESSAGE mentions rate limits must NOT be retried.
    msg = "INVALID_ARGUMENT: resume reads 'cut 429 errors, enforce rate limit and quota; too many requests'"

    class BadReq(Exception):              # anthropic-style: clean .status_code
        status_code = 400

    class GoogleApiErr(Exception):        # google-genai-style: clean .code (int)
        code = 400

    class HttpxErr(Exception):            # httpx-style: status on .response
        response = type("R", (), {"status_code": 403})()

    assert not is_rate_limit_error(BadReq(msg))
    assert not is_rate_limit_error(GoogleApiErr(msg))
    assert not is_rate_limit_error(HttpxErr(msg))

    # genuine 429s with the same vocabulary ARE retried; '429' inside a larger number is not
    class TooMany(Exception):
        status_code = 429

    class Grpc(Exception):
        status = "RESOURCE_EXHAUSTED"

    assert is_rate_limit_error(TooMany("slow down"))
    assert is_rate_limit_error(Grpc("quota for the project is exhausted"))
    assert not is_rate_limit_error(RuntimeError("gateway timeout on host 14290"))  # \\b429\\b


def test_transparent_proxy_delegates_identity():
    eng, _ = _wrap(_FlakyEngine(fail_times=0))
    assert eng.name == "fake" and eng.model == "fake-1" and eng.info()["model"] == "fake-1"


def test_pause_emits_rate_limited_events():
    events: list[dict] = []
    eng, _ = _wrap(_FlakyEngine(fail_times=1), on_wait=events.append)
    eng.complete("s", "p")
    rl = [e for e in events if e["type"] == "rate_limited"]
    assert rl and rl[0]["attempt"] == 1 and rl[0]["wait_s"] == 30 and rl[0]["engine"] == "fake"


def test_pause_is_cancelable_via_on_wait():
    # on_wait raises RunCancelled on force-stop; the wait must stop promptly, mid-sleep
    polls = {"n": 0}

    def on_wait(_ev):
        polls["n"] += 1
        if polls["n"] >= 2:
            raise RunCancelled()

    eng, waited = _wrap(_FlakyEngine(fail_times=1), on_wait=on_wait, poll_s=1.0)
    with pytest.raises(RunCancelled):
        eng.complete("s", "p")
    assert polls["n"] == 2 and waited == [1.0]   # interrupted after one 1 s chunk, not 30 s
