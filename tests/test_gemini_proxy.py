"""GeminiProxyEngine — the URL/API-key gateway path to Gemini (no SDK, urllib)."""
import io
import os
import ssl
from urllib.error import HTTPError

import pytest

from devsecbuddy import GeminiProxyEngine, get_engine
from devsecbuddy.engines import EngineNotConfigured, is_rate_limit_error
from devsecbuddy.models import EngineParams


class _Transport:
    """Records POSTs and returns scripted (status, body) per path; the cost-tag endpoint
    can be told to raise an HTTPError to exercise the registration paths."""

    def __init__(self, prompt_body='{"text": "SCORE: 64/100\\nSolid."}', tag_body="{}", tag_exc=None):
        self.calls: list[dict] = []
        self._prompt_body = prompt_body
        self._tag_body = tag_body
        self._tag_exc = tag_exc

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        if url.endswith("/api/v1/tag"):
            if self._tag_exc is not None:
                raise self._tag_exc
            return 200, self._tag_body
        return 200, self._prompt_body

    def of(self, suffix):
        return [c for c in self.calls if c["url"].endswith(suffix)]


def _engine(transport=None, **kw):
    return GeminiProxyEngine(base_url="https://gw.internal", api_key="key-xyz",
                             transport=transport, **kw)


def _http_error(code, body=b""):
    return HTTPError("https://gw.internal/api/v1/tag", code, "err", {}, io.BytesIO(body))


def test_complete_builds_gateway_payload_and_extracts_text():
    t = _Transport()
    eng = _engine(t, cost_tag="ai-safety-test")
    r = eng.complete("RUBRIC: 0-100.", "Resume: Jane.",
                     EngineParams(extra={"model": "gemini-2.5-flash"}))
    assert r.text == "SCORE: 64/100\nSolid."
    assert r.metadata["provider"] == "gemini" and r.metadata["http_status"] == 200
    p = t.of("/api/v1/gemini/prompt")[0]
    assert p["url"] == "https://gw.internal/api/v1/gemini/prompt"
    assert p["payload"] == {
        "prompt": "RUBRIC: 0-100.\n\nResume: Jane.",  # system rubric folded into the single prompt
        "model_name": "gemini-2.5-flash",             # per-request override via params.extra
        "location": "us-central1",
        "cost_tag": "ai-safety-test",
    }
    assert p["headers"]["x-api-key"] == "key-xyz"          # key carried in the configured header
    assert p["headers"]["content-type"] == "application/json"


def test_cost_tag_registered_once_then_cached():
    t = _Transport()
    eng = _engine(t, cost_tag="tagA")
    eng.complete("s", "a")
    eng.complete("s", "b")
    assert len(t.of("/api/v1/tag")) == 1                   # idempotent: one registration per process
    assert t.of("/api/v1/tag")[0]["payload"] == {"cost_tag": "tagA"}
    assert len(t.of("/api/v1/gemini/prompt")) == 2


def test_cost_tag_already_exists_is_tolerated():
    t = _Transport(tag_exc=_http_error(409, b'{"detail": "cost tag already exists"}'))
    eng = _engine(t, cost_tag="tagA")
    assert "64" in eng.complete("s", "a").text             # does not raise


def test_cost_tag_hard_failure_raises_engine_not_configured():
    t = _Transport(tag_exc=_http_error(500, b"boom"))
    eng = _engine(t, cost_tag="tagA")
    with pytest.raises(EngineNotConfigured):
        eng.complete("s", "a")


def test_no_cost_tag_skips_registration_and_payload():
    t = _Transport()
    eng = _engine(t)                                       # no cost tag configured
    eng.complete("s", "a")
    assert t.of("/api/v1/tag") == []
    assert "cost_tag" not in t.of("/api/v1/gemini/prompt")[0]["payload"]


@pytest.mark.parametrize("body,expected", [
    ('{"text": "hello"}', "hello"),
    ('{"candidates":[{"content":{"parts":[{"text":"abc"}]}}]}', "abc"),  # standard Gemini envelope
    ('{"response": {"text": "nested"}}', "nested"),
    ('"just a string"', "just a string"),
    ('definitely not json', "definitely not json"),       # fall back to the raw body
])
def test_text_extraction_handles_shapes(body, expected):
    assert _engine(_Transport(prompt_body=body)).complete("s", "a").text == expected


def test_configured_requires_base_url_and_key():
    assert GeminiProxyEngine(base_url="https://x", api_key="k").configured() is True
    assert GeminiProxyEngine(base_url="https://x", api_key="").configured() is False
    assert GeminiProxyEngine(base_url="", api_key="k").configured() is False


def test_complete_without_config_raises():
    with pytest.raises(EngineNotConfigured):
        GeminiProxyEngine(base_url="", api_key="").complete("s", "a")


def test_custom_header_and_path_overrides():
    t = _Transport()
    eng = GeminiProxyEngine(base_url="https://gw", api_key="k", transport=t,
                            api_key_header="authorization", prompt_path="/v2/score")
    eng.complete("s", "a")
    last = t.calls[-1]
    assert last["url"] == "https://gw/v2/score"
    assert last["headers"]["authorization"] == "k"


def test_reads_gemini_env_vars(monkeypatch):
    for k in ("BASE_URL", "API_KEY", "API_KEY_HEADER", "MODEL_NAME", "LOCATION",
              "TIMEOUT_SECONDS", "PROMPT_URL", "CUSTOM_COST_TAG", "CUSTOM_COST_TAG_URL"):
        monkeypatch.delenv(f"GEMINI_{k}", raising=False)
    monkeypatch.setenv("GEMINI_BASE_URL", "https://env.gw")
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    monkeypatch.setenv("GEMINI_API_KEY_HEADER", "x-internal-key")
    monkeypatch.setenv("GEMINI_MODEL_NAME", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_LOCATION", "europe-west1")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("GEMINI_CUSTOM_COST_TAG", "env-tag")
    eng = GeminiProxyEngine()
    assert (eng.base_url, eng.api_key, eng.api_key_header) == ("https://env.gw", "env-key", "x-internal-key")
    assert (eng.model, eng.location, eng.timeout_s, eng.cost_tag) == ("gemini-2.5-pro", "europe-west1", 12.0, "env-tag")


def test_registered_in_factory():
    eng = get_engine("gemini", base_url="https://x", api_key="k")
    assert isinstance(eng, GeminiProxyEngine) and eng.name == "gemini"


def test_gateway_429_is_detected_as_rate_limit():
    # a 429 from the gateway carries .code, which the rate-limit wrapper retries on;
    # a 403 (auth/quota-shaped text aside) is not retried.
    assert is_rate_limit_error(_http_error(429)) is True
    assert is_rate_limit_error(_http_error(403)) is False


def test_no_ca_bundle_uses_system_trust_store():
    assert GeminiProxyEngine(base_url="https://x", api_key="k")._ssl_context() is None


def test_ca_bundle_builds_and_caches_an_ssl_context():
    system_ca = ssl.get_default_verify_paths().cafile  # a real PEM bundle on disk to load
    if not system_ca or not os.path.exists(system_ca):
        pytest.skip("no system CA file available to use as a test bundle")
    eng = GeminiProxyEngine(base_url="https://x", api_key="k", ca_bundle=system_ca)
    ctx = eng._ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert eng._ssl_context() is ctx  # built once and cached


def test_unreadable_ca_bundle_raises_engine_not_configured(tmp_path):
    eng = GeminiProxyEngine(base_url="https://x", api_key="k",
                            ca_bundle=str(tmp_path / "does-not-exist.pem"))
    with pytest.raises(EngineNotConfigured):
        eng._ssl_context()


def test_ca_bundle_reads_gemini_custom_env(monkeypatch):
    monkeypatch.setenv("GEMINI_CUSTOM_CA_BUNDLE", "/etc/ssl/internal-ca.pem")
    assert GeminiProxyEngine(base_url="https://x", api_key="k").ca_bundle == "/etc/ssl/internal-ca.pem"
