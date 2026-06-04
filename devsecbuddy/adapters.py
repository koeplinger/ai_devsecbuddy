"""The ``AppAdapter`` protocol — the single shared contract every tile implements.

The ``AdversarialProber`` and ``BaselineProfiler`` talk *only* to this protocol,
never to a concrete tile, so the same probe suite runs unchanged across the whole
tile ladder (docs/architecture.md §3.1, docs/phases.md).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import AppRequest, AppResponse


@runtime_checkable
class AppAdapter(Protocol):
    tile_id: str
    name: str

    def describe(self) -> dict:
        """Static metadata: input field names, output schema, declared guardrails."""
        ...

    def invoke(self, request: AppRequest) -> AppResponse:
        """Run the tile for one request: apply guardrails, call the AIEngine, return output."""
        ...
