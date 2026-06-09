import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { EngineInfo, Health, RunEvent, Tile, TileRun } from './types';
import { TilesGrid } from './components/TilesGrid';
import { RunConsole } from './components/RunConsole';
import { LedgerViewer } from './components/LedgerViewer';
import { ResumesPanel } from './components/ResumesPanel';
import { FindingDetail } from './components/FindingDetail';

type Tab = 'runs' | 'ledger' | 'resumes';

// Fold one streaming event into a tile's run state, appending a human-readable
// progress line. Pure — the backend (devsecbuddy/runner.py) is the source of truth
// for ordering; this only formats what arrives.
function applyEvent(run: TileRun, ev: RunEvent): TileRun {
  const withLine = (line: string, patch: Partial<TileRun> = {}): TileRun => ({
    ...run,
    ...patch,
    lines: [...run.lines, line],
  });
  switch (ev.type) {
    case 'run_started':
      return withLine(`▶ Run started — ${ev.total_probes} probes · engine ${ev.engine_name}`, {
        totalProbes: ev.total_probes,
      });
    case 'phase':
      if (ev.phase === 'baseline')
        return withLine('① Passive learning — building behavioural baseline…');
      if (ev.phase === 'probing')
        return withLine(`② Active probing — ${run.totalProbes ?? ''} attack vectors…`.trim());
      return withLine('③ Actionable reporting — recording findings…');
    case 'baseline_done':
      return withLine(`   baseline captured · ${ev.sample_count} clean samples`);
    case 'probe_started':
      return withLine(`   ▸ ${ev.index}/${ev.total}  ${ev.vector_id} (${ev.category}) running…`, {
        current: { index: ev.index, total: ev.total, label: `${ev.vector_id} (${ev.category})` },
      });
    case 'name_swap':
      return withLine(`       ↔ name swap (${ev.axis}): ${ev.from} → ${ev.to}`);
    case 'probe_target':
      return withLine(`       · testing resume: ${ev.name}`);
    case 'probe_done':
      return withLine(
        `       ${ev.success ? `✗ vulnerable · ${ev.severity}` : '✓ passed'} — ${ev.vector_id}`,
      );
    case 'result':
      return withLine(
        `✓ Done — ${ev.summary.vulnerabilities_found} vulnerabilities / ${ev.summary.probes_run} probes`,
        {
          status: 'done',
          current: undefined,
          result: {
            run_id: ev.run_id,
            tile_id: ev.tile_id,
            engine_name: ev.engine_name,
            summary: ev.summary,
            findings: ev.findings,
          },
        },
      );
    case 'error':
      return withLine(`⚠ ${ev.message}`, { status: 'error', current: undefined, error: ev.message });
    default:
      return run;
  }
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>('runs');
  const [resumesDirty, setResumesDirty] = useState(false);
  const [selectedEngine, setSelectedEngine] = useState('mock');
  const [selectedModel, setSelectedModel] = useState('');

  // One run per tile, keyed by tile_id; multiple may be 'running' at once.
  const [runs, setRuns] = useState<Record<string, TileRun>>({});
  const aborters = useRef<Record<string, AbortController>>({});
  // Synchronous "is this tile running" guard — updated imperatively so a rapid
  // double-click can't slip past it on a stale `runs` snapshot (the button's
  // disabled state still re-renders, but this closes the race window).
  const runningRef = useRef<Set<string>>(new Set());

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.health(), api.tiles(), api.engines()])
      .then(([h, t, e]) => {
        if (cancelled) return;
        setHealth(h);
        setTiles(t);
        setEngines(e);
        const def =
          e.find((x) => x.default && x.configured !== false) ??
          e.find((x) => x.configured !== false);
        if (def) {
          setSelectedEngine(def.name);
          setSelectedModel(def.model ?? '');
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setBootError(e instanceof ApiError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Abort any in-flight run streams on unmount.
  useEffect(() => {
    const controllers = aborters.current;
    return () => {
      Object.values(controllers).forEach((c) => c.abort());
    };
  }, []);

  // Switching engine resets the model to that engine's default.
  const onSelectEngine = useCallback(
    (name: string) => {
      setSelectedEngine(name);
      const eng = engines.find((e) => e.name === name);
      setSelectedModel(eng?.model ?? '');
    },
    [engines],
  );

  const onRun = useCallback(
    (tileId: string) => {
      const tile = tiles.find((t) => t.tile_id === tileId);
      // Guard against a second concurrent start for this tile. Uses a ref (not the
      // `runs` state) so it reads the live value, immune to stale closures / batching.
      if (runningRef.current.has(tileId)) return;
      runningRef.current.add(tileId);

      aborters.current[tileId]?.abort();
      const controller = new AbortController();
      aborters.current[tileId] = controller;

      const engine = selectedEngine;
      const eng = engines.find((e) => e.name === engine);
      // Pin the model to the engine's catalog so the captured/displayed model is never
      // a stale value from a previous engine (the backend also rejects unknown models).
      const model = eng?.models?.some((m) => m.id === selectedModel)
        ? selectedModel
        : (eng?.model ?? '');
      setRuns((prev) => ({
        ...prev,
        [tileId]: {
          tileId,
          tileName: tile?.name ?? tileId,
          engine,
          model,
          status: 'running',
          startedAt: Date.now(),
          lines: [`connecting to ${engine}${model ? ` · ${model}` : ''}…`],
        },
      }));

      const update = (fn: (run: TileRun) => TileRun) =>
        setRuns((prev) => (prev[tileId] ? { ...prev, [tileId]: fn(prev[tileId]) } : prev));

      api
        .streamRun(
          tileId,
          engine,
          model,
          (ev) => {
            update((run) => applyEvent(run, ev));
            if (ev.type === 'result') setLedgerRefreshKey((k) => k + 1);
          },
          controller.signal,
        )
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          const message = e instanceof ApiError ? e.message : String(e);
          update((run) => ({
            ...run,
            status: 'error',
            current: undefined,
            error: message,
            lines: [...run.lines, `⚠ ${message}`],
          }));
        })
        .finally(() => {
          runningRef.current.delete(tileId);
          if (aborters.current[tileId] === controller) delete aborters.current[tileId];
        });
    },
    [selectedEngine, selectedModel, engines, tiles],
  );

  const onDismissRun = useCallback((tileId: string) => {
    runningRef.current.delete(tileId);
    aborters.current[tileId]?.abort();
    delete aborters.current[tileId];
    setRuns((prev) => {
      const next = { ...prev };
      delete next[tileId];
      return next;
    });
  }, []);

  const runningTiles = useMemo(
    () =>
      new Set(Object.values(runs).filter((r) => r.status === 'running').map((r) => r.tileId)),
    [runs],
  );
  const runList = useMemo(
    () => Object.values(runs).sort((a, b) => b.startedAt - a.startedAt),
    [runs],
  );
  const engineNames = useMemo(() => engines.map((e) => e.name), [engines]);
  const modelNames = useMemo(
    () => [...new Set(engines.flatMap((e) => e.models ?? []).map((m) => m.id))],
    [engines],
  );

  // Warn before leaving the Resumes tab with unsaved edits.
  const changeTab = useCallback(
    (next: Tab) => {
      if (
        tab === 'resumes' &&
        next !== 'resumes' &&
        resumesDirty &&
        !window.confirm('Discard unsaved resume changes?')
      ) {
        return;
      }
      setTab(next);
    },
    [tab, resumesDirty],
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">
            🛡️
          </span>
          <div>
            <h1>AI DevSecBuddy</h1>
            <p className="tagline">Automated adversarial AI-security testing</p>
          </div>
        </div>
        <HealthBadge health={health} base={api.base} />
      </header>

      {bootError ? (
        <div className="panel boot-error">
          <h2>Cannot reach the backend</h2>
          <p className="error">⚠ {bootError}</p>
          <p>
            Start it with <code>uvicorn backend.main:app</code> (default{' '}
            <code>http://localhost:8000</code>), or point the UI elsewhere with{' '}
            <code>VITE_API_BASE</code>.
          </p>
        </div>
      ) : (
        <>
          <nav className="tabs" aria-label="Views">
            <button
              className={tab === 'runs' ? 'tab active' : 'tab'}
              onClick={() => changeTab('runs')}
            >
              Tiles &amp; runs
            </button>
            <button
              className={tab === 'ledger' ? 'tab active' : 'tab'}
              onClick={() => changeTab('ledger')}
            >
              Vulnerability ledger
            </button>
            <button
              className={tab === 'resumes' ? 'tab active' : 'tab'}
              onClick={() => changeTab('resumes')}
            >
              Resumes
            </button>
          </nav>

          <main className="stack">
            {tab === 'runs' && (
              <>
                <TilesGrid
                  tiles={tiles}
                  engines={engines}
                  selectedEngine={selectedEngine}
                  onSelectEngine={onSelectEngine}
                  selectedModel={selectedModel}
                  onSelectModel={setSelectedModel}
                  onRun={onRun}
                  runningTiles={runningTiles}
                />
                <RunConsole
                  runs={runList}
                  onOpenFinding={setSelectedFindingId}
                  onDismiss={onDismissRun}
                />
              </>
            )}
            {tab === 'ledger' && (
              <LedgerViewer
                tiles={tiles}
                engineNames={engineNames}
                modelNames={modelNames}
                defaultEngine={selectedEngine}
                refreshKey={ledgerRefreshKey}
                onOpenFinding={setSelectedFindingId}
              />
            )}
            {tab === 'resumes' && <ResumesPanel onDirtyChange={setResumesDirty} />}
          </main>
        </>
      )}

      {selectedFindingId && (
        <FindingDetail findingId={selectedFindingId} onClose={() => setSelectedFindingId(null)} />
      )}

      <footer className="footer">
        Findings persist to the SQLite vulnerability ledger. The same probe suite runs against every
        tile — differences isolate to guardrail strength.
      </footer>
    </div>
  );
}

function HealthBadge({ health, base }: { health: Health | null; base: string }) {
  const ok = health?.status === 'ok';
  return (
    <div className="health" title={base}>
      <span className={ok ? 'status-dot ok' : 'status-dot bad'} aria-hidden="true" />
      {health ? (
        <span>
          API up · engine <strong>{health.default_engine}</strong>
          {health.default_engine_known ? '' : ' (unknown!)'}
        </span>
      ) : (
        <span>connecting…</span>
      )}
    </div>
  );
}
