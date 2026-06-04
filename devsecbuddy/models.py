"""Core data models and shared vocabularies for the devsecbuddy library.

Every dataclass here matches the binding shapes documented in the Design Bible
(docs/phases.md, docs/ai-engines.md, docs/attack-library.md, docs/architecture.md).
Field names are the schema of record; do not rename without updating the docs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- Shared vocabularies (binding; docs/attack-library.md §1.5, §2) -----------

CATEGORIES = ("prompt_injection", "modal_jailbreak", "data_exfiltration", "bias_fairness")
SEVERITIES = ("info", "low", "medium", "high", "critical")
STATUSES = ("open", "triaged", "mitigated", "accepted_risk", "false_positive")

# category -> OWASP LLM Top 10 (2025) id  (docs/attack-library.md §1.5)
CATEGORY_OWASP = {
    "prompt_injection": "LLM01",
    "modal_jailbreak": "LLM01",
    "data_exfiltration": "LLM06",
    "bias_fairness": "LLM09",
}

# CWE applied to injection-class findings (docs/vulnerability-ledger.md §8)
INJECTION_CWE = "CWE-1427"


# --- Engine I/O (docs/ai-engines.md) ------------------------------------------

@dataclass
class EngineParams:
    """Inference parameters. ``seed`` is what lets a deterministic engine pin output."""
    temperature: float = 0.0
    max_tokens: int = 256
    seed: int | None = 7
    stop: list[str] | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class EngineResponse:
    """The single return shape of ``AIEngine.complete``."""
    text: str
    model: str
    finish_reason: str | None = None
    usage: dict | None = None
    raw: dict | None = None
    latency_ms: float | None = None
    metadata: dict = field(default_factory=dict)


# --- App contract I/O (docs/phases.md, docs/architecture.md §3.1) -------------

@dataclass
class AppRequest:
    fields: dict                 # named inputs, e.g. {"applicant_name": "...", "resume_text": "..."}
    raw_text: str | None = None  # optional fully-rendered prompt


@dataclass
class AppResponse:
    score: float | None          # primary structured output (resume score, 0-100)
    text: str                    # free-text model output
    metadata: dict = field(default_factory=dict)  # tile id, engine name, guardrail flags


# --- Attack vector (docs/attack-library.md §2) --------------------------------

@dataclass
class AttackVector:
    id: str
    category: str
    owasp_ref: str
    severity: str
    description: str
    target: str                       # the AppRequest field mutated
    success_criteria: dict            # {"type": ..., type-specific keys}
    mitigation: str
    references: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    payload: str | None = None        # one-of: static payload text
    template: str | dict | None = None  # one-of: parameterized ({field}) or structured map


# --- Phase outputs (docs/phases.md) -------------------------------------------

@dataclass
class Baseline:
    tile_id: str
    created_at: str
    sample_count: int
    score_stats: dict            # per-resume mean/stdev/min/max of clean scores
    behavior_signature: dict     # refusal rate, response-length norms, markers
    notes: str = ""


@dataclass
class ProbeResult:
    vector_id: str
    tile_id: str
    success: bool                # True == attack SUCCEEDED == vulnerability
    severity: str
    category: str
    request_snapshot: dict       # exact fields/payload sent (repro)
    response_snapshot: dict      # score + text + metadata observed (evidence)
    metric_value: float | None = None
    baseline_ref: str | None = None
    detail: str = ""


@dataclass
class Finding:
    id: str
    run_id: str
    tile_id: str
    vector_id: str
    category: str
    severity: str
    status: str                  # open | triaged | mitigated | accepted_risk | false_positive
    repro: dict
    evidence: dict
    mitigation_guidance: str
    owasp_ref: str
    cwe: str | None
    fingerprint: str
    created_at: str
