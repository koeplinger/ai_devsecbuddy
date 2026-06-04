"""AssessmentService — the integration layer between the HTTP API and the
``devsecbuddy`` library.

It hosts the tiles, selects the engine, drives the documented run lifecycle
(``open_run → baseline → probe → record → close_run`` via ``run_assessment``), and
serves ledger reports through the ``Ledger``. It imports ``devsecbuddy`` and never
reimplements product logic (docs/architecture.md).
"""
from __future__ import annotations

from devsecbuddy import Ledger, get_engine, load_vectors, run_assessment
from devsecbuddy.demo import CLEAN_CORPUS, TILES
from devsecbuddy.engines import AnthropicEngine, MockEngine, VertexEngine
from devsecbuddy.models import Finding

# Engines the backend can select between (docs/ai-engines.md).
ENGINE_CLASSES = {"mock": MockEngine, "anthropic": AnthropicEngine, "vertex": VertexEngine}


class TileNotFound(KeyError):
    pass


class EngineNotAvailable(RuntimeError):
    """A known engine that is designed but not wired up yet (cloud engines, M6) -> 501."""


class UnknownEngine(ValueError):
    """A client-supplied or misconfigured engine name that does not exist -> 400."""


class RunNotFound(KeyError):
    pass


class FindingNotFound(KeyError):
    pass


class AssessmentService:
    def __init__(self, db_path: str, default_engine: str = "mock"):
        self.db_path = db_path
        self.default_engine = default_engine

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

    def run(self, tile_id: str, engine_name: str | None = None) -> dict:
        if tile_id not in TILES:
            raise TileNotFound(tile_id)
        resolved = (engine_name or self.default_engine).lower()
        try:
            chosen = get_engine(resolved)             # unknown name -> ValueError
        except ValueError as exc:
            raise UnknownEngine(str(exc)) from exc     # client/config error -> 400

        adapter = TILES[tile_id](chosen)
        vectors = load_vectors(enabled_only=True)
        ledger = Ledger(self.db_path)
        try:
            out = run_assessment(adapter, vectors, CLEAN_CORPUS,
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
        }
        if full:
            payload["repro"] = f.repro
            payload["evidence"] = f.evidence
        return payload
