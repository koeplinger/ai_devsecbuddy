"""Cloud engine adapters — designed now, wired up in roadmap M6.

Both satisfy the ``AIEngine`` protocol structurally but intentionally raise
``NotImplementedError`` from ``complete``: there are no Anthropic / Vertex
accounts yet. ``MockEngine`` is the default and runs offline today. The required
setup for each is documented in docs/ai-engines.md ("Enabling the cloud adapters").
"""
from __future__ import annotations

from ..models import EngineParams, EngineResponse


class _UnwiredEngine:
    name = "unwired"
    _provider = "?"
    _requirements: tuple[str, ...] = ()

    def __init__(self, **kwargs) -> None:
        self._config = kwargs

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider": self._provider,
            "deterministic": False,
            "implemented": False,
            "requires": list(self._requirements),
            "roadmap": "M6",
        }

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        raise NotImplementedError(
            f"{type(self).__name__} ({self._provider}) is designed but not wired up yet "
            f"(roadmap M6). It requires: {', '.join(self._requirements)}. "
            f"The default MockEngine runs offline today — see docs/ai-engines.md."
        )


class AnthropicEngine(_UnwiredEngine):
    name = "anthropic"
    _provider = "Anthropic (Claude)"
    _requirements = (
        "an ANTHROPIC_API_KEY",
        "the anthropic SDK",
        "a Claude model id (e.g. claude-opus-4-8 or claude-sonnet-4-6)",
    )


class VertexEngine(_UnwiredEngine):
    name = "vertex"
    _provider = "Google Vertex AI"
    _requirements = (
        "a GCP project id",
        "a region",
        "service-account credentials",
        "the google-cloud-aiplatform SDK",
    )
