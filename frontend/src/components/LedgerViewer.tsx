import { useEffect, useState } from 'react';
import type { ChangeEvent } from 'react';
import { api, ApiError } from '../api';
import type { Finding, FindingFilters, Tile } from '../types';
import { LedgerTable } from './LedgerTable';
import { ConfirmModal } from './ConfirmModal';

const CATEGORIES = ['prompt_injection', 'modal_jailbreak', 'data_exfiltration', 'bias_fairness'];
const SEVERITIES = ['info', 'low', 'medium', 'high', 'critical'];
const STATUSES = ['open', 'triaged', 'mitigated', 'accepted_risk', 'false_positive'];

interface Props {
  tiles: Tile[];
  engineNames: string[];
  modelNames: string[];
  defaultEngine: string;
  refreshKey: number;
  onOpenFinding: (id: string) => void;
}

export function LedgerViewer({
  tiles,
  engineNames,
  modelNames,
  defaultEngine,
  refreshKey,
  onOpenFinding,
}: Props) {
  // The engine filter defaults to whatever engine is selected on the "Tiles & runs"
  // tab, so the ledger opens showing the same engine's findings.
  const [filters, setFilters] = useState<FindingFilters>({ engine: defaultEngine || undefined });
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  // Snapshot of the ids to delete, captured when the user clicks Delete — so a filter
  // change while the modal is open can't drift the count shown from the rows deleted.
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
  }, [filters, refreshKey, reload]);

  const set = (key: keyof FindingFilters) => (e: ChangeEvent<HTMLSelectElement>) =>
    setFilters((prev) => ({ ...prev, [key]: e.target.value || undefined }));

  const onConfirmDelete = () => {
    if (!pendingIds) return;
    setDeleting(true);
    setDeleteError(null);
    api
      .deleteFindings(pendingIds)
      .then(() => {
        setPendingIds(null);
        setReload((k) => k + 1); // re-fetch the (now-empty for these filters) ledger
      })
      .catch((e: unknown) => {
        setDeleteError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => setDeleting(false));
  };

  const count = findings.length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Vulnerability ledger</h2>
        <span className="count">
          {count} finding{count === 1 ? '' : 's'}
        </span>
      </div>
      <div className="filters">
        <Filter label="Engine" value={filters.engine} onChange={set('engine')} options={engineNames} />
        <Filter label="Model" value={filters.model} onChange={set('model')} options={modelNames} />
        <Filter label="Tile" value={filters.tile_id} onChange={set('tile_id')} options={tiles.map((t) => t.tile_id)} />
        <Filter label="Category" value={filters.category} onChange={set('category')} options={CATEGORIES} />
        <Filter label="Severity" value={filters.severity} onChange={set('severity')} options={SEVERITIES} />
        <Filter label="Status" value={filters.status} onChange={set('status')} options={STATUSES} />
        <button className="btn ghost" onClick={() => setFilters({})}>
          Clear filters
        </button>
        <button
          className="btn danger-ghost"
          onClick={() => {
            setDeleteError(null);
            setPendingIds(findings.map((f) => f.id)); // snapshot exactly what's shown now
          }}
          disabled={count === 0 || loading || !!error}
          title={count === 0 ? 'No findings to delete' : 'Permanently delete the findings shown'}
        >
          Delete{count > 0 ? ` (${count})` : ''}
        </button>
      </div>
      {error && <div className="error">⚠ {error}</div>}
      {loading ? <p className="empty">Loading…</p> : <LedgerTable findings={findings} onOpen={onOpenFinding} />}

      {pendingIds !== null && (
        <ConfirmModal
          title={`Delete ${pendingIds.length} finding${pendingIds.length === 1 ? '' : 's'}?`}
          confirmLabel={deleting ? 'Deleting…' : 'Delete permanently'}
          danger
          busy={deleting}
          error={deleteError}
          onCancel={() => setPendingIds(null)}
          onConfirm={onConfirmDelete}
        >
          This permanently removes{' '}
          {pendingIds.length === 1
            ? 'this finding'
            : `all ${pendingIds.length} findings currently shown`}{' '}
          from the vulnerability ledger. This cannot be undone.
        </ConfirmModal>
      )}
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
