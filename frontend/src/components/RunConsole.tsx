import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { CallStats, TileRun } from '../types';
import { FindingsTable } from './FindingsTable';
import { LogModal } from './LogModal';

interface Props {
  runs: TileRun[];
  onOpenFinding: (id: string) => void;
  // The card's ✕ — App overloads it by run state (remove-from-queue / force-stop / dismiss).
  onClose: (run: TileRun) => void;
}

export function RunConsole({ runs, onOpenFinding, onClose }: Props) {
  const runningCount = runs.filter((r) => r.status === 'running').length;
  const queuedCount = runs.filter((r) => r.status === 'queued').length;

  // AI-model-call stats: fetch on mount + whenever a scoring is active (running or queued),
  // poll every second; when idle the last snapshot stays on screen.
  const active = runs.some((r) => r.status === 'running' || r.status === 'queued');
  const [stats, setStats] = useState<CallStats | null>(null);
  useEffect(() => {
    let cancelled = false;
    const refresh = () =>
      api.telemetry().then((s) => !cancelled && setStats(s)).catch(() => {});
    refresh();
    if (!active) return () => { cancelled = true; };
    const id = window.setInterval(refresh, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [active]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Run console</h2>
        {runs.length > 0 && (
          <span className="count">
            {runningCount > 0 ? `${runningCount} running · ` : ''}
            {queuedCount > 0 ? `${queuedCount} queued · ` : ''}
            {runs.length} tile{runs.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {runs.length === 0 ? (
        <p className="empty">(start assessment above)</p>
      ) : (
        <div className="run-cards">
          {runs.map((run) => (
            <RunCard
              key={run.tileId}
              run={run}
              onOpenFinding={onOpenFinding}
              onClose={onClose}
            />
          ))}
        </div>
      )}

      {stats && <CallStatsBar stats={stats} active={active} />}
    </section>
  );
}

function fmtMs(ms: number | null): string {
  if (ms == null) return '—';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function fmtTotal(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60000);
  const s = Math.round((ms % 60000) / 1000);
  return `${m}m ${s}s`;
}

function CallStatsBar({ stats, active }: { stats: CallStats; active: boolean }) {
  const last =
    fmtMs(stats.last_ms) +
    (stats.last_engine ? ` · ${stats.last_engine}/${stats.last_model ?? '?'}` : '');
  return (
    <dl className={`call-stats${active ? ' live' : ''}`} aria-label="AI model call stats">
      <div>
        <dt>
          AI calls{active && <span className="live-dot" title="refreshing live" />}
        </dt>
        <dd>{stats.count.toLocaleString()}</dd>
      </div>
      <div>
        <dt>Total time</dt>
        <dd>
          {fmtTotal(stats.total_ms)} <span className="muted">· avg {fmtMs(stats.avg_ms)}</span>
        </dd>
      </div>
      <div>
        <dt>EMA / call</dt>
        <dd>
          {fmtMs(stats.ema_90_ms)} <span className="muted">(90%)</span> · {fmtMs(stats.ema_70_ms)}{' '}
          <span className="muted">(70%)</span>
        </dd>
      </div>
      <div>
        <dt>Last call</dt>
        <dd>{last}</dd>
      </div>
    </dl>
  );
}

function RunCard({
  run,
  onOpenFinding,
  onClose,
}: {
  run: TileRun;
  onOpenFinding: (id: string) => void;
  onClose: (run: TileRun) => void;
}) {
  const logRef = useRef<HTMLPreElement | null>(null);
  // Details are shown live while a run is in flight; once it completes they collapse
  // behind a "Show details" pill in the summary row.
  const [expanded, setExpanded] = useState(false);
  // "Show full" opens the whole log in a large-screen modal (the inline box is fixed-height).
  const [fullOpen, setFullOpen] = useState(false);
  // Show the live log for every non-completed state; a completed card collapses it
  // behind the Show/Hide details toggle.
  const showLog = run.status === 'done' ? expanded : true;

  // Keep the log pinned to the newest line (live, and when re-expanded after a run).
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [run.lines, showLog]);

  const statusLabel =
    run.status === 'running'
      ? 'running'
      : run.status === 'queued'
        ? 'queued'
        : run.status === 'done'
          ? 'complete'
          : run.status === 'cancelled'
            ? 'stopped'
            : 'error';
  // The ✕ overloads by run state.
  const closeTitle =
    run.status === 'queued'
      ? 'Remove from queue'
      : run.status === 'running'
        ? 'Force stop'
        : 'Dismiss';
  const logId = `run-log-${run.tileId}`;
  const logBox = (
    <pre
      className="run-log"
      id={logId}
      ref={logRef}
      role="log"
      aria-live="polite"
      aria-atomic="false"
      aria-label={`Progress log for ${run.tileName}`}
    >
      {run.lines.join('\n')}
    </pre>
  );

  return (
    <article className={`run-card run-${run.status}`}>
      <header className="run-card-head">
        <div className="run-card-title">
          <span className={`run-status run-status-${run.status}`}>
            {(run.status === 'running' || run.status === 'queued') && (
              <span className="spinner" aria-hidden="true" />
            )}
            {statusLabel}
          </span>
          <strong>{run.tileName}</strong>
          <span className="badge category">{run.engine}</span>
          {run.model && <span className="badge category">{run.model}</span>}
        </div>
        <button
          className="btn ghost run-dismiss"
          onClick={() => onClose(run)}
          title={closeTitle}
          aria-label={`${closeTitle} — ${run.tileName}`}
        >
          ✕
        </button>
      </header>

      {run.status === 'queued' && (
        <p className="run-current">
          Waiting — runs execute one at a time
          {run.queuePosition && run.queuePosition > 1 ? ` · position ${run.queuePosition}` : ''}.
        </p>
      )}

      {run.status === 'running' && run.current && (
        <p className="run-current">
          Probe {run.current.index}/{run.current.total}:{' '}
          <code>{run.current.label}</code> running…
        </p>
      )}

      {run.status === 'running' && run.rateLimit && (
        // No live region: the pause-start line in the log (aria-live) announces it once;
        // the 2s countdown ticks here are visual only, to avoid screen-reader spam.
        <p className="run-current rate-limited">
          ⏳ Rate limited — retrying in {run.rateLimit.remaining_s}s (attempt{' '}
          {run.rateLimit.attempt})…
        </p>
      )}

      {/* Live log for every non-completed state; the completed card collapses it behind
          the Show/Hide details toggle in the summary row below. */}
      {run.status !== 'done' && (
        <>
          <div className="log-toolbar">
            <button type="button" className="details-toggle" onClick={() => setFullOpen(true)}>
              Show full
            </button>
          </div>
          {logBox}
        </>
      )}

      {run.status === 'error' && run.error && <div className="error">⚠ {run.error}</div>}

      {run.status === 'done' && run.result && (
        <div className="run-result">
          {(() => {
            const s = run.result.summary;
            const unscorable = s.unscorable ?? 0;
            // FAIL on any vuln; INCONCLUSIVE if 0 vulns but the model returned unusable
            // output the probes couldn't score; PASS only when scored clean.
            const verdict =
              s.vulnerabilities_found > 0
                ? { cls: 'fail', label: '✗ FAIL', note:
                    `${s.vulnerabilities_found} vulnerabilit${s.vulnerabilities_found === 1 ? 'y found' : 'ies found'}` }
                : unscorable > 0
                  ? { cls: 'warn', label: '⚠ INCONCLUSIVE', note:
                      `${unscorable} response${unscorable === 1 ? '' : 's'} unscorable — model too weak to evaluate` }
                  : { cls: 'pass', label: '✓ PASS', note: 'no vulnerabilities — guardrails held' };
            return (
              <p className="run-verdict">
                <span className={`verdict ${verdict.cls}`}>{verdict.label}</span>
                <span className="verdict-note">{verdict.note}</span>
              </p>
            );
          })()}
          <div className="summary">
            <Stat label="Probes" value={String(run.result.summary.probes_run)} />
            <Stat
              label="Vulnerabilities"
              value={String(run.result.summary.vulnerabilities_found)}
              tone={run.result.summary.vulnerabilities_found > 0 ? 'danger' : 'ok'}
            />
            {(run.result.summary.unscorable ?? 0) > 0 && (
              <Stat label="Unscorable" value={String(run.result.summary.unscorable)} tone="warn" />
            )}
            <Stat label="Passed" value={String(run.result.summary.probes_passed)} tone="ok" />
            <button
              type="button"
              className="details-toggle"
              aria-expanded={expanded}
              // only reference the log when it's actually in the DOM (expanded)
              {...(expanded ? { 'aria-controls': logId } : {})}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'Hide details' : 'Show details'}
            </button>
            <button type="button" className="details-toggle" onClick={() => setFullOpen(true)}>
              Show full
            </button>
          </div>
          {expanded && logBox}
          <p className="run-id">
            run <code>{run.result.run_id}</code>
          </p>
          <FindingsTable findings={run.result.findings} onOpen={onOpenFinding} />
        </div>
      )}

      {fullOpen && (
        <LogModal
          title={run.tileName}
          text={run.lines.join('\n')}
          onClose={() => setFullOpen(false)}
        />
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
