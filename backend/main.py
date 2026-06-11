"""FastAPI app — the AI DevSecBuddy run/report API (roadmap M2).

A thin HTTP layer over :class:`AssessmentService`. The frontend (M3) speaks only
to this API. Run it with::

    uvicorn backend.main:app --reload      # serves on http://127.0.0.1:8000 (/docs for OpenAPI)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import Settings, load_settings
from .service import (
    MAX_PDF_BYTES,
    AssessmentService,
    EngineNotAvailable,
    EngineNotConfigured,
    FindingNotFound,
    PdfExtractError,
    ResumeNotFound,
    RunNotActive,
    RunNotFound,
    TileBusy,
    TileNotFound,
    UnknownEngine,
    UnknownModel,
)


class RunRequest(BaseModel):
    tile_id: str
    engine_name: str | None = None
    model: str | None = None


class DeleteFindingsRequest(BaseModel):
    ids: list[str]


class ResumeIn(BaseModel):
    applicant_name: str
    resume_text: str
    # Demographic labels for counterfactual bias pairing (free-form; 'unspecified'
    # opts the resume out of an axis). Gender pairing uses 'male'/'female'.
    gender: str = "unspecified"
    ethnicity: str = "unspecified"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    service = AssessmentService(settings.db_path, default_engine=settings.engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        service.close()       # retire the single drain worker on shutdown

    app = FastAPI(
        title="AI DevSecBuddy API",
        version="0.1.0",
        description="Run/report API for automated adversarial AI-security testing (roadmap M2).",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.service = service
    app.state.settings = settings

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "name": "AI DevSecBuddy API",
            "version": "0.1.0",
            "default_engine": settings.engine,
            "endpoints": ["/health", "/tiles", "/engines", "/runs", "/findings", "/docs"],
        }

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "default_engine": settings.engine,
            "default_engine_known": service.default_engine_known(),
            "db": settings.db_path,
        }

    @app.get("/tiles", tags=["catalog"])
    def list_tiles() -> list[dict]:
        return service.list_tiles()

    @app.get("/engines", tags=["catalog"])
    def list_engines() -> list[dict]:
        return service.list_engines()

    @app.get("/telemetry", tags=["meta"])
    def telemetry() -> dict:
        """AI-model-call stats since the backend started (powers the Run-console stats bar)."""
        return service.telemetry.snapshot()

    @app.post("/runs", tags=["runs"], status_code=201)
    def create_run(req: RunRequest) -> dict:
        try:
            return service.run(req.tile_id, req.engine_name, req.model)
        except TileNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown tile {req.tile_id!r}")
        except (UnknownEngine, UnknownModel) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except EngineNotConfigured as exc:        # implemented but missing SDK/credentials
            raise HTTPException(status_code=503, detail=str(exc))
        except EngineNotAvailable as exc:         # designed-but-unwired (legacy path)
            raise HTTPException(status_code=501, detail=str(exc))

    @app.post("/runs/stream", tags=["runs"])
    def create_run_stream(req: RunRequest) -> StreamingResponse:
        """Enqueue an assessment and stream live progress as NDJSON.

        Runs are serialized: only one scorer runs at a time, so a second request is
        queued behind the first (and a tile that already has a job queued/running gets
        409). The first line is a ``queued`` event carrying the job ``id`` (used to
        cancel) and queue ``position``; then ``run_started`` … and a terminal ``result``,
        ``error``, or ``cancelled``. The frontend renders these per tile.
        """
        try:
            lines = service.run_stream(req.tile_id, req.engine_name, req.model)
        except TileNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown tile {req.tile_id!r}")
        except (UnknownEngine, UnknownModel) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except TileBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return StreamingResponse(
            lines,
            media_type="application/x-ndjson",
            # Defeat proxy/browser buffering so events arrive incrementally.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/runs/{job_id}/cancel", tags=["runs"])
    def cancel_run(job_id: str) -> dict:
        """Cancel a streaming run by its job id: remove it from the queue if it hasn't
        started, or force-stop it if it's running. The run's own NDJSON stream then ends
        with a terminal ``cancelled`` event. 404 if the id isn't queued or running."""
        try:
            return service.cancel_run(job_id)
        except RunNotActive:
            raise HTTPException(status_code=404, detail=f"No queued or running job {job_id!r}")

    @app.get("/runs/active", tags=["runs"])
    def active_runs() -> list[dict]:
        """The latest run per tile (in flight OR recently finished), so a freshly loaded or
        refreshed client can rebuild the Run console — it reconnects to each via
        GET /runs/{job_id}/stream. (Defined before /runs/{run_id} so 'active' isn't a run id.)"""
        return service.active_runs()

    @app.get("/runs/{job_id}/stream", tags=["runs"])
    def attach_run_stream(job_id: str) -> StreamingResponse:
        """Reconnect to a run's NDJSON stream: replay its whole event log, then tail new
        events until it finishes. Powers a browser refresh / a second tab. 404 if the job id
        is unknown or already evicted."""
        try:
            lines = service.attach_stream(job_id)
        except RunNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown or evicted run {job_id!r}")
        return StreamingResponse(
            lines, media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/runs", tags=["runs"])
    def list_runs(tile_id: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
        return service.list_runs(tile_id=tile_id, limit=limit)

    @app.get("/runs/{run_id}", tags=["runs"])
    def get_run(run_id: str) -> dict:
        try:
            return service.get_run(run_id)
        except RunNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown run {run_id!r}")

    @app.get("/findings", tags=["report"])
    def list_findings(
        tile_id: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        owasp_ref: str | None = None,
        vector_id: str | None = None,
        engine: str | None = None,
        model: str | None = None,
    ) -> list[dict]:
        return service.list_findings(
            tile_id=tile_id, category=category, severity=severity,
            status=status, owasp_ref=owasp_ref, vector_id=vector_id,
            engine=engine, model=model,
        )

    @app.get("/findings/{finding_id}", tags=["report"])
    def get_finding(finding_id: str) -> dict:
        try:
            return service.get_finding(finding_id)
        except FindingNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown finding {finding_id!r}")

    @app.delete("/findings", tags=["report"])
    def delete_findings(req: DeleteFindingsRequest) -> dict:
        """Permanently delete the listed findings (hard delete). The frontend sends the
        ids of the findings currently shown after the user confirms in a modal."""
        return {"deleted": service.delete_findings(req.ids)}

    # -- resumes: the sample corpus the app probes against ----------------------

    def _clean_resume(req: ResumeIn) -> tuple[str, str, str, str]:
        name, text = req.applicant_name.strip(), req.resume_text.strip()
        if not name or not text:
            raise HTTPException(status_code=422, detail="applicant_name and resume_text are required")
        # Gender drives the counterfactual gender pairing, which needs exactly
        # male/female — validate it so an out-of-set value fails loudly instead of
        # silently dropping the resume from the axis. Ethnicity stays free-form (any
        # cultural-background label forms its own group).
        gender = (req.gender or "").strip().lower() or "unspecified"
        if gender not in {"unspecified", "male", "female"}:
            raise HTTPException(status_code=422, detail="gender must be unspecified, male, or female")
        ethnicity = (req.ethnicity or "").strip().lower() or "unspecified"
        return name, text, gender, ethnicity

    @app.get("/resumes", tags=["resumes"])
    def list_resumes() -> list[dict]:
        return service.list_resumes()

    @app.post("/resumes", tags=["resumes"], status_code=201)
    def create_resume(req: ResumeIn) -> dict:
        name, text, gender, ethnicity = _clean_resume(req)
        return service.create_resume(name, text, gender, ethnicity)

    @app.post("/resumes/reset", tags=["resumes"])
    def reset_resumes() -> list[dict]:
        """'Reset all': delete every resume (incl. user edits/additions) and restore the
        shipped default corpus. Returns the restored resumes."""
        return service.reset_resumes()

    @app.post("/resumes/extract", tags=["resumes"])
    async def extract_resume_pdf(file: UploadFile = File(...)) -> dict:
        """Extract plain text from an uploaded PDF (convenience for drafting a resume)."""
        # Reject an oversized upload before buffering it (when the size is known).
        if file.size is not None and file.size > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="the PDF is too large.")
        data = await file.read()
        try:
            return service.extract_pdf_text(data)
        except PdfExtractError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.put("/resumes/{resume_id}", tags=["resumes"])
    def update_resume(resume_id: str, req: ResumeIn) -> dict:
        name, text, gender, ethnicity = _clean_resume(req)
        try:
            return service.update_resume(resume_id, name, text, gender, ethnicity)
        except ResumeNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown resume {resume_id!r}")

    @app.delete("/resumes/{resume_id}", tags=["resumes"])
    def delete_resume(resume_id: str) -> dict:
        try:
            service.delete_resume(resume_id)
        except ResumeNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown resume {resume_id!r}")
        return {"deleted": True}

    return app


app = create_app()
