"""Phase 3 — the vulnerability ledger (docs/vulnerability-ledger.md, docs/phases.md).

``Ledger`` owns *all* persistence to ``data/ledger.db`` and abstracts SQLite from
the rest of the library. Schema is the five tables of record (tiles, runs,
baselines, attack_vectors, findings); column names and foreign keys are binding.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid

from ._util import now_iso, short_hash
from .adapters import AppAdapter
from .models import CATEGORY_OWASP, INJECTION_CWE, AttackVector, Baseline, Finding, ProbeResult

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "data", "ledger.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tiles (
    tile_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    guardrails  TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    tile_id     TEXT NOT NULL REFERENCES tiles(tile_id),
    engine_name TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    summary     TEXT
);
CREATE TABLE IF NOT EXISTS baselines (
    baseline_id        TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL REFERENCES runs(run_id),
    tile_id            TEXT NOT NULL REFERENCES tiles(tile_id),
    sample_count       INTEGER NOT NULL,
    score_stats        TEXT,
    behavior_signature TEXT,
    created_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attack_vectors (
    vector_id           TEXT PRIMARY KEY,
    category            TEXT NOT NULL,
    owasp_ref           TEXT NOT NULL,
    severity            TEXT NOT NULL,
    description         TEXT,
    target              TEXT,
    payload_or_template TEXT,
    success_criteria    TEXT,
    mitigation          TEXT,
    enabled             INTEGER NOT NULL,
    snapshot_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    finding_id          TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES runs(run_id),
    tile_id             TEXT NOT NULL REFERENCES tiles(tile_id),
    vector_id           TEXT NOT NULL REFERENCES attack_vectors(vector_id),
    category            TEXT NOT NULL,
    severity            TEXT NOT NULL,
    status              TEXT NOT NULL,
    repro_detail        TEXT,
    evidence            TEXT,
    mitigation_guidance TEXT,
    owasp_ref           TEXT NOT NULL,
    cwe                 TEXT,
    fingerprint         TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (run_id, fingerprint)
);
"""

_FILTERABLE = ("tile_id", "run_id", "category", "severity", "status", "owasp_ref", "vector_id")


class Ledger:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # -- run lifecycle ----------------------------------------------------------

    def register_tile(self, adapter: AppAdapter) -> None:
        meta = adapter.describe()
        self.conn.execute(
            "INSERT OR IGNORE INTO tiles(tile_id, name, description, guardrails, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (adapter.tile_id, adapter.name, meta.get("description", ""),
             json.dumps(meta.get("guardrails", [])), now_iso()),
        )
        self.conn.commit()

    def open_run(self, tile_id: str, engine_name: str) -> str:
        run_id = "run-" + uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO runs(run_id, tile_id, engine_name, started_at, status) "
            "VALUES (?, ?, ?, ?, 'running')",
            (run_id, tile_id, engine_name, now_iso()),
        )
        self.conn.commit()
        return run_id

    def record_baseline(self, run_id: str, baseline: Baseline) -> str:
        baseline_id = "baseline-" + short_hash(run_id, baseline.tile_id, length=10)
        self.conn.execute(
            "INSERT OR REPLACE INTO baselines"
            "(baseline_id, run_id, tile_id, sample_count, score_stats, behavior_signature, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (baseline_id, run_id, baseline.tile_id, baseline.sample_count,
             json.dumps(baseline.score_stats), json.dumps(baseline.behavior_signature),
             baseline.created_at),
        )
        self.conn.commit()
        return baseline_id

    def snapshot_vectors(self, vectors: list[AttackVector]) -> None:
        """Snapshot each vector exactly as it was run, so findings stay reproducible
        even if the YAML later changes (docs/vulnerability-ledger.md §3.4)."""
        snapped_at = now_iso()
        for v in vectors:
            if v.payload is not None:
                payload = v.payload
            elif isinstance(v.template, str):
                payload = v.template
            else:
                payload = json.dumps(v.template)
            self.conn.execute(
                "INSERT OR REPLACE INTO attack_vectors"
                "(vector_id, category, owasp_ref, severity, description, target, "
                " payload_or_template, success_criteria, mitigation, enabled, snapshot_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (v.id, v.category, v.owasp_ref, v.severity, v.description, v.target,
                 payload, json.dumps(v.success_criteria), v.mitigation,
                 1 if v.enabled else 0, snapped_at),
            )
        self.conn.commit()

    def record(self, run_id: str, results: list[ProbeResult],
               vectors: list[AttackVector] | None = None,
               model: str | None = None) -> list[Finding]:
        """Convert *failing* probes (success=True) into Findings and persist them.

        Dedupes within a run via UNIQUE(run_id, fingerprint): a repeat of the same
        underlying vulnerability is ignored rather than duplicated. ``model`` (the
        engine's model id) is stamped into each finding's repro so the ledger can show
        which model produced it.
        """
        by_id = {v.id: v for v in (vectors or [])}
        row = self.conn.execute("SELECT engine_name FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        engine_name = row["engine_name"] if row else "mock"

        findings: list[Finding] = []
        for r in results:
            if not r.success:
                continue
            vector = by_id.get(r.vector_id)
            if vector is not None:
                mitigation, owasp_ref = vector.mitigation, vector.owasp_ref
            else:
                # Documented 2-arg record(run_id, results): recover the vector's
                # mitigation/owasp from the attack_vectors snapshot written this run.
                snap = self.conn.execute(
                    "SELECT owasp_ref, mitigation FROM attack_vectors WHERE vector_id = ?",
                    (r.vector_id,)).fetchone()
                mitigation = (snap["mitigation"] if snap else "") or ""
                owasp_ref = snap["owasp_ref"] if snap else ""
            # owasp_ref is a NOT NULL audit column and is deterministically derivable
            # from category (docs/vulnerability-ledger.md §8); never leave it empty.
            owasp_ref = owasp_ref or CATEGORY_OWASP.get(r.category, "")
            cwe = INJECTION_CWE if r.category in ("prompt_injection", "modal_jailbreak") else None
            fingerprint = _fingerprint(r)
            finding_id = "find-" + short_hash(run_id, fingerprint, length=8)
            created_at = now_iso()
            repro = {
                "engine_name": engine_name,
                "model": model,
                "deterministic": engine_name == "mock",
                "tile_id": r.tile_id,
                "vector_id": r.vector_id,
                "request": r.request_snapshot,
                "baseline_ref": r.baseline_ref,
            }
            evidence = {
                "response": r.response_snapshot,
                "metric_value": r.metric_value,
                "detail": r.detail,
            }
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO findings"
                "(finding_id, run_id, tile_id, vector_id, category, severity, status, "
                " repro_detail, evidence, mitigation_guidance, owasp_ref, cwe, fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)",
                (finding_id, run_id, r.tile_id, r.vector_id, r.category, r.severity,
                 json.dumps(repro), json.dumps(evidence), mitigation, owasp_ref, cwe,
                 fingerprint, created_at),
            )
            if cursor.rowcount:
                findings.append(Finding(
                    id=finding_id, run_id=run_id, tile_id=r.tile_id, vector_id=r.vector_id,
                    category=r.category, severity=r.severity, status="open", repro=repro,
                    evidence=evidence, mitigation_guidance=mitigation, owasp_ref=owasp_ref,
                    cwe=cwe, fingerprint=fingerprint, created_at=created_at,
                ))
        self.conn.commit()
        return findings

    def close_run(self, run_id: str, summary: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = 'completed', summary = ? WHERE run_id = ?",
            (now_iso(), json.dumps(summary), run_id),
        )
        self.conn.commit()

    def fail_run(self, run_id: str) -> None:
        """Mark a run as failed (docs/vulnerability-ledger.md runs.status = 'failed')."""
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = 'failed' WHERE run_id = ?",
            (now_iso(), run_id),
        )
        self.conn.commit()

    # -- read -------------------------------------------------------------------

    def query(self, **filters) -> list[Finding]:
        # ``engine`` is not a findings column — it lives on the parent run, so it
        # filters via a join on runs.engine_name (docs/vulnerability-ledger.md).
        engine = filters.get("engine") or filters.get("engine_name")
        model = filters.get("model")
        clauses, params = [], []
        for column in _FILTERABLE:
            if filters.get(column) is not None:
                clauses.append(f"f.{column} = ?")
                params.append(filters[column])
        if engine is not None:
            clauses.append("r.engine_name = ?")
            params.append(engine)
            sql = "SELECT f.* FROM findings f JOIN runs r ON f.run_id = r.run_id"
        else:
            sql = "SELECT f.* FROM findings f"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY f.created_at DESC, f.finding_id"
        rows = self.conn.execute(sql, params).fetchall()
        findings = [_row_to_finding(row) for row in rows]
        if model is not None:
            # ``model`` is stamped into the repro JSON (not a column), so filter post-hoc.
            findings = [f for f in findings if (f.repro or {}).get("model") == model]
        return findings

    def get_finding(self, finding_id: str) -> Finding | None:
        row = self.conn.execute("SELECT * FROM findings WHERE finding_id = ?", (finding_id,)).fetchone()
        return _row_to_finding(row) if row else None

    def delete_ids(self, ids: list[str]) -> int:
        """Permanently delete findings by id; returns the number of rows removed.

        This is a hard delete (the auditable status lifecycle — false_positive /
        accepted_risk — is the *non*-destructive path). The backend exposes it so an
        operator can purge a filtered set of findings from the ledger.
        """
        ids = [i for i in ids if i]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"DELETE FROM findings WHERE finding_id IN ({placeholders})", ids
        )
        self.conn.commit()
        return cur.rowcount

    def list_runs(self, tile_id: str | None = None, limit: int = 100) -> list[dict]:
        sql, params = "SELECT * FROM runs", []
        if tile_id:
            sql += " WHERE tile_id = ?"
            params.append(tile_id)
        sql += " ORDER BY started_at DESC, run_id LIMIT ?"
        params.append(limit)
        return [self._run_row(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        if data.get("summary"):
            try:
                data["summary"] = json.loads(data["summary"])
            except (TypeError, ValueError):
                pass
        return data

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _fingerprint(result: ProbeResult) -> str:
    """Stable hash(tile_id, vector_id, normalized_signal). The normalized signal is
    a value-stable bucket (e.g. rounded score-delta /10) so incidental float noise
    does not change identity, but the same attack on different tiles stays distinct."""
    if result.metric_value is not None:
        signal = str(int(result.metric_value // 10))
    else:
        signal = "match"
    return short_hash(result.tile_id, result.vector_id, signal, length=16)


def _row_to_finding(row: sqlite3.Row) -> Finding:
    return Finding(
        id=row["finding_id"], run_id=row["run_id"], tile_id=row["tile_id"],
        vector_id=row["vector_id"], category=row["category"], severity=row["severity"],
        status=row["status"], repro=json.loads(row["repro_detail"] or "{}"),
        evidence=json.loads(row["evidence"] or "{}"),
        mitigation_guidance=row["mitigation_guidance"] or "", owasp_ref=row["owasp_ref"],
        cwe=row["cwe"], fingerprint=row["fingerprint"], created_at=row["created_at"],
    )
