"""Run durability: a run's event log lives in the backend (not the stream), so a refreshed /
new client can list active+recent runs and reconnect (replay the log, then tail)."""
import json
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.service import AssessmentService, RunNotActive, RunNotFound


def _service():
    return AssessmentService(db_path=tempfile.mktemp(suffix=".db"), default_engine="mock")


def _run(svc, tile="tile-unguarded"):
    """Drive one streaming assessment to completion (consuming the generator tails until done)."""
    return [json.loads(line) for line in svc.run_stream(tile, "mock", None)]


# ---- endpoint behavior (TestClient) -----------------------------------------

def test_active_runs_and_attach_replay_via_http():
    client = TestClient(create_app(Settings(db_path=tempfile.mktemp(suffix=".db"), engine="mock")))
    ev = []
    with client.stream("POST", "/runs/stream", json={"tile_id": "tile-unguarded", "engine_name": "mock"}) as r:
        for line in r.iter_lines():
            if line:
                ev.append(json.loads(line))
    job_id = ev[0]["id"]

    active = client.get("/runs/active").json()
    assert len(active) == 1
    a = active[0]
    assert a["tile_id"] == "tile-unguarded" and a["status"] == "done"
    assert a["job_id"] == job_id and a["engine"] == "mock" and a["tile_name"]

    # reconnecting replays the WHOLE log of the finished run, then ends
    replay = []
    with client.stream("GET", f"/runs/{job_id}/stream") as r:
        for line in r.iter_lines():
            if line:
                replay.append(json.loads(line))
    assert [e["type"] for e in replay] == [e["type"] for e in ev]
    assert replay[0]["type"] == "queued" and replay[-1]["type"] == "result"

    assert client.get("/runs/job-nope/stream").status_code == 404


# ---- service contract --------------------------------------------------------

def test_finished_run_is_retained_and_attachable():
    svc = _service()
    try:
        _run(svc)
        job_id = svc.active_runs()[0]["job_id"]
        replay = [json.loads(s) for s in svc.attach_stream(job_id)]   # replays + ends (job is done)
        assert replay[0]["type"] == "queued" and replay[-1]["type"] == "result"
        with pytest.raises(RunNotFound):
            list(svc.attach_stream("job-missing"))
    finally:
        svc.close()


def test_active_runs_keeps_only_the_latest_job_per_tile():
    svc = _service()
    try:
        _run(svc)                                # run 1 of the tile
        active1 = svc.active_runs()
        first_id = active1[0]["job_id"]
        _run(svc)                                # run 2 of the SAME tile
        active2 = svc.active_runs()
        tile_runs = [a for a in active2 if a["tile_id"] == "tile-unguarded"]
        assert len(tile_runs) == 1                            # only the latest is kept
        assert tile_runs[0]["job_id"] != first_id            # ...and it's the newer run
        with pytest.raises(RunNotFound):                     # the older run was pruned
            list(svc.attach_stream(first_id))
    finally:
        svc.close()


def test_tile_is_freed_before_the_terminal_event_is_observable():
    # Regression guard (the cleanup-after-terminal bug): a client that has just consumed the
    # terminal event must see consistent state — the tile is already freed (immediately
    # re-runnable), never still reported in flight.
    svc = _service()
    try:
        for _ in range(30):
            list(svc.run_stream("tile-unguarded", "mock", None))   # drain to completion
            assert "tile-unguarded" not in svc.running_tiles()     # freed when the stream ended
    finally:
        svc.close()


def test_cancel_rejects_a_finished_run():
    svc = _service()
    try:
        _run(svc)
        job_id = svc.active_runs()[0]["job_id"]
        with pytest.raises(RunNotActive):                    # done -> not cancelable
            svc.cancel_run(job_id)
    finally:
        svc.close()
