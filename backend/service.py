"""AssessmentService — the integration layer between the HTTP API and the
``devsecbuddy`` library.

It hosts the tiles, selects the engine, drives the documented run lifecycle
(``open_run → baseline → probe → record → close_run`` via ``run_assessment``), and
serves ledger reports through the ``Ledger``. It imports ``devsecbuddy`` and never
reimplements product logic (docs/architecture.md).
"""
from __future__ import annotations

import io
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

from devsecbuddy import Ledger, RunCancelled, get_engine, load_vectors, run_assessment
from devsecbuddy.demo import CLEAN_CORPUS, TILES
from devsecbuddy.engines import (
    AnthropicEngine, EngineNotConfigured, GeminiProxyEngine, MockEngine, RateLimitRetryEngine,
    VertexEngine,
)

from .telemetry import CallTelemetry, TelemetryEngine
from devsecbuddy.models import AppRequest, Finding

# Engines the backend can select between (docs/ai-engines.md).
ENGINE_CLASSES = {"mock": MockEngine, "anthropic": AnthropicEngine, "vertex": VertexEngine,
                  "gemini": GeminiProxyEngine}

# Seed resumes for an empty ledger — the brief sample corpus the app ships with,
# carrying the demographic labels used for counterfactual bias pairing.
_RESUME_SEED = [
    {"applicant_name": r.fields["applicant_name"], "resume_text": r.fields["resume_text"],
     "gender": r.meta.get("gender", "unspecified"),
     "ethnicity": r.meta.get("ethnicity", "unspecified")}
    for r in CLEAN_CORPUS
]
# Reject implausibly large PDF uploads up front (defensive — a probe corpus is small).
MAX_PDF_BYTES = 10 * 1024 * 1024
# Cap *extracted* text too: a small compressed PDF can decompress to a huge text layer
# (a "decompression bomb"); a resume is tiny, so 2 MB of text is already generous.
_MAX_PDF_TEXT = 2 * 1024 * 1024


class TileNotFound(KeyError):
    pass


class EngineNotAvailable(RuntimeError):
    """A known engine that is designed but not wired up yet (cloud engines, M6) -> 501."""


class UnknownEngine(ValueError):
    """A client-supplied or misconfigured engine name that does not exist -> 400."""


class UnknownModel(ValueError):
    """A client-supplied model that is not in the selected engine's catalog -> 400."""


class RunNotFound(KeyError):
    pass


class FindingNotFound(KeyError):
    pass


class ResumeNotFound(KeyError):
    pass


class PdfExtractError(ValueError):
    """An uploaded PDF could not be read / yielded no extractable text -> 422."""


class TileBusy(RuntimeError):
    """A streaming run was requested for a tile that already has a job in flight (queued
    or running) -> 409. A tile may have at most one job in the queue at a time.
    """


class RunNotActive(KeyError):
    """cancel() referenced a job id that isn't queued or running (already finished / bad id)."""


# Local date/time WITH timezone, shared by run-log events and the server log, e.g.
# "2026-06-11 14:23:05 PDT". Same format on both so the two logs read consistently.
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S %Z"


def log_timestamp() -> str:
    return datetime.now().astimezone().strftime(LOG_TIMESTAMP_FORMAT)


_TERMINAL_EVENTS = ("result", "cancelled", "error")
# How long a stream blocks waiting for a new event before yielding a heartbeat. The heartbeat
# (a blank NDJSON line the client skips) ensures the generator yields control periodically, so
# a disconnected client's thread is released promptly instead of pinned on an idle run.
_STREAM_POLL_S = 15.0


@dataclass
class _RunJob:
    """One queued/active/finished streaming assessment, held in memory for the backend's
    lifetime (not the DB — a restart starts fresh). ``log`` is the **durable, append-only
    event log**: every progress event the worker emits is kept, so a client can (re)attach at
    any time — a fresh page load or a browser refresh — and rebuild the run console by
    replaying it, then tail new events live. ``cancel`` is observed at each event for
    force-stop. The log is decoupled from any consumer, so a disconnected client never stalls
    the worker."""
    id: str
    tile_id: str
    engine: str
    model: str | None
    corpus: list
    status: str = "queued"                       # queued | running | done | error | cancelled
    log: list = field(default_factory=list)       # append-only event log (the durable record)
    cancel: threading.Event = field(default_factory=threading.Event)
    _order: float = field(default_factory=time.monotonic)             # creation order (eviction)
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _done: threading.Event = field(default_factory=threading.Event)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def emit(self, event: dict) -> None:
        """Append an event to the durable log, advance ``status``, and wake any attached
        streamers. Terminal events (result/cancelled/error) also mark the job done. Each event
        is stamped with a local date/time + timezone (``ts``) at emit time, so the run-console
        log shows when it happened and the stamp is stable across a refresh/replay."""
        event.setdefault("ts", log_timestamp())
        with self._cond:
            self.log.append(event)
            t = event.get("type")
            if t == "run_started":
                self.status = "running"
            elif t in _TERMINAL_EVENTS:
                self.status = "done" if t == "result" else t
                self._done.set()
            self._cond.notify_all()

    def stream(self) -> Iterator[str]:
        """NDJSON lines: replay the whole log so far, then tail new events until the job is
        terminal. Each call keeps its own cursor, so multiple clients (two tabs, a reconnect)
        can attach to the same job independently. Yields a blank-line heartbeat when idle so a
        disconnected client is noticed promptly (the generator must keep returning control)."""
        cursor = 0
        while True:
            with self._cond:
                if cursor >= len(self.log) and not self._done.is_set():
                    self._cond.wait(timeout=_STREAM_POLL_S)   # wakes on emit or times out
                batch = self.log[cursor:]
                cursor = len(self.log)
                finished = self._done.is_set() and cursor >= len(self.log)
            if batch:
                for event in batch:
                    yield json.dumps(event) + "\n"
            elif not finished:
                yield "\n"   # heartbeat: a blank NDJSON line the client skips
            if finished:
                return


def _validate_model(engine, model: str | None) -> None:
    """Reject a client-supplied model that the engine doesn't offer (-> 400), so a typo
    fails fast with a clear message instead of a confusing provider error mid-run. Only
    the *client-supplied* model is checked; an absent model uses the engine's own
    (env-configured) default, which is intentionally not constrained to the catalog."""
    if not model:
        return
    catalog = {m["id"] for m in engine.info().get("models", [])}
    if catalog and model not in catalog:
        raise UnknownModel(
            f"model {model!r} is not offered by engine {engine.name!r}; "
            f"choose one of {sorted(catalog)}"
        )


class AssessmentService:
    def __init__(self, db_path: str, default_engine: str = "mock"):
        self.db_path = db_path
        self.default_engine = default_engine
        # --- Single-threaded scorer: every assessment runs one at a time. Streaming runs
        # are queued and drained by ONE background worker; the same lock also gates the
        # synchronous run(), so no two assessments ever execute concurrently. ---
        self._run_lock = threading.Lock()           # held by whichever run is executing
        self._cv = threading.Condition()            # guards _pending / _jobs / _tiles_in_flight
        self._pending: list[_RunJob] = []           # FIFO of queued-but-not-started jobs
        self._jobs: dict[str, _RunJob] = {}         # id -> job (queued or active), for cancel
        self._tiles_in_flight: set[str] = set()     # tiles with a job queued or running
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()        # serialize lazy worker start
        self._stop = False                          # set by close() to retire the worker
        # Process-global AI-model-call stats (every engine.complete), for the Run-console bar.
        self.telemetry = CallTelemetry()
        # tile_id -> display name, for the active-runs reconnect payload (cheap, static).
        self._tile_names = {d["tile_id"]: d.get("name", d["tile_id"]) for d in self.list_tiles()}
        # Serialize resume seeding so concurrent first-access requests can't double-seed.
        self._seed_lock = threading.Lock()

    # -- catalog ----------------------------------------------------------------

    def list_tiles(self) -> list[dict]:
        return [cls().describe() for cls in TILES.values()]

    def list_engines(self) -> list[dict]:
        engines = []
        for name, cls in ENGINE_CLASSES.items():
            info = cls().info()
            info["name"] = name
            info["default"] = name == self.default_engine
            engines.append(info)
        return engines

    # -- run lifecycle ----------------------------------------------------------

    def run(self, tile_id: str, engine_name: str | None = None,
            model: str | None = None) -> dict:
        if tile_id not in TILES:
            raise TileNotFound(tile_id)
        resolved = (engine_name or self.default_engine).lower()
        try:
            chosen = get_engine(resolved, model=model)  # unknown name -> ValueError
        except ValueError as exc:
            raise UnknownEngine(str(exc)) from exc     # client/config error -> 400
        _validate_model(chosen, model)                 # unknown model -> 400

        # Same rate-limit pause-and-retry as the streaming path, but the synchronous endpoint
        # has no progress events and no force-stop, so cap it tighter (a single escalation,
        # ~90s) rather than blocking the HTTP request — and the shared _run_lock — for minutes.
        adapter = TILES[tile_id](
            RateLimitRetryEngine(TelemetryEngine(chosen, self.telemetry), max_retries=2))
        vectors = load_vectors(enabled_only=True)
        corpus = self._corpus()
        ledger = Ledger(self.db_path)
        try:
            # Serialize with the streaming worker: one scorer runs at a time, globally.
            with self._run_lock:
                out = run_assessment(adapter, vectors, corpus,
                                     ledger=ledger, engine_name=resolved)
        except NotImplementedError as exc:            # a designed-but-unwired cloud engine
            raise EngineNotAvailable(str(exc)) from exc
        finally:
            ledger.close()

        return {
            "run_id": out["run_id"],
            "tile_id": out["tile_id"],
            "engine_name": resolved,
            "summary": out["summary"],
            "findings": [self._finding_payload(f) for f in out["findings"]],
        }

    def run_stream(self, tile_id: str, engine_name: str | None = None,
                   model: str | None = None) -> Iterator[str]:
        """Enqueue a streaming assessment and stream its progress as NDJSON.

        Returns a generator of ``"<json>\\n"`` lines for a ``StreamingResponse``. Runs
        are SERIALIZED: a single background worker drains the queue one job at a time, so
        a caller may kick off several tiles at once but only one scorer runs — the rest
        wait. The first event is ``queued`` (carrying the job ``id`` the client uses to
        cancel and its 1-based queue ``position``); when the worker reaches the job the
        usual ``run_started`` → … → ``result`` events follow.

        Validation happens *before* the first byte: unknown tile -> ``TileNotFound``, bad
        engine -> ``UnknownEngine``/``UnknownModel``, a tile that already has a job queued
        or running -> ``TileBusy`` (409). Errors *during* the run arrive as a terminal
        ``{"type": "error"}`` event; a force-stop arrives as ``{"type": "cancelled"}``.
        """
        if tile_id not in TILES:
            raise TileNotFound(tile_id)
        resolved = (engine_name or self.default_engine).lower()
        try:
            chosen = get_engine(resolved, model=model)  # unknown name -> ValueError
        except ValueError as exc:
            raise UnknownEngine(str(exc)) from exc     # client/config error -> 400
        _validate_model(chosen, model)                 # unknown model -> 400 (before streaming)

        # Pin the corpus now (in the request thread, like run() does) so a concurrent
        # resume edit/delete can't shift what this run probes mid-flight — and so a DB
        # error here surfaces before the job is enqueued (no leak).
        corpus = self._corpus()

        job = _RunJob(id="job-" + uuid.uuid4().hex[:12], tile_id=tile_id,
                      engine=resolved, model=model, corpus=corpus)
        self._ensure_worker()
        with self._cv:
            if tile_id in self._tiles_in_flight:       # one job per tile (queued or running)
                raise TileBusy(f"a run is already queued or in progress for tile {tile_id!r}")
            # This tile's previous (necessarily finished) run is now superseded — drop it so
            # the registry stays ~one job per tile and its stale stream/attach 404s. Done at
            # enqueue (not at finish) so it's deterministic, never racing a draining client.
            for old_id in [jid for jid, j in self._jobs.items() if j.tile_id == tile_id]:
                del self._jobs[old_id]
            self._tiles_in_flight.add(tile_id)
            self._jobs[job.id] = job
            self._pending.append(job)
            position = len(self._pending)
            self._cv.notify()
        # The 'queued' event is the FIRST thing in the job's log, so a client always learns
        # the job id before any run_started the worker may post.
        job.emit({"type": "queued", "id": job.id, "tile_id": tile_id,
                  "engine_name": resolved, "model": model, "position": position})
        self._emit_positions()
        return job.stream()   # replay the log so far (the queued event) + tail live events

    def attach_stream(self, job_id: str) -> Iterator[str]:
        """Reconnect to an existing job's stream — replay its whole event log, then tail.
        Powers a browser refresh / a second tab. Raises ``RunNotFound`` for an unknown id
        (e.g. a finished run already evicted)."""
        with self._cv:
            job = self._jobs.get(job_id)
        if job is None:
            raise RunNotFound(job_id)
        return job.stream()

    def active_runs(self) -> list[dict]:
        """The latest job per tile (in flight OR recently finished), so a freshly loaded /
        refreshed client can rebuild the Run console: it reconnects to each via
        ``attach_stream`` to replay the log and tail live ones."""
        with self._cv:
            latest: dict[str, _RunJob] = {}
            for job in self._jobs.values():
                cur = latest.get(job.tile_id)
                if cur is None or job._order > cur._order:
                    latest[job.tile_id] = job
            jobs = sorted(latest.values(), key=lambda j: j._order)
        return [{"job_id": j.id, "tile_id": j.tile_id,
                 "tile_name": self._tile_names.get(j.tile_id, j.tile_id),
                 "engine": j.engine, "model": j.model, "status": j.status} for j in jobs]

    def cancel_run(self, job_id: str) -> dict:
        """Cancel a job by id. If it is still QUEUED, drop it from the queue (remove from
        queue); if it is RUNNING, signal a force-stop (observed at the next probe event).
        Raises ``RunNotActive`` for an unknown / already-finished id."""
        removed_from_queue = False
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None or job.done:                # unknown / already-finished -> not active
                raise RunNotActive(job_id)
            job.cancel.set()
            if job in self._pending:                   # not started yet -> remove now
                self._pending.remove(job)
                self._jobs.pop(job_id, None)           # removed-from-queue jobs are dropped, not kept
                self._tiles_in_flight.discard(job.tile_id)
                removed_from_queue = True
        if removed_from_queue:
            job.emit({"type": "cancelled", "id": job_id, "reason": "removed_from_queue"})
            self._emit_positions()
        # else: the job is active (or just dequeued); the worker / on_event hook stops it.
        return {"cancelled": True, "job_id": job_id,
                "state": "removed_from_queue" if removed_from_queue else "stopping"}

    def _ensure_worker(self) -> None:
        """Start the single drain worker on first use (idempotent)."""
        with self._worker_lock:
            if self._worker is None:
                self._worker = threading.Thread(target=self._worker_loop,
                                                name="run-worker", daemon=True)
                self._worker.start()

    def close(self) -> None:
        """Retire the drain worker (call on app shutdown). Idempotent. Also signals any
        executing job to cancel, so a worker paused mid-rate-limit-wait exits promptly
        (at the next ~2s poll) instead of holding the loop until its long wait elapses."""
        with self._cv:
            self._stop = True
            for job in self._jobs.values():
                job.cancel.set()
            self._cv.notify_all()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=3.0)
        # The retired worker never ran the still-pending jobs, so end their streams explicitly
        # (a running job was already cancelled to a terminal event above) — otherwise their
        # attached generators would block forever instead of completing on shutdown.
        with self._cv:
            leftover = [j for j in self._jobs.values() if not j.done]
        for job in leftover:
            job.emit({"type": "cancelled", "id": job.id, "reason": "shutdown"})

    def _worker_loop(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return                                 # retired by close()
                job = self._pending.pop(0)
                cancelled_in_queue = job.cancel.is_set()  # cancelled after dequeue race
            terminal: dict | None = None
            try:
                if cancelled_in_queue:
                    terminal = {"type": "cancelled", "id": job.id, "reason": "removed_from_queue"}
                else:
                    self._emit_positions()             # remaining jobs shift up
                    with self._run_lock:               # one scorer at a time (gates run() too)
                        terminal = self._run_job(job)
            finally:
                if terminal is None:                   # defensive: a run always yields a terminal
                    terminal = {"type": "error", "kind": "error",
                                "message": "run produced no terminal event"}
                # ORDER MATTERS: free the tile (and shift the queue) BEFORE the terminal event
                # is observable, so a client reacting to it sees consistent state — a re-run of
                # this tile won't 409, and running_tiles()/active_runs() are already updated.
                # The finished job stays in _jobs (its log is durable for reconnect) until a
                # later run of the same tile evicts it at enqueue.
                with self._cv:
                    self._tiles_in_flight.discard(job.tile_id)
                self._emit_positions()
                job.emit(terminal)                     # NOW publish the terminal event -> stream ends

    def _run_job(self, job: _RunJob) -> dict:
        """Execute one assessment, emitting progress to the job's durable log. RETURNS the
        terminal event (result/error/cancelled) WITHOUT emitting it — the caller emits it
        only after per-job cleanup, so a client reacting to it sees consistent state (a freed
        tile). The ``on_event`` hook doubles as the force-stop check."""
        def emit(event: dict) -> None:
            if job.cancel.is_set():
                raise RunCancelled()
            job.emit(event)

        ledger = None
        try:
            ledger = Ledger(self.db_path)
            # Wrap the engine so a rate-limit (429) pauses-and-retries this scorer with an
            # escalating wait; `emit` shows the wait and makes the force-stop interrupt it.
            engine = RateLimitRetryEngine(
                TelemetryEngine(get_engine(job.engine, model=job.model), self.telemetry),
                on_wait=emit)
            adapter = TILES[job.tile_id](engine)
            vectors = load_vectors(enabled_only=True)
            out = run_assessment(adapter, vectors, job.corpus, ledger=ledger,
                                 engine_name=job.engine, on_event=emit)
            return {
                "type": "result", "run_id": out["run_id"], "tile_id": job.tile_id,
                "engine_name": job.engine, "summary": out["summary"],
                "findings": [self._finding_payload(f) for f in out["findings"]],
            }
        except RunCancelled:
            return {"type": "cancelled", "id": job.id, "reason": "force_stopped"}
        except NotImplementedError as exc:            # designed-but-unwired engine
            return {"type": "error", "kind": "not_available", "message": str(exc)}
        except EngineNotConfigured as exc:            # implemented, missing SDK/creds
            return {"type": "error", "kind": "not_configured", "message": str(exc)}
        except Exception as exc:                      # surfaced to the client, not swallowed
            return {"type": "error", "kind": "error", "message": str(exc)}
        finally:
            if ledger is not None:
                ledger.close()

    def _emit_positions(self) -> None:
        """Push the current 1-based queue position to each still-pending job, so a waiting
        card shows it advancing as runs ahead of it finish. Emitted UNDER _cv so a job that
        is concurrently dequeued or cancelled cannot receive a stale position after it has
        started (a terminal job is no longer in _pending, so it is skipped)."""
        with self._cv:
            for index, job in enumerate(self._pending, start=1):
                job.emit({"type": "queued", "id": job.id, "position": index})

    def running_tiles(self) -> list[str]:
        """Tiles with a job in flight — queued or running."""
        with self._cv:
            return sorted(self._tiles_in_flight)

    def queue_snapshot(self) -> dict:
        """Introspection: ids of pending (queued) jobs in order + the count in flight."""
        with self._cv:
            return {"pending": [j.id for j in self._pending],
                    "in_flight": sorted(self._tiles_in_flight)}

    def default_engine_known(self) -> bool:
        """Whether the configured default engine name is a recognized engine."""
        return self.default_engine.lower() in ENGINE_CLASSES

    # -- reports ----------------------------------------------------------------

    def list_runs(self, tile_id: str | None = None, limit: int = 100) -> list[dict]:
        with Ledger(self.db_path) as ledger:
            return ledger.list_runs(tile_id=tile_id, limit=limit)

    def get_run(self, run_id: str) -> dict:
        with Ledger(self.db_path) as ledger:
            run = ledger.get_run(run_id)
            if run is None:
                raise RunNotFound(run_id)
            run["findings"] = [self._finding_payload(f) for f in ledger.query(run_id=run_id)]
            return run

    def list_findings(self, **filters) -> list[dict]:
        with Ledger(self.db_path) as ledger:
            return [self._finding_payload(f) for f in ledger.query(**filters)]

    def get_finding(self, finding_id: str) -> dict:
        with Ledger(self.db_path) as ledger:
            finding = ledger.get_finding(finding_id)
        if finding is None:
            raise FindingNotFound(finding_id)
        return self._finding_payload(finding, full=True)

    def delete_findings(self, ids: list[str]) -> int:
        """Permanently delete the given findings; returns how many were removed."""
        with Ledger(self.db_path) as ledger:
            return ledger.delete_ids(ids)

    # -- resumes (the sample corpus the app probes against) ---------------------

    def _seed(self, ledger: Ledger) -> None:
        # The check-then-insert in seed_resumes isn't atomic across connections, so a
        # process-wide lock serializes it — concurrent first-access requests (e.g.
        # "Assess all tiles" on a fresh DB) can't each insert the samples. The deploy
        # runs a single uvicorn process, so a process lock is sufficient.
        with self._seed_lock:
            ledger.seed_resumes(_RESUME_SEED)

    def _corpus(self) -> list[AppRequest]:
        """The clean resume corpus a run probes against: the user's DB resumes, seeded
        from the shipped samples on first use. Falls back to the in-code samples if the
        table was emptied, so a run never fails for lack of a corpus."""
        with Ledger(self.db_path) as ledger:
            self._seed(ledger)
            resumes = ledger.list_resumes()
        if not resumes:
            return list(CLEAN_CORPUS)
        return [
            AppRequest(
                fields={"applicant_name": r["applicant_name"], "resume_text": r["resume_text"]},
                meta={"gender": r.get("gender", "unspecified"),
                      "ethnicity": r.get("ethnicity", "unspecified")},
            )
            for r in resumes
        ]

    def list_resumes(self) -> list[dict]:
        with Ledger(self.db_path) as ledger:
            self._seed(ledger)  # seed the shipped samples on first use
            return ledger.list_resumes()

    def create_resume(self, applicant_name: str, resume_text: str,
                      gender: str = "unspecified", ethnicity: str = "unspecified") -> dict:
        with Ledger(self.db_path) as ledger:
            return ledger.create_resume(applicant_name, resume_text, gender, ethnicity)

    def update_resume(self, resume_id: str, applicant_name: str, resume_text: str,
                      gender: str = "unspecified", ethnicity: str = "unspecified") -> dict:
        with Ledger(self.db_path) as ledger:
            updated = ledger.update_resume(resume_id, applicant_name, resume_text, gender, ethnicity)
        if updated is None:
            raise ResumeNotFound(resume_id)
        return updated

    def delete_resume(self, resume_id: str) -> None:
        with Ledger(self.db_path) as ledger:
            if not ledger.delete_resume(resume_id):
                raise ResumeNotFound(resume_id)

    def reset_resumes(self) -> list[dict]:
        """'Reset all': delete every resume (including the user's edits/additions) and
        re-seed the shipped defaults. Held under the seed lock so a concurrent run never
        observes the momentarily-empty table. Returns the restored corpus."""
        with self._seed_lock:
            with Ledger(self.db_path) as ledger:
                ledger.delete_all_resumes()
                ledger.seed_resumes(_RESUME_SEED)
                return ledger.list_resumes()

    @staticmethod
    def extract_pdf_text(data: bytes) -> dict:
        """Extract plain text from an uploaded PDF (pypdf). Returns {text, pages, chars}.

        Raises PdfExtractError (-> 422) for empty / oversized / unreadable PDFs, or a
        PDF with no extractable text (e.g. a scan of images with no text layer)."""
        if not data:
            raise PdfExtractError("the uploaded file is empty.")
        if len(data) > MAX_PDF_BYTES:
            raise PdfExtractError(f"the PDF is too large (limit {MAX_PDF_BYTES // (1024 * 1024)} MB).")
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # dependency missing in this environment
            raise PdfExtractError("PDF support is not installed on the server (pypdf).") from exc
        try:
            reader = PdfReader(io.BytesIO(data))
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                piece = (page.extract_text() or "").strip()
                if not piece:
                    continue
                parts.append(piece)
                total += len(piece)
                if total > _MAX_PDF_TEXT:  # decompression-bomb guard: bound the text layer
                    raise PdfExtractError("the PDF's extracted text is too large.")
        except PdfExtractError:
            raise
        except Exception as exc:  # malformed / encrypted / not actually a PDF
            raise PdfExtractError(f"could not read the PDF ({exc}).") from exc
        text = "\n\n".join(parts).strip()
        if not text:
            raise PdfExtractError("no extractable text found (the PDF may be scanned images).")
        return {"text": text, "pages": len(reader.pages), "chars": len(text)}

    # -- serialization ----------------------------------------------------------

    @staticmethod
    def _finding_payload(f: Finding, full: bool = False) -> dict:
        payload = {
            "id": f.id, "run_id": f.run_id, "tile_id": f.tile_id, "vector_id": f.vector_id,
            "category": f.category, "severity": f.severity, "status": f.status,
            "owasp_ref": f.owasp_ref, "cwe": f.cwe, "fingerprint": f.fingerprint,
            "created_at": f.created_at, "mitigation_guidance": f.mitigation_guidance,
            "metric_value": f.evidence.get("metric_value"),
            "detail": f.evidence.get("detail", ""),
            # engine + model that produced this finding (stamped into repro at record time)
            "engine": f.repro.get("engine_name"),
            "model": f.repro.get("model"),
        }
        if full:
            payload["repro"] = f.repro
            payload["evidence"] = f.evidence
        return payload
