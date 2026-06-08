"""M6 cloud-engine tests — request mapping, response parsing, sampling guard, and
the not-configured error path, all with a mocked Anthropic SDK client (no network,
no keys). The live smoke test happens once real credentials exist.
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


def test_vertex_engine_shares_the_messages_mapping():
    client = _FakeClient()
    engine = VertexEngine(client=client, project="proj", region="us-east5",
                          model="claude-haiku-4-5")
    resp = engine.complete("s", "p")
    assert resp.metadata["provider"] == "vertex"
    assert client.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    info = engine.info()
    assert info["implemented"] is True and info["configured"] is True
    assert info["project"] == "proj" and info["region"] == "us-east5"


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
