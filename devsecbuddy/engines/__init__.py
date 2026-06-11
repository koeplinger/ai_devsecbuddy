"""Pluggable model engines (docs/ai-engines.md).

Every tile and every piece of devsecbuddy logic talks to a model only through the
``AIEngine`` protocol — never to a concrete vendor SDK. ``MockEngine`` is the
default; ``AnthropicEngine`` and ``VertexEngine`` are designed now, wired in M6.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import EngineParams, EngineResponse
from .cloud import AnthropicEngine, EngineNotConfigured, GeminiProxyEngine, VertexEngine
from .mock import MockEngine
from .retry import RateLimitRetryEngine, is_rate_limit_error


@runtime_checkable
class AIEngine(Protocol):
    name: str

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        ...

    def info(self) -> dict:
        ...


_ENGINES = {"mock": MockEngine, "anthropic": AnthropicEngine, "vertex": VertexEngine,
            "gemini": GeminiProxyEngine}


def get_engine(name: str | None = None, **kwargs) -> AIEngine:
    """Resolve an engine by name. Defaults to ``MockEngine`` when ``name`` is None.

    Engine selection is normally the backend's responsibility; this factory exists
    so the library, CLI and tests can construct the default offline engine.
    """
    key = (name or "mock").lower()
    try:
        return _ENGINES[key](**kwargs)
    except KeyError:
        raise ValueError(f"Unknown engine {name!r}; choose one of {sorted(_ENGINES)}") from None


__all__ = ["AIEngine", "MockEngine", "AnthropicEngine", "VertexEngine", "GeminiProxyEngine",
           "get_engine", "EngineNotConfigured", "RateLimitRetryEngine", "is_rate_limit_error"]
