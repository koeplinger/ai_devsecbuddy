"""Rate-limit wait-and-retry wrapper for any ``AIEngine``.

A real engine can return a rate-limit / quota error (HTTP 429 / ``RESOURCE_EXHAUSTED``)
under load. ``RateLimitRetryEngine`` wraps an engine so that, instead of failing the run,
a scorer **pauses and retries** on a rate-limit error — escalating the wait by a fixed
step on each hit *within the same run*: 30 s, then 60 s, then 90 s, … Each scorer (run)
starts fresh, because the backend builds a new engine per run.

The pause is reported — and made interruptible — through the run's ``on_event`` hook
(``on_wait``): it streams a ``rate_limited`` event (so the UI shows the wait) and, because
that hook raises ``RunCancelled`` when the job is force-stopped, a force-stop interrupts
the wait promptly. With no hook (the synchronous path) it simply sleeps and retries.
"""
from __future__ import annotations

import re
import time

# Word-boundary rate-limit vocabulary for the TEXT fallback (used only when no structured
# HTTP status is available). Word boundaries avoid matching '429' inside '14290' etc.
_RATE_LIMIT_TEXT = re.compile(
    r"\b(429|resource_exhausted|rate[ _-]?limit|too many requests|quota)\b", re.IGNORECASE
)

# Escalating-backoff step and cap. The Nth rate-limit pause in a run waits N * step; after
# ``RATE_LIMIT_MAX_RETRIES`` pauses the rate-limit error is allowed to propagate (the run
# fails) rather than waiting forever — a force-stop can end it sooner.
RATE_LIMIT_STEP_S = 30.0
RATE_LIMIT_MAX_RETRIES = 6
_POLL_S = 2.0  # how often to re-emit the wait (also the force-stop reaction latency)


def _numeric_status(exc: BaseException):
    """The exception's HTTP status as an int, if it carries one (anthropic ``.status_code``,
    google-genai ``.code``, or httpx ``.response.status_code``); else None."""
    for attr in ("status_code", "code", "http_status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    val = getattr(getattr(exc, "response", None), "status_code", None)
    return val if isinstance(val, int) and not isinstance(val, bool) else None


def is_rate_limit_error(exc: BaseException) -> bool:
    """True if ``exc`` is a provider rate-limit / quota error (HTTP 429 / ``RESOURCE_EXHAUSTED``).

    A **structured HTTP status is authoritative**: a known non-429 (400 bad-request, 401/403
    auth, 404, …) is NOT a rate limit even if the message text echoes the prompt's words —
    important here because the prompt embeds the candidate's resume, whose text could mention
    "rate limit"/"quota"/"429", and the SDKs echo the request back in the error. Only when no
    numeric status is available does it fall back to a tight, word-boundary text scan."""
    status = _numeric_status(exc)
    if status is not None:
        return status == 429
    if str(getattr(exc, "status", "")).upper() == "RESOURCE_EXHAUSTED":   # grpc/google name
        return True
    return bool(_RATE_LIMIT_TEXT.search(f"{type(exc).__name__}: {exc}"))


class RateLimitRetryEngine:
    """Transparent proxy around an ``AIEngine`` that retries rate-limited ``complete`` calls
    with an escalating pause. Every other attribute/method delegates to the wrapped engine,
    so adapters, the ledger, and ``_engine_model`` see the real engine's name/model/info."""

    def __init__(self, inner, on_wait=None, step_s: float = RATE_LIMIT_STEP_S,
                 max_retries: int = RATE_LIMIT_MAX_RETRIES, poll_s: float = _POLL_S,
                 sleep=time.sleep) -> None:
        self._inner = inner
        self._on_wait = on_wait        # the run's on_event: shows the wait + raises on force-stop
        self._step_s = step_s
        self._max_retries = max_retries
        self._poll_s = poll_s
        self._sleep = sleep
        self._pauses = 0               # per-scorer: rate-limit pauses so far (escalates the wait)

    def __getattr__(self, attr: str):
        # Delegate everything not defined here (name, model, info, …) to the wrapped engine.
        if attr == "_inner":           # not set yet -> avoid infinite recursion
            raise AttributeError(attr)
        return getattr(self._inner, attr)

    def complete(self, system, prompt, params=None):
        while True:
            try:
                return self._inner.complete(system, prompt, params)
            except Exception as exc:
                if self._pauses >= self._max_retries or not is_rate_limit_error(exc):
                    raise
                self._pauses += 1
                self._pause(self._step_s * self._pauses)   # 30, 60, 90, … (per scorer)

    def _pause(self, wait_s: float) -> None:
        """Sleep ``wait_s`` seconds, re-announcing the wait through ``on_wait`` so the UI
        shows it and a force-stop (which ``on_wait`` raises as ``RunCancelled``) interrupts
        it within ``poll_s``."""
        remaining = wait_s
        while remaining > 0:
            if self._on_wait is not None:
                self._on_wait({
                    "type": "rate_limited", "attempt": self._pauses,
                    "wait_s": int(wait_s), "remaining_s": int(remaining + 0.999),
                    "engine": getattr(self._inner, "name", None),
                })
            chunk = self._poll_s if remaining > self._poll_s else remaining
            self._sleep(chunk)
            remaining -= chunk
