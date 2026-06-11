"""Process-global AI-model-call telemetry for the Run-console stats bar.

Every ``engine.complete()`` is one AI model call. ``TelemetryEngine`` wraps an engine and
records each successful call's wall-clock latency (plus engine name / model id) into a
``CallTelemetry``, which keeps running aggregates since the backend started: total count,
total/average latency, two exponential moving averages of per-call latency, and the last
call's latency + engine/model. Thread-safe: calls are recorded from the run worker thread
while the snapshot is read from request threads.
"""
from __future__ import annotations

import threading
import time

# EMA smoothing factors. "90% weighting of prior" -> alpha 0.1; "70% of prior" -> alpha 0.3.
_EMA_SLOW_ALPHA = 0.1   # ema_90: 0.9 * prior + 0.1 * current  (smoother, lags more)
_EMA_FAST_ALPHA = 0.3   # ema_70: 0.7 * prior + 0.3 * current  (more responsive)


class CallTelemetry:
    """Running stats over every AI model call since the backend process started."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._total_ms = 0.0
        self._ema_slow: float | None = None   # 90%-prior EMA
        self._ema_fast: float | None = None   # 70%-prior EMA
        self._last_ms: float | None = None
        self._last_engine: str | None = None
        self._last_model: str | None = None

    @staticmethod
    def _step(ema: float | None, value: float, alpha: float) -> float:
        return value if ema is None else (1 - alpha) * ema + alpha * value

    def record(self, latency_ms: float, engine: str | None, model: str | None) -> None:
        with self._lock:
            self._count += 1
            self._total_ms += latency_ms
            self._ema_slow = self._step(self._ema_slow, latency_ms, _EMA_SLOW_ALPHA)
            self._ema_fast = self._step(self._ema_fast, latency_ms, _EMA_FAST_ALPHA)
            self._last_ms = latency_ms
            self._last_engine = engine
            self._last_model = model

    def snapshot(self) -> dict:
        """A JSON-able snapshot of the current stats (``None`` for fields with no data yet)."""
        with self._lock:
            n = self._count
            r1 = lambda v: round(v, 1) if v is not None else None  # noqa: E731
            return {
                "count": n,
                "total_ms": round(self._total_ms, 1),
                "avg_ms": round(self._total_ms / n, 1) if n else None,
                "ema_90_ms": r1(self._ema_slow),
                "ema_70_ms": r1(self._ema_fast),
                "last_ms": r1(self._last_ms),
                "last_engine": self._last_engine,
                "last_model": self._last_model,
            }


class TelemetryEngine:
    """Transparently wraps an ``AIEngine`` and times each successful ``complete()`` call,
    recording it into ``telemetry``. Everything else delegates to the wrapped engine, so the
    rest of the stack (``info()``, ``name``, ``model``) is unaffected."""

    def __init__(self, inner, telemetry: CallTelemetry):
        self._inner = inner
        self._telemetry = telemetry

    def __getattr__(self, attr):
        if attr == "_inner":  # guard against recursion before __init__ assigns it
            raise AttributeError(attr)
        return getattr(self._inner, attr)

    def complete(self, system, prompt, params=None):
        started = time.perf_counter()
        response = self._inner.complete(system, prompt, params)  # may raise -> not recorded
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._telemetry.record(latency_ms, getattr(self._inner, "name", None),
                               getattr(response, "model", None))
        return response
