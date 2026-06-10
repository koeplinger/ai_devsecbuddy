import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent } from 'react';
import { api, ApiError } from '../api';
import type { Finding, FindingFilters } from '../types';
import { LedgerTable } from './LedgerTable';
import { ConfirmModal } from './ConfirmModal';

// The six filterable dimensions, each mapping a finding to its value for that filter.
type DimKey = 'engine' | 'model' | 'tile_id' | 'category' | 'severity' | 'status';
const DIMENSIONS: { key: DimKey; label: string; get: (f: Finding) => string }[] = [
  { key: 'engine', label: 'Engine', get: (f) => f.engine ?? '' },
  { key: 'model', label: 'Model', get: (f) => f.model ?? '' },
  { key: 'tile_id', label: 'Tile', get: (f) => f.tile_id },
  { key: 'category', label: 'Category', get: (f) => f.category },
  { key: 'severity', label: 'Severity', get: (f) => f.severity },
  { key: 'status', label: 'Status', get: (f) => f.status },
];
const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'];

function matchesExcept(f: Finding, filters: FindingFilters, except?: DimKey): boolean {
  return DIMENSIONS.every((d) => {
    if (d.key === except) return true;
    const v = filters[d.key];
    return !v || d.get(f) === v;
  });
}

// Distinct values of `key` among findings matching every OTHER active filter — i.e. the
// selections that would NOT produce an empty result. Sorted (severity by rank, else alpha).
function valuesFor(findings: Finding[], filters: FindingFilters, key: DimKey): string[] {
  const dim = DIMENSIONS.find((d) => d.key === key)!;
  const set = new Set<string>();
  for (const f of findings) {
    if (matchesExcept(f, filters, key)) {
      const v = dim.get(f);
      if (v) set.add(v);
    }
  }
  return [...set].sort(
    key === 'severity'
      ? (a, b) => SEVERITY_ORDER.indexOf(a) - SEVERITY_ORDER.indexOf(b)
      : (a, b) => a.localeCompare(b),
  );
}

function sameFilters(a: FindingFilters, b: FindingFilters): boolean {
  return DIMENSIONS.every((d) => (a[d.key] || undefined) === (b[d.key] || undefined));
}

interface Props {
  defaultEngine: string;
  refreshKey: number;
  onOpenFinding: (id: string) => void;
}

export function LedgerViewer({ defaultEngine, refreshKey, onOpenFinding }: Props) {
  // The engine filter defaults to whatever engine is selected on the "Tiles & runs" tab.
  const [filters, setFilters] = useState<FindingFilters>({ engine: defaultEngine || undefined });
  const [allFindings, setAllFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  // Snapshot of the ids to delete, captured when the user clicks Delete.
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Keep the engine filter tracking the Tiles-tab selection as it changes.
  useEffect(() => {
    const engine = defaultEngine || undefined;
    setFilters((prev) => (prev.engine === engine ? prev : { ...prev, engine }));
  }, [defaultEngine]);

  // Fetch the WHOLE ledger once (and on run-complete / delete). Filtering + faceting is
  // client-side so the dropdowns can reflect exactly what's present.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listFindings({})
      .then((f) => {
        if (!cancelled) setAllFindings(f);
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
  }, [refreshKey, reload]);

  // Drop any selection that's impossible given the others (a default-engine preselect with
  // no findings, or a selection invalidated by new data). Iterates to a fixed point;
  // relaxing only ever adds findings, so it converges. Skipped until data has loaded.
  const effective = useMemo<FindingFilters>(() => {
    if (allFindings.length === 0) return filters;
    const f: FindingFilters = { ...filters };
    for (let pass = 0; pass <= DIMENSIONS.length; pass++) {
      let changed = false;
      for (const d of DIMENSIONS) {
        const v = f[d.key];
        if (v && !valuesFor(allFindings, f, d.key).includes(v)) {
          delete f[d.key];
          changed = true;
        }
      }
      if (!changed) break;
    }
    return f;
  }, [allFindings, filters]);

  useEffect(() => {
    if (!sameFilters(effective, filters)) setFilters(effective);
  }, [effective, filters]);

  // Per-dimension options possible given the OTHER (reconciled) selections.
  const available = useMemo(() => {
    const m = {} as Record<DimKey, string[]>;
    for (const d of DIMENSIONS) m[d.key] = valuesFor(allFindings, effective, d.key);
    return m;
  }, [allFindings, effective]);

  const filtered = useMemo(
    () => allFindings.filter((f) => matchesExcept(f, effective)),
    [allFindings, effective],
  );

  const set = (key: DimKey) => (e: ChangeEvent<HTMLSelectElement>) =>
    setFilters((prev) => ({ ...prev, [key]: e.target.value || undefined }));

  const onConfirmDelete = () => {
    if (!pendingIds) return;
    setDeleting(true);
    setDeleteError(null);
    api
      .deleteFindings(pendingIds)
      .then(() => {
        setPendingIds(null);
        setReload((k) => k + 1); // re-fetch the ledger
      })
      .catch((e: unknown) => {
        setDeleteError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => setDeleting(false));
  };

  const count = filtered.length;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Vulnerability ledger</h2>
        <span className="count">
          {count} finding{count === 1 ? '' : 's'}
        </span>
      </div>
      <div className="filters">
        {DIMENSIONS.map((d) => {
          const opts = available[d.key];
          if (opts.length === 0) return null; // no possible value here — hide the filter
          if (opts.length === 1) {
            // only one value possible given the others — show it fixed, not as a dropdown
            return (
              <span key={d.key} className="filter filter-fixed">
                {d.label}
                <strong>{opts[0]}</strong>
              </span>
            );
          }
          return (
            <Filter
              key={d.key}
              label={d.label}
              value={effective[d.key]}
              onChange={set(d.key)}
              options={opts}
            />
          );
        })}
        <button className="btn ghost" onClick={() => setFilters({})}>
          Clear filters
        </button>
        <button
          className="btn danger-ghost"
          onClick={() => {
            setDeleteError(null);
            setPendingIds(filtered.map((f) => f.id)); // snapshot exactly what's shown now
          }}
          disabled={count === 0 || loading || !!error}
          title={count === 0 ? 'No findings to delete' : 'Permanently delete the findings shown'}
        >
          Delete{count > 0 ? ` (${count})` : ''}
        </button>
      </div>
      {error && <div className="error">⚠ {error}</div>}
      {loading ? (
        <p className="empty">Loading…</p>
      ) : (
        <LedgerTable findings={filtered} onOpen={onOpenFinding} />
      )}

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
