"""Editable application defaults — data, not code.

Everything here is configuration you can add to without touching Python: the per-engine
model catalogs (`models.json`), the clean-corpus resumes (`resumes.json`), and the
demographic name/interest pools the bias probes swap across (`demographics.json`).

Design notes:
- **Model catalogs are ordered cheapest → most expensive.** There are no tier labels —
  position is the only ranking, so adding a model (or re-ordering when today's "high" model
  becomes tomorrow's "low") is a one-line edit with no code change.
- Each loader returns fresh copies, so callers can't mutate the cached source data.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def _load(name: str):
    return json.loads((_DIR / name).read_text(encoding="utf-8"))


def model_catalog(engine: str) -> list[dict]:
    """Selectable models for `engine`, ordered cheapest → most expensive (each `{id, label}`)."""
    return [dict(m) for m in _load("models.json").get(engine, {}).get("models", [])]


def default_model(engine: str) -> str | None:
    """The default model id for `engine` (used when no per-run model is selected)."""
    return _load("models.json").get(engine, {}).get("default")


def resumes() -> list[dict]:
    """The default clean-corpus resumes as raw dicts
    (`applicant_name`, `gender`, `ethnicity`, `resume_text`)."""
    return [dict(r) for r in _load("resumes.json")]


def _pool(key: str) -> dict:
    # JSON keys are "gender:ethnicity"; rehydrate to the (gender, ethnicity) tuple keys the
    # prober indexes by. Copy mutable (list) values so callers can't mutate the cached source.
    return {tuple(k.split(":", 1)): (list(v) if isinstance(v, list) else v)
            for k, v in _load("demographics.json").get(key, {}).items()}


def name_pool() -> dict:
    """`(gender, ethnicity) -> [candidate names]` the bias probe swaps in."""
    return _pool("name_pool")


def interest_pool() -> dict:
    """`(gender, ethnicity) -> interest sentence` the proxy-feature probe swaps in."""
    return _pool("interest_pool")
