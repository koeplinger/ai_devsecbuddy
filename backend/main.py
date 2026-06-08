"""FastAPI app — the AI DevSecBuddy run/report API (roadmap M2).

A thin HTTP layer over :class:`AssessmentService`. The frontend (M3) speaks only
to this API. Run it with::

    uvicorn backend.main:app --reload      # serves on http://127.0.0.1:8000 (/docs for OpenAPI)
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import Settings, load_settings
from .service import (
    AssessmentService,
    EngineNotAvailable,
    EngineNotConfigured,
    FindingNotFound,
    RunNotFound,
    TileBusy,
    TileNotFound,
    UnknownEngine,
)


class RunRequest(BaseModel):
    tile_id: str
    engine_name: str | None = None


class DeleteFindingsRequest(BaseModel):
    ids: list[str]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    service = AssessmentService(settings.db_path, default_engine=settings.engine)

    app = FastAPI(
        title="AI DevSecBuddy API",
        version="0.1.0",
        description="Run/report API for automated adversarial AI-security testing (roadmap M2).",
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

    @app.post("/runs", tags=["runs"], status_code=201)
    def create_run(req: RunRequest) -> dict:
        try:
            return service.run(req.tile_id, req.engine_name)
        except TileNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown tile {req.tile_id!r}")
        except UnknownEngine as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except EngineNotConfigured as exc:        # implemented but missing SDK/credentials
            raise HTTPException(status_code=503, detail=str(exc))
        except EngineNotAvailable as exc:         # designed-but-unwired (legacy path)
            raise HTTPException(status_code=501, detail=str(exc))

    @app.post("/runs/stream", tags=["runs"])
    def create_run_stream(req: RunRequest) -> StreamingResponse:
        """Run an assessment and stream live progress as NDJSON.

        One live run per tile: a second request for a tile already running gets 409.
        Each line is a JSON event (``run_started``, ``phase``, ``probe_started`` /
        ``probe_done``, then a terminal ``result`` or ``error``). The frontend's
        per-tile run console renders these as they arrive.
        """
        try:
            lines = service.run_stream(req.tile_id, req.engine_name)
        except TileNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown tile {req.tile_id!r}")
        except UnknownEngine as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except TileBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return StreamingResponse(
            lines,
            media_type="application/x-ndjson",
            # Defeat proxy/browser buffering so events arrive incrementally.
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
    ) -> list[dict]:
        return service.list_findings(
            tile_id=tile_id, category=category, severity=severity,
            status=status, owasp_ref=owasp_ref, vector_id=vector_id, engine=engine,
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

    return app


app = create_app()
