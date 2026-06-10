"""Phase 1 — Passive learning / baseline profiling (docs/phases.md).

``BaselineProfiler`` runs a corpus of *clean* (non-adversarial) requests through a
tile's ordinary ``invoke`` path and accumulates statistics. It never mutates
inputs. The finalized ``Baseline`` gives Phase 2 a per-resume yardstick so a
probed score can be read as a meaningful delta rather than a bare number.
"""
from __future__ import annotations

import statistics
from collections.abc import Iterable

from ._util import now_iso, short_hash
from .adapters import AppAdapter
from .models import AppRequest, Baseline


def resume_key(resume_text: str) -> str:
    """Stable, name-independent key for a resume (keys the per-resume score stats)."""
    return "r-" + short_hash(resume_text, length=8)


# The learning phase re-asks the model up to this many times when a response is malformed.
BASELINE_MAX_RETRIES = 3


def valid_score(response) -> bool:
    """A well-formed scoring response: the model emitted a parseable score inside the
    expected 0–100 band (exclusive of 0). An unparseable response (``score is None``), a
    degenerate ``0``, or an out-of-range value signals that a simpler model errored out /
    didn't actually score, so it should be retried."""
    s = getattr(response, "score", None)
    return s is not None and 0 < s <= 100


class BaselineProfiler:
    def __init__(self) -> None:
        self._tile_id: str | None = None
        self._scores: dict[str, list[float]] = {}
        self._lengths: list[int] = []
        self._refusals = 0
        self._n = 0

    def observe(self, adapter: AppAdapter, corpus: Iterable[AppRequest], on_event=None) -> None:
        """Passively run clean traffic through the tile; accumulate behavior stats.

        Each resume is re-asked until the model returns a well-formed, parseable score
        (simpler models occasionally emit an unparseable response or a degenerate 0), up to
        ``BASELINE_MAX_RETRIES`` retries, then the run moves on rather than blocking — and a
        malformed score never feeds the baseline.

        ``on_event`` (optional) receives a ``learning`` event per resume as it is observed,
        and a ``learning_retry`` event for each re-ask, so the backend can stream progress.
        """
        corpus = list(corpus)
        total = len(corpus)
        for index, request in enumerate(corpus, start=1):
            name = request.fields.get("applicant_name", "")
            if on_event is not None:
                on_event({"type": "learning", "index": index, "total": total, "name": name})

            response = adapter.invoke(request)
            attempt = 0
            while not valid_score(response) and attempt < BASELINE_MAX_RETRIES:
                attempt += 1
                if on_event is not None:
                    on_event({"type": "learning_retry", "index": index, "total": total,
                              "name": name, "attempt": attempt})
                response = adapter.invoke(request)

            self._tile_id = adapter.tile_id
            key = resume_key(request.fields.get("resume_text", request.raw_text or ""))
            if valid_score(response):  # only a real score feeds the baseline (no 0 / None pollution)
                self._scores.setdefault(key, []).append(response.score)
            self._lengths.append(len(response.text or ""))
            if response.metadata.get("refused"):
                self._refusals += 1
            self._n += 1

    def build(self, tile_id: str) -> Baseline:
        """Finalize and return the learned ``Baseline``."""
        score_stats: dict[str, dict] = {}
        for key, values in self._scores.items():
            score_stats[key] = {
                "mean": round(statistics.fmean(values), 4),
                "stdev": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
                "n": len(values),
            }
        all_values = [v for values in self._scores.values() for v in values]
        if all_values:
            score_stats["__overall__"] = {
                "mean": round(statistics.fmean(all_values), 4),
                "min": min(all_values),
                "max": max(all_values),
                "n": len(all_values),
            }
        behavior_signature = {
            "refusal_rate": round(self._refusals / self._n, 4) if self._n else 0.0,
            "response_length_mean": round(statistics.fmean(self._lengths), 2) if self._lengths else 0.0,
            "markers": [],
        }
        return Baseline(
            tile_id=tile_id,
            created_at=now_iso(),
            sample_count=self._n,
            score_stats=score_stats,
            behavior_signature=behavior_signature,
            notes="clean, non-adversarial corpus",
        )
