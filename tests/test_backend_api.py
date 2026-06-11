"""M2 API tests — the FastAPI run/report endpoints over a temp ledger.

The headline test confirms the run endpoint reproduces the docs/tiles.md divergence
through HTTP, and the report endpoints serve the persisted findings.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.service import AssessmentService, TileBusy
from devsecbuddy.demo import CLEAN_CORPUS


def _gated_run_assessment(release: threading.Event, started: list):
    """A drop-in for run_assessment that blocks until ``release`` (or until force-stopped
    via on_event), recording the order tiles actually start. Lets concurrency tests be
    deterministic without depending on a real run's timing."""
    def fake(adapter, vectors, corpus, ledger=None, engine_name="mock", on_event=None):
        started.append(adapter.tile_id)
        if on_event:                          # the sync run() path passes no on_event
            on_event({"type": "run_started", "run_id": "r", "tile_id": adapter.tile_id,
                      "engine_name": engine_name, "total_probes": 1})
        while not release.is_set():
            if on_event:
                on_event({"type": "tick"})    # raises RunCancelled if the job is force-stopped
            time.sleep(0.005)
        return {"run_id": "r-" + adapter.tile_id, "tile_id": adapter.tile_id, "findings": [],
                "summary": {"probes_run": 0, "vulnerabilities_found": 0, "probes_passed": 0,
                            "by_severity": {}, "by_category": {}}}
    return fake


def _wait(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "ledger.db"), engine="mock"))
    return TestClient(app)


def _make_pdf(text: str) -> bytes:
    """Build a minimal single-page PDF whose only content is `text` (for extract tests)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode() + b") Tj ET"
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref).encode() + b"\n%%EOF")
    return pdf


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


def test_engines_expose_model_catalogs(client):
    engines = {e["name"]: e for e in client.get("/engines").json()}
    a = engines["anthropic"]["models"]
    assert [m["id"] for m in a] == [  # ordered cheapest -> priciest; Fable 5 added; no tier
        "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8", "claude-fable-5"]
    assert all("tier" not in m for m in a)
    v = {m["id"] for m in engines["vertex"]["models"]}
    assert {"gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro",
            "gemini-3.1-flash-lite", "gemini-3-flash", "gemini-3.1-pro"} == v  # 2.5 kept + 3.x added
    # a catalog model is accepted; an unknown one is rejected up front with a clear 400
    ok = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock",
                                    "model": "mock-resume-scorer-1"})
    assert ok.status_code == 201
    bad = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock", "model": "nope"})
    assert bad.status_code == 400
    # model is validated against the engine's catalog *before* the configured/503 check
    bad2 = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "anthropic",
                                      "model": "claude-nope"})
    assert bad2.status_code == 400
    assert client.post("/runs/stream", json={"tile_id": "tile-unguarded", "engine_name": "mock",
                                             "model": "nope"}).status_code == 400


def test_run_unguarded_reproduces_full_profile(client):
    resp = client.post("/runs", json={"tile_id": "tile-unguarded"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["engine_name"] == "mock"
    assert body["summary"]["vulnerabilities_found"] == 7
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
    # lifecycle markers are present and ordered: queued -> run_started -> probes -> result
    assert types[0] == "queued"                      # serialized: first event carries the job id
    assert events[0]["id"].startswith("job-") and events[0]["position"] >= 1
    assert "run_started" in types
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
    assert len(started) == 7 == len(done)            # one per enabled vector
    assert started[0]["total"] == 7 and started[0]["index"] == 1
    assert all("vector_id" in e and "category" in e for e in started)
    # each completion carries the per-line verdict inputs: success / unscorable / detail
    assert all("success" in e and e["unscorable"] is False and "detail" in e for e in done)

    result = events[-1]
    assert result["engine_name"] == "mock"
    assert result["summary"]["vulnerabilities_found"] == 7
    assert len(result["findings"]) == 7
    cats = {f["category"] for f in result["findings"]}
    assert cats == {"prompt_injection", "modal_jailbreak", "data_exfiltration", "bias_fairness"}


def test_run_stream_emits_terminal_error_for_unconfigured_engine(client):
    # An engine that fails mid-run (anthropic has no creds in this env) cannot change
    # the HTTP status once streaming has begun, so it arrives as a terminal error event.
    events = _stream_events(client, {"tile_id": "tile-unguarded", "engine_name": "anthropic"})
    assert events[0]["type"] == "queued"             # enqueued, then the run started streaming
    assert any(e["type"] == "run_started" for e in events)
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


def test_run_stream_one_job_per_tile(tmp_path):
    # A tile that already has a job queued or running rejects a second start (409). A
    # different tile is accepted (it queues behind the first).
    service = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    with service._cv:
        service._tiles_in_flight.add("tile-unguarded")  # pretend a job is in flight
    with pytest.raises(TileBusy):
        service.run_stream("tile-unguarded", "mock")
    # a different tile is accepted; drain it so the worker finishes and releases the tile
    other = service.run_stream("tile-hardened", "mock")
    list(other)
    assert "tile-hardened" not in service.running_tiles()


def test_runs_are_serialized_one_at_a_time(tmp_path, monkeypatch):
    # Kick off two tiles at once: only ONE scorer runs; the other waits in the queue, and
    # runs only after the first finishes.
    release, started = threading.Event(), []
    monkeypatch.setattr("backend.service.run_assessment", _gated_run_assessment(release, started))
    svc = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    ga = svc.run_stream("tile-unguarded", "mock")  # FIFO: this one runs first
    gb = svc.run_stream("tile-hardened", "mock")   # this one queues
    assert _wait(lambda: started == ["tile-unguarded"])
    time.sleep(0.05)
    assert started == ["tile-unguarded"]           # the second has NOT started
    snap = svc.queue_snapshot()
    assert len(snap["pending"]) == 1 and set(snap["in_flight"]) == {"tile-unguarded", "tile-hardened"}

    release.set()                                  # let the first finish -> the second runs
    assert _wait(lambda: started == ["tile-unguarded", "tile-hardened"])
    list(ga); list(gb)                             # drain so worker threads wind down


def test_cancel_removes_a_queued_run(tmp_path, monkeypatch):
    release, started = threading.Event(), []
    monkeypatch.setattr("backend.service.run_assessment", _gated_run_assessment(release, started))
    svc = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    svc.run_stream("tile-unguarded", "mock")       # runs + blocks
    gb = svc.run_stream("tile-hardened", "mock")   # queued
    assert _wait(lambda: started == ["tile-unguarded"])

    job_b = svc.queue_snapshot()["pending"][0]
    assert svc.cancel_run(job_b)["state"] == "removed_from_queue"
    assert svc.queue_snapshot()["pending"] == [] and "tile-hardened" not in svc.running_tiles()
    evs = [json.loads(x) for x in gb]              # its stream ends with a 'cancelled' event
    assert evs[-1]["type"] == "cancelled" and evs[-1]["reason"] == "removed_from_queue"
    release.set()


def test_force_stop_a_running_run(tmp_path, monkeypatch):
    release, started = threading.Event(), []
    monkeypatch.setattr("backend.service.run_assessment", _gated_run_assessment(release, started))
    svc = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    ga = svc.run_stream("tile-unguarded", "mock")
    assert _wait(lambda: started == ["tile-unguarded"])

    with svc._cv:
        job_a = next(iter(svc._jobs))
    assert svc.cancel_run(job_a)["state"] == "stopping"
    evs = [json.loads(x) for x in ga]              # the run stops; stream ends with 'cancelled'
    assert evs[-1]["type"] == "cancelled" and evs[-1]["reason"] == "force_stopped"
    assert _wait(lambda: svc.running_tiles() == [])  # tile released


def test_cancel_unknown_job_is_404(client):
    assert client.post("/runs/nope-123/cancel").status_code == 404


def test_sync_run_serializes_with_streaming_worker(tmp_path, monkeypatch):
    # The synchronous run() (POST /runs) shares _run_lock with the streaming worker, so it
    # waits while a streaming run is executing — one scorer at a time across BOTH paths.
    release, started = threading.Event(), []
    monkeypatch.setattr("backend.service.run_assessment", _gated_run_assessment(release, started))
    svc = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    svc.run_stream("tile-unguarded", "mock")       # worker grabs _run_lock and blocks
    assert _wait(lambda: started == ["tile-unguarded"])

    done = threading.Event()
    threading.Thread(target=lambda: (svc.run("tile-hardened", "mock"), done.set()), daemon=True).start()
    time.sleep(0.1)
    assert started == ["tile-unguarded"] and not done.is_set()  # sync run() blocked on _run_lock
    release.set()                                  # release both
    assert _wait(lambda: done.is_set()) and "tile-hardened" in started


def test_close_retires_the_drain_worker(tmp_path):
    svc = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    list(svc.run_stream("tile-unguarded", "mock"))  # start + drain a run -> worker is alive/idle
    worker = svc._worker
    assert worker is not None and worker.is_alive()
    svc.close()
    assert _wait(lambda: not worker.is_alive())     # the idle worker exits cleanly


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
    assert len(on_mock) == 7 and all(f["category"] for f in on_mock)
    # no findings were produced by any other engine in this ledger
    assert client.get("/findings", params={"engine": "anthropic"}).json() == []
    # engine combines with the existing column filters (severity lives on findings). The
    # severity filter is exact, and injection/jailbreak/bias each land on high OR critical
    # depending on the random sample, so count the serious tier (everything but the two
    # medium data_exfiltration findings) = 5, which is deterministic.
    high_mock = client.get("/findings", params={"engine": "mock", "severity": "high"}).json()
    assert all(f["severity"] == "high" for f in high_mock)
    serious = [f for f in on_mock if f["severity"] in ("high", "critical")]
    assert len(serious) == 5  # 2x injection + jailbreak + 2x bias (exfil x2 is medium)


def test_findings_filter_by_model(client):
    client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock"})
    # model lives in the finding's repro JSON; the filter matches it post-query
    on_model = client.get("/findings", params={"model": "mock-resume-scorer-1"}).json()
    assert len(on_model) == 7
    assert client.get("/findings", params={"model": "gemini-2.5-pro"}).json() == []
    # model combines with engine + column filters
    combined = client.get("/findings", params={"engine": "mock", "model": "mock-resume-scorer-1",
                                               "severity": "high"}).json()
    assert all(f["severity"] == "high" and f["category"] for f in combined)
    serious = [f for f in on_model if f["severity"] in ("high", "critical")]
    assert len(serious) == 5


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
    assert len(findings) == 7

    ids = [f["id"] for f in findings[:2]]
    resp = client.request("DELETE", "/findings", json={"ids": ids})
    assert resp.status_code == 200 and resp.json()["deleted"] == 2

    remaining = client.get("/findings", params={"tile_id": "tile-unguarded"}).json()
    assert len(remaining) == 5
    assert {f["id"] for f in remaining}.isdisjoint(ids)        # the right rows went

    # deleting the rest empties the ledger; empty / unknown ids are a safe no-op
    rest = [f["id"] for f in remaining]
    assert client.request("DELETE", "/findings", json={"ids": rest}).json()["deleted"] == 5
    assert client.get("/findings", params={"tile_id": "tile-unguarded"}).json() == []
    assert client.request("DELETE", "/findings", json={"ids": []}).json()["deleted"] == 0
    assert client.request("DELETE", "/findings", json={"ids": ["nope"]}).json()["deleted"] == 0


def test_resumes_seed_crud_and_validation(client):
    seeded = client.get("/resumes").json()
    assert len(seeded) == len(CLEAN_CORPUS)  # the shipped sample corpus, seeded on first read
    assert all(r["id"] and r["applicant_name"] and r["updated_at"] for r in seeded)

    created = client.post("/resumes", json={"applicant_name": "Pat Doe", "resume_text": "Staff engineer."})
    assert created.status_code == 201
    rid = created.json()["id"]
    assert len(client.get("/resumes").json()) == len(CLEAN_CORPUS) + 1

    updated = client.put(f"/resumes/{rid}", json={"applicant_name": "Pat Doe",
                                                  "resume_text": "Staff engineer, 11y."}).json()
    assert updated["resume_text"].endswith("11y.")

    # blank fields are rejected; unknown ids 404
    assert client.post("/resumes", json={"applicant_name": " ", "resume_text": "x"}).status_code == 422
    assert client.put("/resumes/nope", json={"applicant_name": "a", "resume_text": "b"}).status_code == 404
    assert client.delete("/resumes/nope").status_code == 404

    assert client.delete(f"/resumes/{rid}").json()["deleted"] is True
    assert len(client.get("/resumes").json()) == len(CLEAN_CORPUS)


def test_deleting_all_resumes_reseeds_samples(client):
    first = client.get("/resumes").json()
    assert len(first) == len(CLEAN_CORPUS)
    for r in first:
        client.delete(f"/resumes/{r['id']}")
    # an empty table re-seeds the shipped samples on next read (spec: seed when empty)
    assert len(client.get("/resumes").json()) == len(CLEAN_CORPUS)


def test_reset_resumes_restores_defaults(client):
    seeded = client.get("/resumes").json()
    assert len(seeded) == len(CLEAN_CORPUS)
    # mutate the corpus: delete one of the defaults and add a custom resume
    assert client.delete(f"/resumes/{seeded[0]['id']}").json()["deleted"] is True
    client.post("/resumes", json={"applicant_name": "Custom One", "resume_text": "bespoke"})
    assert len(client.get("/resumes").json()) == len(CLEAN_CORPUS)  # one default deleted + one custom

    # reset wipes ALL of it (edits + additions) and restores the shipped defaults
    restored = client.post("/resumes/reset").json()
    assert len(restored) == len(CLEAN_CORPUS)
    names = {r["applicant_name"] for r in restored}
    assert "Custom One" not in names and {"James Carter", "Diego Ramirez"} <= names
    assert len(client.get("/resumes").json()) == len(CLEAN_CORPUS)


def test_resume_labels_persist_and_drive_bias_pairing(client):
    # labels round-trip through the API
    created = client.post("/resumes", json={
        "applicant_name": "Dana Cole", "resume_text": "Engineer.",
        "gender": "female", "ethnicity": "asian"}).json()
    assert created["gender"] == "female" and created["ethnicity"] == "asian"
    assert any(r["gender"] == "female" and r["ethnicity"] == "asian" for r in client.get("/resumes").json())

    # gender is validated (pairing needs male/female); ethnicity is free-form
    assert client.post("/resumes", json={"applicant_name": "X", "resume_text": "y",
                                         "gender": "other"}).status_code == 422
    assert client.post("/resumes", json={"applicant_name": "X", "resume_text": "y",
                                         "ethnicity": "latino"}).status_code == 201

    # replace the corpus with a controlled labelled set, then run
    for r in client.get("/resumes").json():
        client.delete(f"/resumes/{r['id']}")
    same = "Backend engineer, led the platform and scaled services."
    for nm, g, e in [("James Carter", "male", "american"),
                     ("Emily Brooks", "female", "american"),
                     ("Hiroshi Tanaka", "male", "asian")]:
        client.post("/resumes", json={"applicant_name": nm, "resume_text": same,
                                      "gender": g, "ethnicity": e})

    run = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock"}).json()
    assert run["summary"]["vulnerabilities_found"] == 7
    bias = next(f for f in run["findings"] if f["category"] == "bias_fairness")
    variants = client.get(f"/findings/{bias['id']}").json()["evidence"]["response"]["variants"]
    # the probe swapped THESE resume names (each resume's own name is the 'from')
    assert {v["a"] for v in variants} == {"James Carter", "Emily Brooks", "Hiroshi Tanaka"}
    assert {v["axis"] for v in variants} <= {"gender", "ethnicity", "both"}


def test_runs_probe_the_db_resume_corpus(client):
    # replace the seeded corpus with one custom resume, then run
    for r in client.get("/resumes").json():
        client.delete(f"/resumes/{r['id']}")
    client.post("/resumes", json={"applicant_name": "Corpus Tester",
                                  "resume_text": "Principal engineer; led platform; scaled services."})
    assert len(client.get("/resumes").json()) == 1
    # the ladder still holds regardless of corpus content (probes inject their own payloads)
    body = client.post("/runs", json={"tile_id": "tile-unguarded", "engine_name": "mock"}).json()
    assert body["summary"]["vulnerabilities_found"] == 7


def test_resume_pdf_extraction(client):
    pdf = _make_pdf("Reliability Engineer at ExampleCorp")
    ok = client.post("/resumes/extract", files={"file": ("cv.pdf", pdf, "application/pdf")})
    assert ok.status_code == 200
    assert "Reliability Engineer" in ok.json()["text"] and ok.json()["pages"] == 1
    # a non-PDF or empty upload is a clean 422, never a 500
    assert client.post("/resumes/extract",
                       files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 422
    assert client.post("/resumes/extract",
                       files={"file": ("e.pdf", b"", "application/pdf")}).status_code == 422


def test_resume_pdf_extract_text_is_capped(client):
    # a PDF whose text layer is huge is rejected (decompression-bomb guard), not a 200/OOM
    big = _make_pdf("xy " * 1_200_000)  # ~3.6 MB of extractable text, over the 2 MB cap
    r = client.post("/resumes/extract", files={"file": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 422


def test_resume_seeding_is_concurrency_safe(tmp_path):
    import threading

    from backend.service import AssessmentService

    service = AssessmentService(str(tmp_path / "ledger.db"), default_engine="mock")
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # all threads hit the empty DB at once to maximize the seed race
        service.list_resumes()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # exactly the shipped samples — the seed lock prevented concurrent double-seeding
    assert len(service.list_resumes()) == len(CLEAN_CORPUS)


def test_reports_list_runs_and_findings(client):
    run = client.post("/runs", json={"tile_id": "tile-unguarded"}).json()
    run_id = run["run_id"]

    runs = client.get("/runs").json()
    assert any(r["run_id"] == run_id and r["status"] == "completed" for r in runs)

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["engine_name"] == "mock"
    assert len(detail["findings"]) == 7

    highs = client.get("/findings", params={"tile_id": "tile-unguarded", "severity": "high"}).json()
    assert all(f["severity"] == "high" for f in highs)  # exact-severity filter
    serious = [f for f in detail["findings"] if f["severity"] in ("high", "critical")]
    assert len(serious) == 5  # 2x injection + jailbreak + 2x bias (exfil x2 is medium)

    finding_id = highs[0]["id"]
    full = client.get(f"/findings/{finding_id}").json()
    assert full["mitigation_guidance"]
    assert "request" in full["repro"] and "response" in full["evidence"]

    assert client.get("/runs/run-does-not-exist").status_code == 404
    assert client.get("/findings/find-does-not-exist").status_code == 404
