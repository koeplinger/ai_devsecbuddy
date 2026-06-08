import { useEffect, useRef } from 'react';
import type { TileRun } from '../types';
import { FindingsTable } from './FindingsTable';

interface Props {
  runs: TileRun[];
  onOpenFinding: (id: string) => void;
  onDismiss: (tileId: string) => void;
}

export function RunConsole({ runs, onOpenFinding, onDismiss }: Props) {
  const runningCount = runs.filter((r) => r.status === 'running').length;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Run console</h2>
        {runs.length > 0 && (
          <span className="count">
            {runningCount > 0 ? `${runningCount} running · ` : ''}
            {runs.length} tile{runs.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {runs.length === 0 ? (
        <p className="empty">
          Pick a tile above and run an assessment to see live progress here. You can run several
          tiles at once — each gets its own panel.
        </p>
      ) : (
        <div className="run-cards">
          {runs.map((run) => (
            <RunCard
              key={run.tileId}
              run={run}
              onOpenFinding={onOpenFinding}
              onDismiss={onDismiss}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function RunCard({
  run,
  onOpenFinding,
  onDismiss,
}: {
  run: TileRun;
  onOpenFinding: (id: string) => void;
  onDismiss: (tileId: string) => void;
}) {
  const logRef = useRef<HTMLPreElement | null>(null);
  // Keep the live log pinned to the newest line.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run.lines]);

  const statusLabel =
    run.status === 'running' ? 'running' : run.status === 'done' ? 'complete' : 'error';

  return (
    <article className={`run-card run-${run.status}`}>
      <header className="run-card-head">
        <div className="run-card-title">
          <span className={`run-status run-status-${run.status}`}>
            {run.status === 'running' && <span className="spinner" aria-hidden="true" />}
            {statusLabel}
          </span>
          <strong>{run.tileName}</strong>
          <span className="badge category">{run.engine}</span>
        </div>
        <button
          className="btn ghost run-dismiss"
          onClick={() => onDismiss(run.tileId)}
          title={run.status === 'running' ? 'Stop & dismiss' : 'Dismiss'}
          aria-label={`Dismiss run for ${run.tileName}`}
        >
          ✕
        </button>
      </header>

      {run.status === 'running' && run.current && (
        <p className="run-current">
          Probe {run.current.index}/{run.current.total}:{' '}
          <code>{run.current.label}</code> running…
        </p>
      )}

      <pre
        className="run-log"
        ref={logRef}
        role="log"
        aria-live="polite"
        aria-atomic="false"
        aria-label={`Progress log for ${run.tileName}`}
      >
        {run.lines.join('\n')}
      </pre>

      {run.status === 'error' && run.error && <div className="error">⚠ {run.error}</div>}

      {run.status === 'done' && run.result && (
        <div className="run-result">
          <div className="summary">
            <Stat label="Probes" value={String(run.result.summary.probes_run)} />
            <Stat
              label="Vulnerabilities"
              value={String(run.result.summary.vulnerabilities_found)}
              tone={run.result.summary.vulnerabilities_found > 0 ? 'danger' : 'ok'}
            />
            <Stat label="Passed" value={String(run.result.summary.probes_passed)} tone="ok" />
          </div>
          <p className="run-id">
            run <code>{run.result.run_id}</code>
          </p>
          <FindingsTable findings={run.result.findings} onOpen={onOpenFinding} />
        </div>
      )}
    </article>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ''}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
