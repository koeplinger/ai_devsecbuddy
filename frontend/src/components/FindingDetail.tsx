import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import type { Finding } from '../types';
import { CategoryBadge, SeverityBadge } from './Badge';
import { FindingExecSummary } from './FindingExecSummary';

export function FindingDetail({
  findingId,
  onClose,
}: {
  findingId: string;
  onClose: () => void;
}) {
  const [finding, setFinding] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLElement>(null);

  // Move focus into the dialog on open and restore it to the trigger on close,
  // so a keyboard/AT user is not left focused behind the aria-modal overlay.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => previouslyFocused?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setFinding(null);
    setError(null);
    api
      .getFinding(findingId)
      .then((f) => {
        if (!cancelled) setFinding(f);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [findingId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside
        className="drawer"
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Finding detail"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-head">
          <h3>Finding</h3>
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {error && <div className="error">⚠ {error}</div>}
        {!finding && !error && <p className="empty">Loading…</p>}

        {finding && (
          <div className="drawer-body">
            <div className="kv-row">
              <SeverityBadge severity={finding.severity} />
              <CategoryBadge category={finding.category} />
              <span className="pill pill-neutral">{finding.status}</span>
            </div>

            <FindingExecSummary finding={finding} />

            <dl className="kv">
              <dt>Finding id</dt>
              <dd>
                <code>{finding.id}</code>
              </dd>
              <dt>Vector</dt>
              <dd>
                <code>{finding.vector_id}</code>
              </dd>
              <dt>Tile</dt>
              <dd>
                <code>{finding.tile_id}</code>
              </dd>
              <dt>OWASP / CWE</dt>
              <dd>
                {finding.owasp_ref}
                {finding.cwe ? ` · ${finding.cwe}` : ''}
              </dd>
              <dt>Detected</dt>
              <dd>{finding.created_at}</dd>
            </dl>

            <h4>Detection detail</h4>
            <p>{finding.detail}</p>

            <h4>Mitigation guidance</h4>
            <p className="mitigation">{finding.mitigation_guidance}</p>

            {finding.repro && (
              <>
                <h4>Reproduction</h4>
                <pre className="code">{JSON.stringify(finding.repro, null, 2)}</pre>
              </>
            )}
            {finding.evidence && (
              <>
                <h4>Evidence</h4>
                <pre className="code">{JSON.stringify(finding.evidence, null, 2)}</pre>
              </>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
