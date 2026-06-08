// TypeScript shapes mirroring the M2 backend payloads (see backend/service.py,
// devsecbuddy/models.py, docs/vulnerability-ledger.md). The frontend holds no
// security or engine logic — it only renders what the run/report API returns.

export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type Category =
  | 'prompt_injection'
  | 'modal_jailbreak'
  | 'data_exfiltration'
  | 'bias_fairness';

export interface Tile {
  tile_id: string;
  name: string;
  description: string;
  input_fields: string[];
  output_schema: Record<string, string>;
  guardrails: string[];
}

export interface ModelInfo {
  id: string;
  tier: string; // low | mid | high | n/a
  label: string;
}

export interface EngineInfo {
  name: string;
  implemented?: boolean;
  configured?: boolean;
  deterministic?: boolean;
  default?: boolean;
  offline?: boolean;
  provider?: string;
  model?: string; // the engine's default/current model id
  models?: ModelInfo[]; // selectable models (low -> high tier)
  requires?: string[];
  roadmap?: string;
}

export interface Finding {
  id: string;
  run_id: string;
  tile_id: string;
  vector_id: string;
  category: string;
  severity: string;
  status: string;
  owasp_ref: string;
  cwe: string | null;
  fingerprint: string;
  created_at: string;
  mitigation_guidance: string;
  metric_value: number | null;
  detail: string;
  engine?: string | null; // engine that produced the finding (mock | anthropic | vertex)
  model?: string | null; // model id (e.g. gemini-2.5-flash, claude-haiku-4-5)
  // present only on GET /findings/{id}
  repro?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
}

export interface RunSummary {
  probes_run: number;
  vulnerabilities_found: number;
  probes_passed: number;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
}

// POST /runs response
export interface RunResult {
  run_id: string;
  tile_id: string;
  engine_name: string;
  summary: RunSummary;
  findings: Finding[];
}

// GET /runs and GET /runs/{id}
export interface RunRow {
  run_id: string;
  tile_id: string;
  engine_name: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  summary: RunSummary | null;
  findings?: Finding[];
}

export interface Health {
  status: string;
  default_engine: string;
  default_engine_known: boolean;
  db: string;
}

export interface FindingFilters {
  tile_id?: string;
  category?: string;
  severity?: string;
  status?: string;
  owasp_ref?: string;
  vector_id?: string;
  engine?: string;
}

// ---- streaming run progress (NDJSON events from POST /runs/stream) ----
// One event per line; the backend emits these as run_assessment progresses
// (devsecbuddy/runner.py + prober.py). The frontend renders them live, per tile.
export type RunEvent =
  | { type: 'run_started'; run_id: string; tile_id: string; engine_name: string; total_probes: number }
  | { type: 'phase'; phase: 'baseline' | 'probing' | 'reporting' }
  | { type: 'baseline_done'; sample_count: number }
  | {
      type: 'probe_started';
      index: number;
      total: number;
      vector_id: string;
      category: string;
      severity: string;
    }
  | {
      type: 'probe_done';
      index: number;
      total: number;
      vector_id: string;
      category: string;
      success: boolean;
      severity: string;
      detail: string;
    }
  | {
      type: 'result';
      run_id: string;
      tile_id: string;
      engine_name: string;
      summary: RunSummary;
      findings: Finding[];
    }
  | { type: 'error'; kind?: string; message: string };

// Per-tile run state the UI keeps for the run console (one entry per tile that
// has been run this session). Multiple tiles can be 'running' at once.
export interface TileRun {
  tileId: string;
  tileName: string;
  engine: string;
  model: string;
  status: 'running' | 'done' | 'error';
  startedAt: number;
  // human-readable progress log lines, appended as events arrive
  lines: string[];
  // the in-flight probe, for a live "x/total running…" indicator
  current?: { index: number; total: number; label: string };
  totalProbes?: number;
  result?: RunResult;
  error?: string;
}
