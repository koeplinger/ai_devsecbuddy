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

export interface EngineInfo {
  name: string;
  implemented?: boolean;
  deterministic?: boolean;
  default?: boolean;
  offline?: boolean;
  provider?: string;
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
}
