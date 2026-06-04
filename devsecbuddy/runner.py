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


def run_assessment(adapter: AppAdapter, vectors: list[AttackVector], corpus,
                   ledger: Ledger | None = None, engine_name: str = "mock") -> dict:
    """Run all three phases against one tile and persist results to the ledger."""
    own_ledger = ledger is None
    ledger = ledger or Ledger()
    enabled = [v for v in vectors if v.enabled]
    run_id = None
    try:
        ledger.register_tile(adapter)
        run_id = ledger.open_run(adapter.tile_id, engine_name)

        profiler = BaselineProfiler()
        profiler.observe(adapter, corpus)
        baseline = profiler.build(adapter.tile_id)
        ledger.record_baseline(run_id, baseline)

        ledger.snapshot_vectors(enabled)
        prober = AdversarialProber(enabled, baseline, list(corpus))
        results = prober.probe(adapter)
        findings = ledger.record(run_id, results, vectors=enabled)

        summary = _summarize(results, findings)
        ledger.close_run(run_id, summary)
        return {"run_id": run_id, "tile_id": adapter.tile_id, "baseline": baseline,
                "results": results, "findings": findings, "summary": summary}
    except Exception:
        if run_id is not None:
            ledger.fail_run(run_id)
        raise
    finally:
        if own_ledger:
            ledger.close()


def _summarize(results, findings) -> dict:
    return {
        "probes_run": len(results),
        "vulnerabilities_found": len(findings),
        "probes_passed": sum(1 for r in results if not r.success),
        "by_severity": dict(Counter(f.severity for f in findings)),
        "by_category": dict(Counter(f.category for f in findings)),
    }
