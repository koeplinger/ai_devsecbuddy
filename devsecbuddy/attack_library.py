"""Load attack vectors from ``attack-library/vectors/*.yaml`` (docs/attack-library.md).

The library is *data, not code*: a list of vector records per YAML file. The
loader validates the binding schema (§2) and the category->OWASP mapping (§1.5),
so a malformed or drifting vector fails loudly instead of silently misbehaving.
"""
from __future__ import annotations

import glob
import os

import yaml

from .models import CATEGORIES, CATEGORY_OWASP, SEVERITIES, AttackVector

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_VECTORS_DIR = os.path.join(_REPO_ROOT, "attack-library", "vectors")

_REQUIRED = (
    "id", "category", "owasp_ref", "severity", "description", "target",
    "success_criteria", "mitigation", "references", "tags", "enabled",
)

# The four binding success_criteria types (docs/attack-library.md §2.1).
CRITERIA_TYPES = (
    "score_inflation", "score_delta_vs_baseline", "score_delta",
    "substring_match", "refusal_expected",
)


def load_vectors(path: str | None = None, enabled_only: bool = False) -> list[AttackVector]:
    """Load and validate every vector under ``path`` (default: the repo vectors dir)."""
    path = path or DEFAULT_VECTORS_DIR
    files = sorted(glob.glob(os.path.join(path, "*.yaml")) + glob.glob(os.path.join(path, "*.yml")))
    vectors: list[AttackVector] = []
    seen: dict[str, str] = {}
    for fp in files:
        with open(fp, "r", encoding="utf-8") as fh:
            records = yaml.safe_load(fh) or []
        if not isinstance(records, list):
            raise ValueError(f"{fp}: expected a YAML list of vectors, got {type(records).__name__}")
        for rec in records:
            vector = _parse(rec, fp)
            if vector.id in seen:
                raise ValueError(f"duplicate vector id {vector.id!r} in {fp} and {seen[vector.id]}")
            seen[vector.id] = fp
            if enabled_only and not vector.enabled:
                continue
            vectors.append(vector)
    return vectors


def _parse(rec: dict, fp: str) -> AttackVector:
    if not isinstance(rec, dict):
        raise ValueError(f"{fp}: each vector must be a mapping, got {type(rec).__name__}")
    missing = [k for k in _REQUIRED if k not in rec]
    if missing:
        raise ValueError(f"{fp}: vector {rec.get('id', '?')!r} missing fields: {missing}")
    if "payload" not in rec and "template" not in rec:
        raise ValueError(f"{fp}: vector {rec['id']!r} must define one of payload/template")
    if rec["category"] not in CATEGORIES:
        raise ValueError(f"{fp}: vector {rec['id']!r} has unknown category {rec['category']!r}")
    if rec["severity"] not in SEVERITIES:
        raise ValueError(f"{fp}: vector {rec['id']!r} has unknown severity {rec['severity']!r}")
    expected = CATEGORY_OWASP[rec["category"]]
    if rec["owasp_ref"] != expected:
        raise ValueError(
            f"{fp}: vector {rec['id']!r} owasp_ref {rec['owasp_ref']!r} != {expected!r} "
            f"for category {rec['category']!r} (see docs/attack-library.md §1.5)"
        )
    if not isinstance(rec["success_criteria"], dict) or "type" not in rec["success_criteria"]:
        raise ValueError(f"{fp}: vector {rec['id']!r} success_criteria must be a map with a 'type'")
    ctype = rec["success_criteria"]["type"]
    if ctype not in CRITERIA_TYPES:
        raise ValueError(f"{fp}: vector {rec['id']!r} unknown success_criteria type {ctype!r}; "
                         f"expected one of {CRITERIA_TYPES}")
    return AttackVector(
        id=rec["id"],
        category=rec["category"],
        owasp_ref=rec["owasp_ref"],
        severity=rec["severity"],
        description=rec["description"],
        target=rec["target"],
        success_criteria=rec["success_criteria"],
        mitigation=rec["mitigation"],
        references=list(rec.get("references", [])),
        tags=list(rec.get("tags", [])),
        enabled=bool(rec["enabled"]),
        payload=rec.get("payload"),
        template=rec.get("template"),
    )
