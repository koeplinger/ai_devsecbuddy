"""M2 API tests — the FastAPI run/report endpoints over a temp ledger.

The headline test confirms the run endpoint reproduces the docs/tiles.md divergence
through HTTP, and the report endpoints serve the persisted findings.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "ledger.db"), engine="mock"))
    return TestClient(app)


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


def test_engines_reports_mock_default_and_unwired_cloud(client):
    engines = {e["name"]: e for e in client.get("/engines").json()}
    assert engines["mock"]["implemented"] is True and engines["mock"]["default"] is True
    assert engines["anthropic"]["implemented"] is False
    assert engines["vertex"]["implemented"] is False


def test_run_unguarded_reproduces_full_profile(client):
    resp = client.post("/runs", json={"tile_id": "tile-unguarded"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["engine_name"] == "mock"
    assert body["summary"]["vulnerabilities_found"] == 3
    cats = {f["category"] for f in body["findings"]}
    assert cats == {"prompt_injection", "data_exfiltration", "bias_fairness"}


def test_run_hardened_is_clean(client):
    body = client.post("/runs", json={"tile_id": "tile-hardened"}).json()
    assert body["summary"]["vulnerabilities_found"] == 0
    assert body["findings"] == []


def test_run_unknown_tile_404(client):
    assert client.post("/runs", json={"tile_id": "tile-nope"}).status_code == 404


def test_run_unwired_engine_501(client):
    resp = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "anthropic"})
    assert resp.status_code == 501
    assert "M6" in resp.json()["detail"] or "not wired" in resp.json()["detail"].lower()


def test_run_unknown_engine_400(client):
    # a typo'd / nonexistent engine name is a client error, not 501 not-implemented
    resp = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "gpt4"})
    assert resp.status_code == 400


def test_reports_list_runs_and_findings(client):
    run = client.post("/runs", json={"tile_id": "tile-unguarded"}).json()
    run_id = run["run_id"]

    runs = client.get("/runs").json()
    assert any(r["run_id"] == run_id and r["status"] == "completed" for r in runs)

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["engine_name"] == "mock"
    assert len(detail["findings"]) == 3

    highs = client.get("/findings", params={"tile_id": "tile-unguarded", "severity": "high"}).json()
    assert len(highs) == 2  # injection + bias

    finding_id = highs[0]["id"]
    full = client.get(f"/findings/{finding_id}").json()
    assert full["mitigation_guidance"]
    assert "request" in full["repro"] and "response" in full["evidence"]

    assert client.get("/runs/run-does-not-exist").status_code == 404
    assert client.get("/findings/find-does-not-exist").status_code == 404
