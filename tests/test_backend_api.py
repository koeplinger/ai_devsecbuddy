"""M2 API tests — the FastAPI run/report endpoints over a temp ledger.

The headline test confirms the run endpoint reproduces the docs/tiles.md divergence
through HTTP, and the report endpoints serve the persisted findings.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.service import AssessmentService, TileBusy


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "ledger.db"), engine="mock"))
    return TestClient(app)


def _stream_events(client, payload) -> list[dict]:
    """POST /runs/stream and collect the NDJSON events."""
    events: list[dict] = []
    with client.stream("POST", "/runs/stream", json=payload) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        for line in resp.iter_lines():
            if line:
                events.append(json.loads(line))
    return events


def test_health_and_root(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "/runs" in client.get("/").json()["endpoints"]


def test_tiles_lists_the_four_reference_tiles(client):
    tiles = client.get("/tiles").json()
    ids = {t["tile_id"] for t in tiles}
    assert {"tile-unguarded", "tile-input-sanitized", "tile-fairness-aware", "tile-hardened"} <= ids
    unguarded = next(t for t in tiles if t["tile_id"] == "tile-unguarded")
    assert unguarded["input_fields"] == ["applicant_name", "resume_text"]
    assert "guardrails" in unguarded


def test_engines_reports_mock_default_and_cloud_implemented_unconfigured(client):
    engines = {e["name"]: e for e in client.get("/engines").json()}
    assert engines["mock"]["implemented"] is True and engines["mock"]["default"] is True
    assert engines["mock"]["configured"] is True
    # cloud engines are now implemented but unconfigured (no creds in this env)
    assert engines["anthropic"]["implemented"] is True
    assert engines["anthropic"]["configured"] is False
    assert engines["vertex"]["implemented"] is True
    assert engines["vertex"]["configured"] is False


def test_run_unguarded_reproduces_full_profile(client):
    resp = client.post("/runs", json={"tile_id": "tile-unguarded"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["engine_name"] == "mock"
    assert body["summary"]["vulnerabilities_found"] == 6
    cats = {f["category"] for f in body["findings"]}
    assert cats == {"prompt_injection", "modal_jailbreak", "data_exfiltration", "bias_fairness"}


def test_run_hardened_is_clean(client):
    body = client.post("/runs", json={"tile_id": "tile-hardened"}).json()
    assert body["summary"]["vulnerabilities_found"] == 0
    assert body["findings"] == []


def test_run_unknown_tile_404(client):
    assert client.post("/runs", json={"tile_id": "tile-nope"}).status_code == 404


def test_run_unconfigured_engine_503(client):
    # anthropic is implemented but has no SDK/key in this env -> a clear 503, not a 500
    resp = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "anthropic"})
    assert resp.status_code == 503
    assert "anthropic" in resp.json()["detail"].lower()


def test_run_unknown_engine_400(client):
    # a typo'd / nonexistent engine name is a client error, not 501 not-implemented
    resp = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "gpt4"})
    assert resp.status_code == 400


def test_run_stream_emits_progress_then_result(client):
    events = _stream_events(client, {"tile_id": "tile-unguarded", "engine_name": "mock"})
    types = [e["type"] for e in events]
    # lifecycle markers are present and ordered: start -> probes -> terminal result
    assert types[0] == "run_started"
    assert types[-1] == "result"
    assert "probe_started" in types and "probe_done" in types

    # the documented sequence (architecture.md §5.1): the three phases arrive in order
    # and baseline_done lands between the baseline and probing phases.
    assert [e["phase"] for e in events if e["type"] == "phase"] == ["baseline", "probing", "reporting"]
    assert "baseline_done" in types
    probing_at = next(i for i, e in enumerate(events) if e["type"] == "phase" and e["phase"] == "probing")
    assert types.index("baseline_done") < probing_at < types.index("probe_started")

    started = [e for e in events if e["type"] == "probe_started"]
    done = [e for e in events if e["type"] == "probe_done"]
    assert len(started) == 6 == len(done)            # one per enabled vector
    assert started[0]["total"] == 6 and started[0]["index"] == 1
    assert all("vector_id" in e and "category" in e for e in started)

    result = events[-1]
    assert result["engine_name"] == "mock"
    assert result["summary"]["vulnerabilities_found"] == 6
    assert len(result["findings"]) == 6
    cats = {f["category"] for f in result["findings"]}
    assert cats == {"prompt_injection", "modal_jailbreak", "data_exfiltration", "bias_fairness"}


def test_run_stream_emits_terminal_error_for_unconfigured_engine(client):
    # An engine that fails mid-run (anthropic has no creds in this env) cannot change
    # the HTTP status once streaming has begun, so it arrives as a terminal error event.
    events = _stream_events(client, {"tile_id": "tile-unguarded", "engine_name": "anthropic"})
    assert events[0]["type"] == "run_started"        # the run did start streaming
    assert events[-1]["type"] == "error"
    assert events[-1]["kind"] == "not_configured"
    assert events[-1]["message"]
    assert not any(e["type"] == "result" for e in events)


def test_run_stream_hardened_is_clean(client):
    events = _stream_events(client, {"tile_id": "tile-hardened", "engine_name": "mock"})
    result = events[-1]
    assert result["type"] == "result"
    assert result["summary"]["vulnerabilities_found"] == 0
    assert result["findings"] == []
    # every probe still ran — they just all passed
    assert all(e["success"] is False for e in events if e["type"] == "probe_done")


def test_run_stream_unknown_tile_404_and_engine_400(client):
    assert client.post("/runs/stream", json={"tile_id": "tile-nope"}).status_code == 404
    assert (
        client.post("/runs/stream", json={"tile_id": "tile-unguarded", "engine_name": "gpt4"}).status_code
        == 400
    )


def test_run_stream_one_live_run_per_tile(tmp_path):
    # The 409 guard is a service invariant; exercise it directly so it's deterministic
    # (the mock run is too fast to collide over HTTP). A reserved tile rejects a second
    # start; a different tile is unaffected.
    service = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    service._running.add("tile-unguarded")
    with pytest.raises(TileBusy):
        service.run_stream("tile-unguarded", "mock")
    # other tiles are independent
    other = service.run_stream("tile-hardened", "mock")
    list(other)  # drain so the worker finishes and releases the tile
    assert "tile-hardened" not in service.running_tiles()


def test_run_stream_releases_tile_on_early_close(tmp_path):
    # A client that disconnects mid-stream (closes the generator without draining)
    # must not leak the tile — the worker thread runs independently to completion and
    # releases it in its finally. Otherwise the tile is stuck at 409 forever.
    service = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    gen = service.run_stream("tile-unguarded", "mock")
    next(gen)            # pull one event, then "disconnect"
    gen.close()
    for _ in range(100):  # worker finishes async; poll briefly for release
        if "tile-unguarded" not in service.running_tiles():
            break
        time.sleep(0.02)
    assert service.running_tiles() == []


def test_findings_filter_by_engine(client):
    client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock"})
    on_mock = client.get("/findings", params={"engine": "mock"}).json()
    assert len(on_mock) == 6 and all(f["category"] for f in on_mock)
    # no findings were produced by any other engine in this ledger
    assert client.get("/findings", params={"engine": "anthropic"}).json() == []
    # engine combines with the existing column filters (severity lives on findings)
    high_mock = client.get("/findings", params={"engine": "mock", "severity": "high"}).json()
    assert len(high_mock) == 4


def test_findings_carry_engine_and_model(client):
    client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock"})
    findings = client.get("/findings").json()
    assert findings, "expected findings"
    # every finding (incl. bias, which has a different snapshot) carries engine + model
    assert all(f["engine"] == "mock" for f in findings)
    assert all(f["model"] == "mock-resume-scorer-1" for f in findings)
    assert any(f["category"] == "bias_fairness" for f in findings)


def test_delete_findings_removes_them_permanently(client):
    client.post("/runs", json={"tile_id": "tile-unguarded"})
    findings = client.get("/findings", params={"tile_id": "tile-unguarded"}).json()
    assert len(findings) == 6

    ids = [f["id"] for f in findings[:2]]
    resp = client.request("DELETE", "/findings", json={"ids": ids})
    assert resp.status_code == 200 and resp.json()["deleted"] == 2

    remaining = client.get("/findings", params={"tile_id": "tile-unguarded"}).json()
    assert len(remaining) == 4
    assert {f["id"] for f in remaining}.isdisjoint(ids)        # the right rows went

    # deleting the rest empties the ledger; empty / unknown ids are a safe no-op
    rest = [f["id"] for f in remaining]
    assert client.request("DELETE", "/findings", json={"ids": rest}).json()["deleted"] == 4
    assert client.get("/findings", params={"tile_id": "tile-unguarded"}).json() == []
    assert client.request("DELETE", "/findings", json={"ids": []}).json()["deleted"] == 0
    assert client.request("DELETE", "/findings", json={"ids": ["nope"]}).json()["deleted"] == 0


def test_reports_list_runs_and_findings(client):
    run = client.post("/runs", json={"tile_id": "tile-unguarded"}).json()
    run_id = run["run_id"]

    runs = client.get("/runs").json()
    assert any(r["run_id"] == run_id and r["status"] == "completed" for r in runs)

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["engine_name"] == "mock"
    assert len(detail["findings"]) == 6

    highs = client.get("/findings", params={"tile_id": "tile-unguarded", "severity": "high"}).json()
    assert len(highs) == 4  # 2x injection + jailbreak + bias (exfil is medium)

    finding_id = highs[0]["id"]
    full = client.get(f"/findings/{finding_id}").json()
    assert full["mitigation_guidance"]
    assert "request" in full["repro"] and "response" in full["evidence"]

    assert client.get("/runs/run-does-not-exist").status_code == 404
    assert client.get("/findings/find-does-not-exist").status_code == 404
