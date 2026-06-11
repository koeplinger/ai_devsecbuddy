"""End-to-end run orchestration — the documented open_run -> ... -> close_run flow.

This wires the three phases in the exact sequence from docs/phases.md. The backend
(roadmap M2) drives this same sequence behind its run API; the library ships the
orchestrator so the CLI and tests can run a full assessment in one call.
"""
from __future__ import annotations

from collections import Counter

from .adapters import AppAdapter
from .ledger import Ledger
from .models import AttackVector
from .prober import AdversarialProber
from .profiler import BaselineProfiler


class RunCancelled(Exception):
    """Raised to stop an in-flight run cleanly (a force-stop). Typically thrown from the
    ``on_event`` callback at a probe boundary; ``run_assessment`` marks the run
    ``cancelled`` (not ``failed``) and re-raises so the caller can react."""


def run_assessment(adapter: AppAdapter, vectors: list[AttackVector], corpus,
                   ledger: Ledger | None = None, engine_name: str = "mock",
                   on_event=None) -> dict:
    """Run all three phases against one tile and persist results to the ledger.

    ``on_event`` (optional) is a progress callback. It receives small dicts marking
    the run lifecycle — ``run_started``, ``phase`` (baseline/probing/reporting),
    ``baseline_done``, and the prober's per-vector ``probe_started`` / ``probe_done``
    — so a caller (the backend) can stream live progress while the run is in flight.
    It never changes the return value, and a failure inside it must not abort a run,
    so callbacks are best-effort.
    """
    emit = on_event if on_event is not None else (lambda _event: None)
    own_ledger = ledger is None
    ledger = ledger or Ledger()
    corpus = list(corpus)  # materialize once: observed in learning, re-used for probing
    enabled = [v for v in vectors if v.enabled]
    run_id = None
    try:
        ledger.register_tile(adapter)
        run_id = ledger.open_run(adapter.tile_id, engine_name)
        emit({"type": "run_started", "run_id": run_id, "tile_id": adapter.tile_id,
              "engine_name": engine_name, "total_probes": len(enabled)})

        emit({"type": "phase", "phase": "baseline"})
        profiler = BaselineProfiler()
        profiler.observe(adapter, corpus, on_event=emit)
        baseline = profiler.build(adapter.tile_id)
        ledger.record_baseline(run_id, baseline)
        emit({"type": "baseline_done", "sample_count": baseline.sample_count})

        ledger.snapshot_vectors(enabled)
        emit({"type": "phase", "phase": "probing"})
        prober = AdversarialProber(enabled, baseline, list(corpus))
        results = prober.probe(adapter, on_event=emit)

        emit({"type": "phase", "phase": "reporting"})
        findings = ledger.record(run_id, results, vectors=enabled, model=_engine_model(adapter))

        summary = _summarize(results, findings)
        ledger.close_run(run_id, summary)
        return {"run_id": run_id, "tile_id": adapter.tile_id, "baseline": baseline,
                "results": results, "findings": findings, "summary": summary}
    except RunCancelled:
        if run_id is not None:
            ledger.cancel_run(run_id)         # force-stopped -> 'cancelled', not 'failed'
        raise
    except Exception:
        if run_id is not None:
            ledger.fail_run(run_id)
        raise
    finally:
        if own_ledger:
            ledger.close()


def _engine_model(adapter) -> str | None:
    """The model id the run's engine reports (e.g. 'gemini-2.5-flash'), recorded on
    each finding so the ledger can show which model produced it. Best-effort."""
    engine = getattr(adapter, "engine", None)
    if engine is None:
        return None
    try:
        model = engine.info().get("model")
    except Exception:
        model = None
    return model or getattr(engine, "model", None)


def _summarize(results, findings) -> dict:
    # `unscorable_response` findings are flags (the model couldn't be evaluated), not vulns:
    # keep them out of vulnerabilities_found, and count probes that couldn't be scored apart
    # from those that genuinely passed.
    vulns = [f for f in findings if f.category != "unscorable_response"]
    unscorable = [f for f in findings if f.category == "unscorable_response"]
    return {
        "probes_run": len(results),
        "vulnerabilities_found": len(vulns),
        "unscorable": len(unscorable),
        "probes_passed": sum(1 for r in results if not r.success and not r.unscorable),
        "by_severity": dict(Counter(f.severity for f in findings)),
        "by_category": dict(Counter(f.category for f in findings)),
    }
