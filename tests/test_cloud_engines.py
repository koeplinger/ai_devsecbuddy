"""M6 cloud-engine tests — request mapping, response parsing, sampling guard, and
the not-configured error path, with mocked SDK clients (no network, no keys):
``AnthropicEngine`` = Claude via the Anthropic Messages API; ``VertexEngine`` =
Gemini via the google-genai generate_content API. Live smoke tests happen once real
credentials exist.
"""
from __future__ import annotations

import pytest

from devsecbuddy import AnthropicEngine, VertexEngine, get_engine
from devsecbuddy.engines import EngineNotConfigured
from devsecbuddy.models import EngineParams


# -- a minimal stand-in for the anthropic Messages client ----------------------

class _FakeUsage:
    input_tokens = 120
    output_tokens = 18
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]
        self.model = "claude-haiku-4-5"
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()
        self.id = "msg_123"
        self._request_id = "req_abc"


class _FakeMessages:
    def __init__(self, calls):
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return _FakeResponse("SCORE: 64/100\nSolid candidate.")


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = _FakeMessages(self.calls)


# -- a minimal stand-in for the google-genai Vertex client ---------------------

class _FakeGeminiUsage:
    prompt_token_count = 100
    candidates_token_count = 12
    total_token_count = 112
    thoughts_token_count = 0


class _FakeFinishReason:
    name = "STOP"


class _FakeGeminiCandidate:
    finish_reason = _FakeFinishReason()
    content = None


class _FakeGeminiResponse:
    def __init__(self, text):
        self.text = text
        self.model_version = "gemini-2.5-flash"
        self.response_id = "resp_1"
        self.usage_metadata = _FakeGeminiUsage()
        self.candidates = [_FakeGeminiCandidate()]


class _FakeGeminiModels:
    def __init__(self, calls):
        self._calls = calls

    def generate_content(self, **kwargs):
        self._calls.append(kwargs)
        return _FakeGeminiResponse("SCORE: 71/100\nStrong match.")


class _FakeGeminiClient:
    def __init__(self):
        self.calls = []
        self.models = _FakeGeminiModels(self.calls)


# -- tests ---------------------------------------------------------------------

def test_anthropic_engine_maps_request_and_response():
    client = _FakeClient()
    engine = AnthropicEngine(client=client, api_key="x", model="claude-haiku-4-5")
    resp = engine.complete("RUBRIC system", "Applicant name: Jordan Lee\nResume: ...",
                           EngineParams(max_tokens=200, temperature=0.0))

    req = client.calls[0]
    assert req["model"] == "claude-haiku-4-5"
    assert req["max_tokens"] == 200
    assert req["system"][0]["text"] == "RUBRIC system"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}   # stable prefix cached
    assert req["messages"] == [{"role": "user", "content": "Applicant name: Jordan Lee\nResume: ..."}]
    assert req["temperature"] == 0.0   # Haiku accepts sampling params
    assert "stop_sequences" not in req  # none requested

    assert resp.text.startswith("SCORE:")
    assert resp.model == "claude-haiku-4-5"
    assert resp.finish_reason == "end_turn"
    assert resp.usage["input_tokens"] == 120 and resp.usage["output_tokens"] == 18
    assert resp.metadata["deterministic"] is False
    assert resp.metadata["provider"] == "anthropic"
    assert resp.metadata["request_id"] == "req_abc"
    assert resp.metadata["cache_read_input_tokens"] == 0
    assert engine.info()["implemented"] is True and engine.info()["configured"] is True


def test_sampling_params_dropped_for_opus_4_7_plus():
    client = _FakeClient()
    AnthropicEngine(client=client, model="claude-opus-4-8").complete("s", "p")
    assert "temperature" not in client.calls[0]   # Opus 4.7/4.8 reject sampling params


def test_vertex_engine_maps_gemini_request_and_response():
    pytest.importorskip("google.genai")  # config is built with the real google-genai types
    client = _FakeGeminiClient()
    engine = VertexEngine(client=client, project="devsecbuddy", region="us-east1",
                          model="gemini-2.5-flash")
    resp = engine.complete("RUBRIC system", "Applicant name: Jordan Lee\nResume: ...",
                           EngineParams(max_tokens=200, temperature=0.0, stop=["END"]))

    call = client.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"] == "Applicant name: Jordan Lee\nResume: ..."
    cfg = call["config"]
    assert cfg.system_instruction == "RUBRIC system"     # system prompt -> system_instruction
    assert cfg.max_output_tokens == 200
    assert cfg.temperature == 0.0
    assert list(cfg.stop_sequences) == ["END"]
    assert cfg.thinking_config.thinking_budget == 0       # thinking disabled for the 2.5 model

    assert resp.text.startswith("SCORE:")
    assert resp.model == "gemini-2.5-flash"
    assert resp.finish_reason == "STOP"
    assert resp.usage["input_tokens"] == 100 and resp.usage["output_tokens"] == 12
    assert resp.metadata["deterministic"] is False
    assert resp.metadata["provider"] == "vertex"
    assert resp.metadata["project"] == "devsecbuddy" and resp.metadata["region"] == "us-east1"
    info = engine.info()
    assert info["implemented"] is True and info["configured"] is True
    assert info["provider"] == "Google Vertex AI (Gemini)" and info["model"] == "gemini-2.5-flash"


def test_vertex_model_override_and_thinking_only_on_2_5():
    pytest.importorskip("google.genai")
    client = _FakeGeminiClient()
    VertexEngine(client=client, project="p", region="us-central1").complete(
        "s", "p", EngineParams(extra={"model": "gemini-2.0-flash"}))
    call = client.calls[0]
    assert call["model"] == "gemini-2.0-flash"     # EngineParams.extra["model"] overrides
    assert call["config"].thinking_config is None  # thinking_config only set for gemini-2.5*


def test_vertex_pro_keeps_thinking_with_output_headroom():
    pytest.importorskip("google.genai")
    client = _FakeGeminiClient()
    VertexEngine(client=client, project="p", region="us-east1", model="gemini-2.5-pro").complete(
        "s", "p", EngineParams(max_tokens=256))
    cfg = client.calls[0]["config"]
    assert cfg.thinking_config.thinking_budget == 128   # Pro can't disable thinking (>= 128)
    assert cfg.max_output_tokens >= 512                  # headroom so the short answer survives


def test_engine_model_catalogs_expose_low_mid_high_tiers():
    a = {m["tier"]: m["id"] for m in AnthropicEngine().info()["models"]}
    assert a == {"low": "claude-haiku-4-5", "mid": "claude-sonnet-4-6", "high": "claude-opus-4-8"}
    v = {m["tier"]: m["id"] for m in VertexEngine().info()["models"]}
    assert set(v) == {"low", "mid", "high"} and v["high"] == "gemini-2.5-pro"
    # a selected model is honored and reflected by info() (-> recorded on the finding)
    assert AnthropicEngine(model="claude-opus-4-8").info()["model"] == "claude-opus-4-8"
    assert VertexEngine(model="gemini-2.5-pro").info()["model"] == "gemini-2.5-pro"


def test_unconfigured_engines_raise_clear_error():
    # no injected client, no SDK/credentials in this env -> EngineNotConfigured (not a 500)
    with pytest.raises(EngineNotConfigured):
        AnthropicEngine(api_key=None, model="claude-haiku-4-5").complete("s", "p")
    with pytest.raises(EngineNotConfigured):
        VertexEngine(project=None, region=None).complete("s", "p")


def test_get_engine_resolves_cloud_engines():
    assert get_engine("anthropic").name == "anthropic"
    assert get_engine("vertex").name == "vertex"
    assert get_engine().name == "mock"


def test_stop_sequences_and_per_request_model_override():
    client = _FakeClient()
    AnthropicEngine(client=client, api_key="x", model="claude-haiku-4-5").complete(
        "s", "p", EngineParams(stop=["END"], extra={"model": "claude-sonnet-4-6"}))
    req = client.calls[0]
    assert req["stop_sequences"] == ["END"]
    assert req["model"] == "claude-sonnet-4-6"   # EngineParams.extra["model"] overrides
    assert req["temperature"] == 0.0             # sonnet still accepts sampling params
