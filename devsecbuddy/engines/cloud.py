"""Cloud engine adapters — three access paths to two model families.

* ``AnthropicEngine`` runs **Claude directly against the Anthropic API** (the
  Anthropic SDK, ``anthropic.Anthropic``) using the **Messages API**.
* ``VertexEngine`` runs **Google's Gemini models on GCP Vertex AI** (the
  ``google-genai`` SDK in Vertex mode) using the **generate_content API**, with
  gcloud / Application-Default-Credentials auth.
* ``GeminiProxyEngine`` runs **Gemini through a URL-based API gateway** — plain HTTP
  with an API key in a header (no SDK, just ``urllib``). This is the "third way" to
  reach Google's models when you have a gateway URL + key instead of gcloud login.
  All connection details are env-configurable (``GEMINI_*``); gateway-specific extras
  (cost attribution) are optional (``GEMINI_CUSTOM_*``).

So "anthropic" = Claude-direct, "vertex" = Gemini-via-gcloud, "gemini" = Gemini-via-gateway —
each uses its provider's own request/response shape. All are wired in M6.

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

# Default to the cheapest current Claude model for the Anthropic path (docs/setup/).
DEFAULT_MODEL = "claude-haiku-4-5"
# Default Gemini model for the Vertex path — cheap + fast (docs/setup/).
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
# Opus 4.7/4.8 reject sampling params (temperature/top_p/top_k) — drop them there.
_NO_SAMPLING_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8")

# Per-request timeout for cloud calls. The backend runs assessments single-threaded, so a
# call with no timeout would wedge the one worker (and the whole queue). 120 s is generous
# for a short scoring prompt; bounds the worst case far below the SDKs' multi-minute default.
_REQUEST_TIMEOUT_S = 120.0
_REQUEST_TIMEOUT_MS = int(_REQUEST_TIMEOUT_S * 1000)

# Selectable models per provider, low -> high tier. The UI offers these; any one is a
# valid DEVSECBUDDY_*_MODEL default. Real models are non-deterministic and higher tiers
# cost more — see each provider's pricing page (docs/setup/).
ANTHROPIC_MODELS = (
    {"id": "claude-haiku-4-5", "tier": "low", "label": "Claude Haiku 4.5"},
    {"id": "claude-sonnet-4-6", "tier": "mid", "label": "Claude Sonnet 4.6"},
    {"id": "claude-opus-4-8", "tier": "high", "label": "Claude Opus 4.8"},
)
GEMINI_MODELS = (
    {"id": "gemini-2.5-flash-lite", "tier": "low", "label": "Gemini 2.5 Flash-Lite"},
    {"id": "gemini-2.5-flash", "tier": "mid", "label": "Gemini 2.5 Flash"},
    {"id": "gemini-2.5-pro", "tier": "high", "label": "Gemini 2.5 Pro"},
)


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


# --- Gemini on Vertex (google-genai generate_content) -------------------------

def _gemini_complete(client, model: str, system: str, prompt: str,
                     params: EngineParams, project: str | None, region: str | None) -> EngineResponse:
    """Call Gemini via the google-genai Vertex client + map into our EngineResponse."""
    from google.genai import types  # lazy: only needed when actually running a run

    model = (params.extra or {}).get("model", model)   # optional per-request override
    config_kwargs: dict = {
        "system_instruction": system,
        "temperature": params.temperature,
        "max_output_tokens": params.max_tokens,
    }
    if params.seed is not None:
        config_kwargs["seed"] = params.seed             # Vertex supports a sampling seed
    if params.stop:
        config_kwargs["stop_sequences"] = list(params.stop)
    # Gemini 2.5 "thinking" models spend output tokens on hidden reasoning. For this
    # bounded scoring task we want the budget on the answer: Flash / Flash-Lite let us
    # turn thinking off (budget 0); Pro can't disable it (budget must be >= 128), so we
    # cap it low and leave output headroom so the short answer isn't truncated.
    if model.startswith("gemini-2.5-flash"):
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    elif model.startswith("gemini-2.5-pro"):
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=128)
        config_kwargs["max_output_tokens"] = max(params.max_tokens, 512)

    started = time.perf_counter()
    response = client.models.generate_content(
        model=model, contents=prompt, config=types.GenerateContentConfig(**config_kwargs),
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    return EngineResponse(
        text=_gemini_text(response),
        model=getattr(response, "model_version", None) or model,
        finish_reason=_gemini_finish(response),
        usage=_gemini_usage(getattr(response, "usage_metadata", None)),
        raw={"response_id": getattr(response, "response_id", None)},
        latency_ms=latency_ms,
        metadata={
            "deterministic": False,
            "provider": "vertex",
            "project": project,
            "region": region,
        },
    )


def _gemini_text(response) -> str:
    """Concatenate text parts. ``response.text`` can raise/return None if a candidate
    was blocked or carries no text, so fall back to walking the candidate parts."""
    try:
        text = response.text
    except Exception:
        text = None
    if text:
        return text
    parts_text = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            piece = getattr(part, "text", None)
            if piece:
                parts_text.append(piece)
    return "".join(parts_text)


def _gemini_usage(usage) -> dict | None:
    if usage is None:
        return None
    out = {}
    for ours, theirs in (("input_tokens", "prompt_token_count"),
                         ("output_tokens", "candidates_token_count"),
                         ("total_tokens", "total_token_count"),
                         ("thoughts_tokens", "thoughts_token_count")):
        value = getattr(usage, theirs, None)
        if value is not None:
            out[ours] = value
    return out or None


def _gemini_finish(response) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    return getattr(reason, "name", None) or str(reason)


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
            "models": [dict(m) for m in ANTHROPIC_MODELS],
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
        self._client = anthropic.Anthropic(api_key=self.api_key, timeout=_REQUEST_TIMEOUT_S)
        return self._client

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        return _messages_complete(self._get_client(), self.model, system, prompt,
                                  params or EngineParams(), provider="anthropic")


class VertexEngine:
    """Google Gemini on GCP Vertex AI via the ``google-genai`` SDK
    (docs/setup/google-vertex-signup.md).

    Authentication uses Application Default Credentials — run
    ``gcloud auth application-default login`` once (user) or set
    ``GOOGLE_APPLICATION_CREDENTIALS`` to a service-account key (server). No API key.
    """

    name = "vertex"

    def __init__(self, *, project: str | None = None, region: str | None = None,
                 model: str | None = None, client=None, **kwargs):
        self.project = project or os.environ.get("DEVSECBUDDY_VERTEX_PROJECT") \
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.region = region or os.environ.get("DEVSECBUDDY_VERTEX_REGION") \
            or os.environ.get("GOOGLE_CLOUD_REGION") \
            or os.environ.get("CLOUD_ML_REGION", "us-central1")
        self.model = model or os.environ.get("DEVSECBUDDY_VERTEX_MODEL", GEMINI_DEFAULT_MODEL)
        self._client = client
        self._config = kwargs

    def configured(self) -> bool:
        # ADC is picked up by the SDK at call time; project+region are what we can
        # check up front. complete() raises EngineNotConfigured if creds are missing.
        return bool(self.project and self.region) or self._client is not None

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider": "Google Vertex AI (Gemini)",
            "deterministic": False,
            "implemented": True,
            "configured": self.configured(),
            "model": self.model,
            "models": [dict(m) for m in GEMINI_MODELS],
            "project": self.project,
            "region": self.region,
            "requires": ["a GCP project + region", "the Vertex AI API enabled",
                         "Application Default Credentials (gcloud auth application-default login)",
                         "the google-genai SDK"],
            "roadmap": "M6",
        }

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:
            raise EngineNotConfigured(
                "the 'google-genai' SDK is not installed — `pip install google-genai` "
                "(or `pip install -e .[vertex]`)."
            ) from exc
        if not (self.project and self.region):
            raise EngineNotConfigured(
                "DEVSECBUDDY_VERTEX_PROJECT and DEVSECBUDDY_VERTEX_REGION are required — "
                "see docs/setup/google-vertex-signup.md."
            )
        from google.genai import types
        self._client = genai.Client(
            vertexai=True, project=self.project, location=self.region,
            http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),  # ms; bound a hung call
        )
        return self._client

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        return _gemini_complete(self._get_client(), self.model, system, prompt,
                                params or EngineParams(), self.project, self.region)


# --- Gemini via a URL-based API gateway (urllib, no SDK) ----------------------

# Defaults for the gateway. The base URL is deployment-internal (and this repo is public),
# so it has *no* default — it must come from the environment. The URL *paths* below are
# generic API routes (not secrets) and are safe to default; override them per deployment.
GEMINI_GATEWAY_DEFAULTS = {
    "api_key_header": "x-api-key",          # GEMINI_API_KEY_HEADER
    "prompt_path": "/api/v1/gemini/prompt",  # GEMINI_PROMPT_URL
    "location": "us-central1",               # GEMINI_LOCATION
    "model": GEMINI_DEFAULT_MODEL,           # GEMINI_MODEL_NAME
    "timeout_s": 60.0,                       # GEMINI_TIMEOUT_SECONDS
    "cost_tag_path": "/api/v1/tag",          # GEMINI_CUSTOM_COST_TAG_URL
}


def _gateway_text(body: str) -> tuple[str, dict | None]:
    """Pull the model's text out of the gateway's JSON response. The gateway's envelope
    isn't pinned by a public spec, so try the common shapes and fall back to the raw body
    (so a ``SCORE: NN/100`` line is still parseable even from an unexpected wrapper)."""
    import json

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body, None
    if isinstance(data, str):
        return data, None
    if not isinstance(data, dict):
        return body, None
    # standard Gemini generateContent envelope: candidates[].content.parts[].text
    for cand in data.get("candidates") or []:
        parts = ((cand or {}).get("content") or {}).get("parts") or []
        joined = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if joined:
            return joined, data
    # flat fields a gateway might use
    for key in ("text", "response", "output", "completion", "content", "result", "answer", "message"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val, data
    # one level of nesting, e.g. {"response": {"text": ...}}
    for key in ("response", "result", "data", "prediction"):
        inner = data.get(key)
        if isinstance(inner, dict):
            for k2 in ("text", "output", "content", "completion", "answer"):
                if isinstance(inner.get(k2), str) and inner[k2]:
                    return inner[k2], data
    return body, data


class GeminiProxyEngine:
    """Google Gemini via a URL-based API gateway (API key in a header), as opposed to
    Vertex's gcloud/ADC auth. Talks plain HTTP with ``urllib`` — no vendor SDK.

    Config (env, ``GEMINI_*``): ``GEMINI_BASE_URL`` (required, deployment-internal — no
    default), ``GEMINI_API_KEY`` (blank by default), ``GEMINI_API_KEY_HEADER``,
    ``GEMINI_PROMPT_URL``, ``GEMINI_LOCATION``, ``GEMINI_MODEL_NAME``,
    ``GEMINI_TIMEOUT_SECONDS``. Gateway-specific extras (``GEMINI_CUSTOM_*``, optional):
    ``GEMINI_CUSTOM_COST_TAG`` (a cost-attribution tag; when set it is registered once and
    sent with each prompt) and ``GEMINI_CUSTOM_COST_TAG_URL`` (where to register it).
    """

    name = "gemini"

    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, location: str | None = None,
                 api_key_header: str | None = None, prompt_path: str | None = None,
                 timeout_s: float | None = None, cost_tag: str | None = None,
                 cost_tag_path: str | None = None, transport=None, **kwargs):
        env = os.environ.get
        d = GEMINI_GATEWAY_DEFAULTS
        # --- standard gateway config (GEMINI_*) ---
        self.base_url = (base_url if base_url is not None else env("GEMINI_BASE_URL", "")).rstrip("/")
        self.api_key = api_key if api_key is not None else env("GEMINI_API_KEY", "")
        self.api_key_header = api_key_header or env("GEMINI_API_KEY_HEADER") or d["api_key_header"]
        self.model = model or env("GEMINI_MODEL_NAME") or d["model"]
        self.location = location or env("GEMINI_LOCATION") or d["location"]
        self.prompt_path = prompt_path or env("GEMINI_PROMPT_URL") or d["prompt_path"]
        self.timeout_s = float(
            timeout_s if timeout_s is not None else (env("GEMINI_TIMEOUT_SECONDS") or d["timeout_s"])
        )
        # --- gateway-specific extras (GEMINI_CUSTOM_*), optional ---
        self.cost_tag = cost_tag if cost_tag is not None else env("GEMINI_CUSTOM_COST_TAG", "")
        self.cost_tag_path = cost_tag_path or env("GEMINI_CUSTOM_COST_TAG_URL") or d["cost_tag_path"]
        # injectable HTTP for tests: (url, headers, payload, timeout_s) -> (status, body_text)
        self._transport = transport
        self._cost_tag_ready = False
        self._config = kwargs

    def configured(self) -> bool:
        return bool(self.base_url and self.api_key) or self._transport is not None

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider": "Google Gemini (API gateway)",
            "deterministic": False,
            "implemented": True,
            "configured": self.configured(),
            "model": self.model,
            "models": [dict(m) for m in GEMINI_MODELS],
            "location": self.location,
            "requires": ["GEMINI_BASE_URL", "GEMINI_API_KEY (in the GEMINI_API_KEY_HEADER header)"],
            "roadmap": "M6",
        }

    # -- HTTP -------------------------------------------------------------------
    def _headers(self) -> dict:
        return {"content-type": "application/json", self.api_key_header: self.api_key}

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):  # allow a full URL override
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def _post_json(self, path: str, payload: dict) -> tuple[int, str]:
        """POST JSON and return (status, body_text). Raises urllib HTTPError on 4xx/5xx —
        whose ``.code`` the rate-limit wrapper reads to detect a 429."""
        if self._transport is not None:
            return self._transport(self._url(path), self._headers(), payload, self.timeout_s)
        import json
        from urllib import request

        req = request.Request(
            self._url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_s) as response:  # noqa: S310 (config'd URL)
            return response.status, response.read().decode("utf-8")

    def _ensure_cost_tag(self) -> None:
        """Register the cost tag once per process (idempotent — an 'already exists'
        response is fine). No-op when no cost tag is configured."""
        if not self.cost_tag or self._cost_tag_ready:
            return
        from urllib import error

        try:
            self._post_json(self.cost_tag_path, {"cost_tag": self.cost_tag})
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
            if "already exists" not in body.lower():
                raise EngineNotConfigured(
                    f"cost-tag registration failed ({exc.code}) at {self.cost_tag_path}: "
                    f"{body[:200]}"
                ) from exc
        self._cost_tag_ready = True

    def complete(self, system: str, prompt: str, params: EngineParams | None = None) -> EngineResponse:
        if not self.configured():
            raise EngineNotConfigured(
                "GEMINI_BASE_URL and GEMINI_API_KEY are required — see "
                "docs/setup/google-gemini-gateway.md."
            )
        params = params or EngineParams()
        model = (params.extra or {}).get("model", self.model)  # optional per-request override
        self._ensure_cost_tag()

        # The gateway takes a single prompt (no separate system field), so fold the rubric in.
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload: dict = {"prompt": full_prompt, "model_name": model, "location": self.location}
        if self.cost_tag:
            payload["cost_tag"] = self.cost_tag

        started = time.perf_counter()
        status, body = self._post_json(self.prompt_path, payload)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        text, _data = _gateway_text(body)
        return EngineResponse(
            text=text,
            model=model,
            finish_reason=None,
            usage=None,
            raw={"status": status, "body": body[:2000]},  # body preview aids first-run debugging
            latency_ms=latency_ms,
            metadata={
                "deterministic": False,
                "provider": "gemini",
                "location": self.location,
                "http_status": status,
            },
        )
