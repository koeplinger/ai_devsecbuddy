import { useEffect, useState } from 'react';
import type { ChangeEvent } from 'react';
import { api, ApiError } from '../api';
import type { Finding, FindingFilters, Tile } from '../types';
import { FindingsTable } from './FindingsTable';

const CATEGORIES = ['prompt_injection', 'modal_jailbreak', 'data_exfiltration', 'bias_fairness'];
const SEVERITIES = ['info', 'low', 'medium', 'high', 'critical'];
const STATUSES = ['open', 'triaged', 'mitigated', 'accepted_risk', 'false_positive'];

interface Props {
  tiles: Tile[];
  engineNames: string[];
  defaultEngine: string;
  refreshKey: number;
  onOpenFinding: (id: string) => void;
}

export function LedgerViewer({ tiles, engineNames, defaultEngine, refreshKey, onOpenFinding }: Props) {
  // The engine filter defaults to whatever engine is selected on the "Tiles & runs"
  // tab, so the ledger opens showing the same engine's findings.
  const [filters, setFilters] = useState<FindingFilters>({ engine: defaultEngine || undefined });
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep the engine filter tracking the Tiles-tab selection as it changes. Return
  // the same state object when nothing changes, so this doesn't trigger a re-fetch.
  useEffect(() => {
    const engine = defaultEngine || undefined;
    setFilters((prev) => (prev.engine === engine ? prev : { ...prev, engine }));
  }, [defaultEngine]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listFindings(filters)
      .then((f) => {
        if (!cancelled) setFindings(f);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters, refreshKey]);

  const set = (key: keyof FindingFilters) => (e: ChangeEvent<HTMLSelectElement>) =>
    setFilters((prev) => ({ ...prev, [key]: e.target.value || undefined }));

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Vulnerability ledger</h2>
        <span className="count">
          {findings.length} finding{findings.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="filters">
        <Filter label="Engine" value={filters.engine} onChange={set('engine')} options={engineNames} />
        <Filter label="Tile" value={filters.tile_id} onChange={set('tile_id')} options={tiles.map((t) => t.tile_id)} />
        <Filter label="Category" value={filters.category} onChange={set('category')} options={CATEGORIES} />
        <Filter label="Severity" value={filters.severity} onChange={set('severity')} options={SEVERITIES} />
        <Filter label="Status" value={filters.status} onChange={set('status')} options={STATUSES} />
        <button className="btn ghost" onClick={() => setFilters({ engine: defaultEngine || undefined })}>
          Clear filters
        </button>
      </div>
      {error && <div className="error">⚠ {error}</div>}
      {loading ? <p className="empty">Loading…</p> : <FindingsTable findings={findings} onOpen={onOpenFinding} />}
    </section>
  );
}

function Filter({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string | undefined;
  onChange: (e: ChangeEvent<HTMLSelectElement>) => void;
  options: string[];
}) {
  return (
    <label className="filter">
      {label}
      <select value={value ?? ''} onChange={onChange}>
        <option value="">all</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
