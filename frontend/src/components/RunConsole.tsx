import type { RunResult } from '../types';
import { FindingsTable } from './FindingsTable';

const PHASES = ['Passive learning', 'Active probing', 'Actionable reporting'];

interface Props {
  running: boolean;
  phaseIndex: number;
  tileName: string | null;
  result: RunResult | null;
  error: string | null;
  onOpenFinding: (id: string) => void;
}

export function RunConsole({ running, phaseIndex, tileName, result, error, onOpenFinding }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Run console</h2>
      </div>

      {running && (
        <div className="run-progress">
          <p>
            Running DevSecBuddy against <strong>{tileName}</strong>…
          </p>
          <ol className="phases">
            {PHASES.map((p, i) => (
              <li key={p} className={i <= phaseIndex ? 'phase done' : 'phase'}>
                <span className="dot" /> {p}
              </li>
            ))}
          </ol>
        </div>
      )}

      {!running && error && <div className="error">⚠ {error}</div>}

      {!running && result && (
        <div className="run-result">
          <div className="summary">
            <Stat label="Tile" value={result.tile_id} />
            <Stat label="Engine" value={result.engine_name} />
            <Stat label="Probes" value={String(result.summary.probes_run)} />
            <Stat
              label="Vulnerabilities"
              value={String(result.summary.vulnerabilities_found)}
              tone={result.summary.vulnerabilities_found > 0 ? 'danger' : 'ok'}
            />
            <Stat label="Passed" value={String(result.summary.probes_passed)} tone="ok" />
          </div>
          <p className="run-id">
            run <code>{result.run_id}</code>
          </p>
          <FindingsTable findings={result.findings} onOpen={onOpenFinding} />
        </div>
      )}

      {!running && !result && !error && (
        <p className="empty">Pick a tile above and run an assessment to see its findings here.</p>
      )}
    </section>
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
