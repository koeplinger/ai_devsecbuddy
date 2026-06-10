"""AI DevSecBuddy — the product library (roadmap M1 core).

Implements the single shared contract (``AppAdapter`` / ``AIEngine``), the core
data models, the three phase components (``BaselineProfiler``, ``AdversarialProber``,
``Ledger``), and the deterministic offline ``MockEngine``. See the docs/ set for
the binding design. ``AnthropicEngine`` and ``VertexEngine`` are designed now and
wired up in roadmap M6 (no accounts yet).
"""
from __future__ import annotations

from .adapters import AppAdapter
from .attack_library import DEFAULT_VECTORS_DIR, load_vectors
from .engines import AIEngine, AnthropicEngine, MockEngine, VertexEngine, get_engine
from .fairness import DEFAULT_SELECTION_THRESHOLD, fairness_metrics
from .ledger import DEFAULT_DB_PATH, Ledger
from .models import (
    CATEGORIES,
    CATEGORY_OWASP,
    INJECTION_CWE,
    SEVERITIES,
    STATUSES,
    AppRequest,
    AppResponse,
    AttackVector,
    Baseline,
    EngineParams,
    EngineResponse,
    Finding,
    ProbeResult,
)
from .prober import AdversarialProber
from .profiler import BaselineProfiler
from .runner import RunCancelled, run_assessment

__version__ = "0.1.0"

__all__ = [
    # contracts
    "AppAdapter", "AIEngine",
    # engines
    "MockEngine", "AnthropicEngine", "VertexEngine", "get_engine",
    # data models
    "EngineParams", "EngineResponse", "AppRequest", "AppResponse", "AttackVector",
    "Baseline", "ProbeResult", "Finding",
    # vocabularies
    "CATEGORIES", "SEVERITIES", "STATUSES", "CATEGORY_OWASP", "INJECTION_CWE",
    # phases
    "BaselineProfiler", "AdversarialProber", "Ledger",
    # helpers
    "load_vectors", "run_assessment", "RunCancelled", "fairness_metrics", "DEFAULT_SELECTION_THRESHOLD",
    "DEFAULT_VECTORS_DIR", "DEFAULT_DB_PATH",
    "__version__",
]
