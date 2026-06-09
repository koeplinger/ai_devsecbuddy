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
import queue
import threading
from typing import Iterator

from devsecbuddy import Ledger, get_engine, load_vectors, run_assessment
from devsecbuddy.demo import CLEAN_CORPUS, TILES
from devsecbuddy.engines import AnthropicEngine, EngineNotConfigured, MockEngine, VertexEngine
from devsecbuddy.models import AppRequest, Finding

# Engines the backend can select between (docs/ai-engines.md).
ENGINE_CLASSES = {"mock": MockEngine, "anthropic": AnthropicEngine, "vertex": VertexEngine}

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
    """A streaming run was requested for a tile that already has one in flight -> 409.

    The product invariant is "one live assessment run per tile" — multiple tiles may
    run concurrently, but a single tile serializes its runs.
    """


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
        # Tiles with a streaming run in flight, guarding "one live run per tile".
        self._running: set[str] = set()
        self._running_lock = threading.Lock()
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

        adapter = TILES[tile_id](chosen)
        vectors = load_vectors(enabled_only=True)
        corpus = self._corpus()
        ledger = Ledger(self.db_path)
        try:
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
        """Run an assessment, streaming progress as newline-delimited JSON (NDJSON).

        Returns a generator of ``"<json>\\n"`` lines the HTTP layer hands to a
        ``StreamingResponse``. The work runs in a background thread; lifecycle and
        per-probe events (from ``run_assessment``'s ``on_event``) are forwarded to
        the client as they happen, so a slow real-engine run shows live progress
        instead of a single blocking response.

        Validation happens *before* the first byte is streamed so the caller can map
        it to a status code: unknown tile -> ``TileNotFound``, bad engine name ->
        ``UnknownEngine``, and a tile that is already running -> ``TileBusy`` (409).
        Errors raised *during* the run (e.g. an unconfigured cloud engine) cannot
        change the status code once streaming has begun, so they arrive as a terminal
        ``{"type": "error", ...}`` event instead.
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
        # error here surfaces before the tile is reserved (no leak).
        corpus = self._corpus()

        # Reserve the tile (one live run per tile). Released in the worker's finally,
        # which always runs once the thread starts — even if the client disconnects.
        with self._running_lock:
            if tile_id in self._running:
                raise TileBusy(f"a run is already in progress for tile {tile_id!r}")
            self._running.add(tile_id)

        events: queue.Queue = queue.Queue()
        end = object()

        def worker() -> None:
            # Everything that can fail lives inside the try so the finally ALWAYS runs:
            # it must release the tile and post the terminal sentinel, or the tile leaks
            # (stuck 409) and the stream generator blocks on an event that never comes.
            # Ledger() itself can raise (locked/permission/corrupt db), so open it here.
            ledger = None
            try:
                ledger = Ledger(self.db_path)
                adapter = TILES[tile_id](get_engine(resolved, model=model))
                vectors = load_vectors(enabled_only=True)
                out = run_assessment(adapter, vectors, corpus, ledger=ledger,
                                     engine_name=resolved, on_event=events.put)
                events.put({
                    "type": "result", "run_id": out["run_id"], "tile_id": tile_id,
                    "engine_name": resolved, "summary": out["summary"],
                    "findings": [self._finding_payload(f) for f in out["findings"]],
                })
            except NotImplementedError as exc:        # designed-but-unwired engine
                events.put({"type": "error", "kind": "not_available", "message": str(exc)})
            except EngineNotConfigured as exc:        # implemented, missing SDK/creds
                events.put({"type": "error", "kind": "not_configured", "message": str(exc)})
            except Exception as exc:                  # surfaced to the client, not swallowed
                events.put({"type": "error", "kind": "error", "message": str(exc)})
            finally:
                if ledger is not None:
                    ledger.close()
                with self._running_lock:
                    self._running.discard(tile_id)
                events.put(end)

        threading.Thread(target=worker, name=f"run-{tile_id}", daemon=True).start()

        def stream() -> Iterator[str]:
            while True:
                event = events.get()
                if event is end:
                    break
                yield json.dumps(event) + "\n"

        return stream()

    def running_tiles(self) -> list[str]:
        """Tiles with a streaming run currently in flight."""
        with self._running_lock:
            return sorted(self._running)

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
