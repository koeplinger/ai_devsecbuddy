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
  refreshKey: number;
  onOpenFinding: (id: string) => void;
}

export function LedgerViewer({ tiles, refreshKey, onOpenFinding }: Props) {
  const [filters, setFilters] = useState<FindingFilters>({});
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <Filter label="Tile" value={filters.tile_id} onChange={set('tile_id')} options={tiles.map((t) => t.tile_id)} />
        <Filter label="Category" value={filters.category} onChange={set('category')} options={CATEGORIES} />
        <Filter label="Severity" value={filters.severity} onChange={set('severity')} options={SEVERITIES} />
        <Filter label="Status" value={filters.status} onChange={set('status')} options={STATUSES} />
        <button className="btn ghost" onClick={() => setFilters({})}>
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
