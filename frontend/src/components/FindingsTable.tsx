import type { Finding } from '../types';
import { CategoryBadge, SeverityBadge } from './Badge';

export function FindingsTable({
  findings,
  onOpen,
}: {
  findings: Finding[];
  onOpen: (id: string) => void;
}) {
  if (findings.length === 0) {
    return <p className="empty">No findings — guardrails held against every probe.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="findings">
        <thead>
          <tr>
            <th>Severity</th>
            <th>Category</th>
            <th>OWASP / CWE</th>
            <th>Vector</th>
            <th>Tile</th>
            <th>Detail</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {findings.map((f) => (
            <tr key={f.id} className="row-click" onClick={() => onOpen(f.id)}>
              <td>
                <SeverityBadge severity={f.severity} />
              </td>
              <td>
                <CategoryBadge category={f.category} />
              </td>
              <td>
                {f.owasp_ref}
                {f.cwe ? ` · ${f.cwe}` : ''}
              </td>
              <td>
                <code>{f.vector_id}</code>
              </td>
              <td>
                <code>{f.tile_id}</code>
              </td>
              <td className="detail-cell">{f.detail}</td>
              <td className="row-action">
                <button
                  className="btn ghost row-open"
                  aria-label={`Open finding ${f.vector_id} on ${f.tile_id}`}
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
