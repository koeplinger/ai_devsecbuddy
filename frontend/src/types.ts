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

// A sample resume in the clean corpus the app probes against (CRUD via /resumes).
// gender + ethnicity are demographic labels used for counterfactual bias pairing.
export interface Resume {
  id: string;
  applicant_name: string;
  resume_text: string;
  gender: string;
  ethnicity: string;
  created_at: string;
  updated_at: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  // Catalogs are ordered cheapest -> most expensive; there is no tier label.
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
  models?: ModelInfo[]; // selectable models, ordered cheapest -> priciest
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
  unscorable?: number; // probes the model couldn't be scored for (unusable response) — not vulns
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
  model?: string;
}

// ---- streaming run progress (NDJSON events from POST /runs/stream) ----
// One event per line; the backend emits these as run_assessment progresses
// (devsecbuddy/runner.py + prober.py). The frontend renders them live, per tile.
export type RunEvent =
  | {
      type: 'queued';
      id: string;
      position: number;
      tile_id?: string;
      engine_name?: string;
      model?: string;
    }
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
  | { type: 'learning'; index: number; total: number; name: string }
  | { type: 'name_swap'; axis: string; from: string; to: string; interest?: string }
  | { type: 'probe_target'; vector_id: string; name: string }
  | { type: 'rate_limited'; attempt: number; wait_s: number; remaining_s: number; engine?: string }
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
  | { type: 'error'; kind?: string; message: string }
  | { type: 'cancelled'; id?: string; reason: 'removed_from_queue' | 'force_stopped' };

// Per-tile run state the UI keeps for the run console (one entry per tile that
// has been run this session). Multiple tiles can be 'running' at once.
export interface TileRun {
  tileId: string;
  tileName: string;
  engine: string;
  model: string;
  // queued: waiting its turn (runs are serialized); running: executing; cancelled:
  // removed from queue or force-stopped.
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  startedAt: number;
  // backend job id (from the 'queued' event) — used to cancel / force-stop this run
  jobId?: string;
  // 1-based position while queued (1 = next to run)
  queuePosition?: number;
  // set while the scorer is paused on a rate-limit (429), with a live retry countdown
  rateLimit?: { attempt: number; remaining_s: number; wait_s: number };
  // human-readable progress log lines, appended as events arrive
  lines: string[];
  // the in-flight probe, for a live "x/total running…" indicator
  current?: { index: number; total: number; label: string };
  totalProbes?: number;
  result?: RunResult;
  error?: string;
}
