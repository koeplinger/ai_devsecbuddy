"""Cloud engine adapters — Claude via the Anthropic API and via Google Vertex AI.

Both adapters speak the Anthropic **Messages API** (the Vertex one through the
SDK's ``AnthropicVertex`` client), so they share one request/response mapping; only
client construction and the model id differ. They are wired up in roadmap **M6**.

Credentials are read from the environment and the SDK clients are imported lazily,
so importing this module never requires the SDKs or any keys. ``complete()`` raises
``EngineNotConfigured`` (a clear, catchable error) when the SDK is missing or the
credentials are absent — see docs/setup/ for how to obtain them.

Real models are non-deterministic, so ``info()["deterministic"]`` is ``False`` and
findings vary run-to-run (the ledger captures per-run evidence).
"""
from __future__ import annotations

import os
import time

from ..models import EngineParams, EngineResponse

# Default to the cheapest current Claude model for testing (docs/setup/).
DEFAULT_MODEL = "claude-haiku-4-5"
# Opus 4.7/4.8 reject sampling params (temperature/top_p/top_k) — drop them there.
_NO_SAMPLING_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8")


class EngineNotConfigured(RuntimeError):
    """A real engine is implemented but its SDK or credentials are not available."""


def _messages_complete(client, model: str, system: str, prompt: str,
                       params: EngineParams, provider: str) -> EngineResponse:
    """Shared Anthropic Messages-API call + mapping into our EngineResponse."""
    model = (params.extra or {}).get("model", model)   # optional per-request override
    request: dict = {
        "model": model,
        "max_tokens": params.max_tokens,
        # The system prompt (scoring rubric) is stable across probes; cache it. (On
        # small prefixes below the model's minimum this silently no-ops — see
        # docs/ai-engines.md — but it engages automatically once the prefix grows.)
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": prompt}],
    }
    if params.stop:
        request["stop_sequences"] = list(params.stop)
    if not model.startswith(_NO_SAMPLING_PREFIXES):
        request["temperature"] = params.temperature

    started = time.perf_counter()
    response = client.messages.create(**request)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    usage = _usage_dict(getattr(response, "usage", None))
    return EngineResponse(
        text=text,
        model=getattr(response, "model", model),
        finish_reason=getattr(response, "stop_reason", None),
        usage=usage,
        raw={"id": getattr(response, "id", None)},
        latency_ms=latency_ms,
        metadata={
            "deterministic": False,
            "provider": provider,
            "request_id": getattr(response, "_request_id", None),
            "cache_read_input_tokens": (usage or {}).get("cache_read_input_tokens"),
        },
    )


def _usage_dict(usage) -> dict | None:
    if usage is None:
        return None
    out = {}
    for key in ("input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            out[key] = value
    return out or None


class AnthropicEngine:
    """Claude via the Anthropic API (docs/setup/anthropic-signup.md)."""

    name = "anthropic"

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 client=None, **kwargs):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("DEVSECBUDDY_ANTHROPIC_MODEL", DEFAULT_MODEL)
        self._client = client  # injectable for tests / reuse
        self._config = kwargs

    def configured(self) -> bool:
        return bool(self.api_key) or self._client is not None

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider": "Anthropic (Claude)",
            "deterministic": False,
            "implemented": True,
            "configured": self.configured(),
            "model": self.model,
            "requires": ["ANTHROPIC_API_KEY", "the anthropic SDK"],
            "roadmap": "M6",
        }

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise EngineNotConfigured(
                "the 'anthropic' SDK is not installed — `pip install \"anthropic\"` "
                "(or `pip install -e .[anthropic]`)."
            ) from exc
        if not self.api_key:
            raise EngineNotConfigured(
                "ANTHROPIC_API_KEY is not set — see docs/setup/anthropic-signup.md."
            )
        self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        return _messages_complete(self._get_client(), self.model, system, prompt,
                                  params or EngineParams(), provider="anthropic")


class VertexEngine:
    """Claude on Google Vertex AI via the Anthropic SDK's Vertex client
    (docs/setup/google-vertex-signup.md)."""

    name = "vertex"

    def __init__(self, *, project: str | None = None, region: str | None = None,
                 model: str | None = None, client=None, **kwargs):
        self.project = project or os.environ.get("DEVSECBUDDY_VERTEX_PROJECT") \
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.region = region or os.environ.get("DEVSECBUDDY_VERTEX_REGION") \
            or os.environ.get("CLOUD_ML_REGION", "us-east5")
        self.model = model or os.environ.get("DEVSECBUDDY_VERTEX_MODEL", DEFAULT_MODEL)
        self._client = client
        self._config = kwargs

    def configured(self) -> bool:
        return bool(self.project and self.region) or self._client is not None

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider": "Google Vertex AI (Claude)",
            "deterministic": False,
            "implemented": True,
            "configured": self.configured(),
            "model": self.model,
            "project": self.project,
            "region": self.region,
            "requires": ["a GCP project + region", "ADC / service-account credentials",
                         "the anthropic[vertex] SDK"],
            "roadmap": "M6",
        }

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from anthropic import AnthropicVertex
        except ImportError as exc:
            raise EngineNotConfigured(
                "the Vertex client is unavailable — `pip install \"anthropic[vertex]\"` "
                "(or `pip install -e .[vertex]`)."
            ) from exc
        if not (self.project and self.region):
            raise EngineNotConfigured(
                "DEVSECBUDDY_VERTEX_PROJECT and DEVSECBUDDY_VERTEX_REGION are required — "
                "see docs/setup/google-vertex-signup.md."
            )
        self._client = AnthropicVertex(project_id=self.project, region=self.region)
        return self._client

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        return _messages_complete(self._get_client(), self.model, system, prompt,
                                  params or EngineParams(), provider="vertex")
