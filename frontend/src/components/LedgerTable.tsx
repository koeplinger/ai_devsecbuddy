import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Finding } from '../types';
import { CategoryBadge, SeverityBadge } from './Badge';

// Severity sorts by rank (info < low < … < critical), not alphabetically.
const SEVERITY_RANK = ['info', 'low', 'medium', 'high', 'critical'];

type SortDir = 'asc' | 'desc';
interface SortKey {
  key: string;
  dir: SortDir;
}

interface Column {
  key: string;
  label: string;
  cellClass?: string;
  render: (f: Finding) => ReactNode;
  sortValue: (f: Finding) => string | number;
}

// Column order intentionally mirrors the ledger filter order (Engine, Tile, Category,
// Severity, Status), with Model first and the non-filter columns after.
const COLUMNS: Column[] = [
  {
    key: 'model',
    label: 'Model',
    render: (f) => <code>{f.model ?? '—'}</code>,
    sortValue: (f) => (f.model ?? '').toLowerCase(),
  },
  {
    key: 'engine',
    label: 'Engine',
    render: (f) => <code>{f.engine ?? '—'}</code>,
    sortValue: (f) => (f.engine ?? '').toLowerCase(),
  },
  {
    key: 'tile',
    label: 'Tile',
    render: (f) => <code>{f.tile_id}</code>,
    sortValue: (f) => f.tile_id.toLowerCase(),
  },
  {
    key: 'category',
    label: 'Category',
    render: (f) => <CategoryBadge category={f.category} />,
    sortValue: (f) => f.category,
  },
  {
    key: 'severity',
    label: 'Severity',
    render: (f) => <SeverityBadge severity={f.severity} />,
    sortValue: (f) => SEVERITY_RANK.indexOf(f.severity),
  },
  {
    key: 'status',
    label: 'Status',
    render: (f) => <span className="badge category">{f.status}</span>,
    sortValue: (f) => f.status,
  },
  {
    key: 'owasp',
    label: 'OWASP / CWE',
    render: (f) => (
      <>
        {f.owasp_ref}
        {f.cwe ? ` · ${f.cwe}` : ''}
      </>
    ),
    sortValue: (f) => `${f.owasp_ref} ${f.cwe ?? ''}`.toLowerCase(),
  },
  {
    key: 'vector',
    label: 'Vector',
    render: (f) => <code>{f.vector_id}</code>,
    sortValue: (f) => f.vector_id.toLowerCase(),
  },
  {
    key: 'detail',
    label: 'Detail',
    cellClass: 'detail-cell',
    render: (f) => f.detail,
    sortValue: (f) => f.detail.toLowerCase(),
  },
];

const COLS_BY_KEY = Object.fromEntries(COLUMNS.map((c) => [c.key, c]));

export function LedgerTable({
  findings,
  onOpen,
}: {
  findings: Finding[];
  onOpen: (id: string) => void;
}) {
  // Sort keys, most-recent-first: clicking a header makes it primary and keeps the
  // previously chosen columns as secondary, tertiary, … in reverse-chronological order.
  const [sortKeys, setSortKeys] = useState<SortKey[]>([]);

  const onSort = (key: string) =>
    setSortKeys((prev) => {
      const existing = prev.find((s) => s.key === key);
      const dir: SortDir = existing ? (existing.dir === 'asc' ? 'desc' : 'asc') : 'asc';
      return [{ key, dir }, ...prev.filter((s) => s.key !== key)];
    });

  const sorted = useMemo(() => {
    if (sortKeys.length === 0) return findings;
    return [...findings].sort((a, b) => {
      for (const { key, dir } of sortKeys) {
        const col = COLS_BY_KEY[key];
        if (!col) continue;
        const av = col.sortValue(a);
        const bv = col.sortValue(b);
        let c: number;
        if (typeof av === 'number' && typeof bv === 'number') c = av - bv;
        else c = String(av).localeCompare(String(bv));
        if (c !== 0) return dir === 'asc' ? c : -c;
      }
      return 0; // stable: equal under all keys keeps insertion order
    });
  }, [findings, sortKeys]);

  if (findings.length === 0) {
    return <p className="empty">No findings — guardrails held against every probe.</p>;
  }

  return (
    <div className="table-wrap">
      <table className="findings">
        <thead>
          <tr>
            {COLUMNS.map((col) => {
              const idx = sortKeys.findIndex((s) => s.key === col.key);
              const active = idx >= 0;
              return (
                <th
                  key={col.key}
                  aria-sort={active ? (sortKeys[idx].dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  <button
                    type="button"
                    className={`sort-th${active ? ' active' : ''}`}
                    onClick={() => onSort(col.key)}
                    title={`Sort by ${col.label}`}
                  >
                    {col.label}
                    {active && (
                      <span className="sort-ind" aria-hidden="true">
                        {sortKeys[idx].dir === 'asc' ? '▲' : '▼'}
                        {sortKeys.length > 1 && <sup>{idx + 1}</sup>}
                      </span>
                    )}
                  </button>
                </th>
              );
            })}
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((f) => (
            <tr key={f.id} className="row-click" onClick={() => onOpen(f.id)}>
              {COLUMNS.map((col) => (
                <td key={col.key} className={col.cellClass}>
                  {col.render(f)}
                </td>
              ))}
              <td className="row-action">
                <button
                  className="btn ghost row-open"
                  aria-label={`Open finding ${f.vector_id} on ${f.tile_id} from ${f.model ?? '—'}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpen(f.id);
                  }}
                >
                  View
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
