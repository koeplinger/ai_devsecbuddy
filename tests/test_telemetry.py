"""AI-model-call telemetry: aggregates + EMAs, the engine wrapper, and the /telemetry endpoint."""
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.telemetry import CallTelemetry, TelemetryEngine
from devsecbuddy.models import EngineResponse


def test_call_telemetry_aggregates_count_total_avg_and_emas():
    t = CallTelemetry()
    empty = t.snapshot()
    assert empty["count"] == 0 and empty["avg_ms"] is None and empty["ema_90_ms"] is None

    for v in (100.0, 200.0, 300.0):
        t.record(v, "vertex", "gemini-2.5-flash")
    s = t.snapshot()
    assert s["count"] == 3 and s["total_ms"] == 600.0 and s["avg_ms"] == 200.0
    # 90%-prior EMA (alpha .1): 100 -> .9*100+.1*200=110 -> .9*110+.1*300=129
    assert s["ema_90_ms"] == 129.0
    # 70%-prior EMA (alpha .3): 100 -> .7*100+.3*200=130 -> .7*130+.3*300=181
    assert s["ema_70_ms"] == 181.0
    assert s["last_ms"] == 300.0
    assert s["last_engine"] == "vertex" and s["last_model"] == "gemini-2.5-flash"


class _Eng:
    name = "fake"

    def __init__(self, boom=False):
        self.boom = boom
        self.calls = 0

    def complete(self, system, prompt, params=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("kaboom")
        return EngineResponse(text="ok", model="fake-model-1")

    def info(self):
        return {"name": self.name, "model": "fake-model-1"}


def test_telemetry_engine_records_each_complete_and_delegates():
    t = CallTelemetry()
    eng = _Eng()
    wrapped = TelemetryEngine(eng, t)
    assert wrapped.complete("sys", "prompt").text == "ok"   # transparent passthrough
    assert wrapped.name == "fake" and wrapped.info()["model"] == "fake-model-1"  # delegates attrs
    s = t.snapshot()
    assert s["count"] == 1 and s["last_engine"] == "fake" and s["last_model"] == "fake-model-1"
    assert s["last_ms"] is not None and s["last_ms"] >= 0.0


def test_telemetry_engine_does_not_record_a_failed_call():
    t = CallTelemetry()
    wrapped = TelemetryEngine(_Eng(boom=True), t)
    with pytest.raises(RuntimeError):
        wrapped.complete("s", "p")
    assert t.snapshot()["count"] == 0  # an errored call is not an AI model call


def test_telemetry_endpoint_tracks_calls_across_a_run():
    app = create_app(Settings(db_path=tempfile.mktemp(suffix=".db"), engine="mock"))
    client = TestClient(app)
    before = client.get("/telemetry").json()
    assert before["count"] == 0 and before["avg_ms"] is None
    assert client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock"}).status_code == 201
    after = client.get("/telemetry").json()
    assert after["count"] > before["count"]
    assert after["last_engine"] == "mock" and after["last_model"] == "mock-resume-scorer-1"
    assert after["avg_ms"] is not None and after["ema_90_ms"] is not None and after["ema_70_ms"] is not None
