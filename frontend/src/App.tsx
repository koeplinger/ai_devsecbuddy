import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { EngineInfo, Health, RunResult, Tile } from './types';
import { TilesGrid } from './components/TilesGrid';
import { RunConsole } from './components/RunConsole';
import { LedgerViewer } from './components/LedgerViewer';
import { FindingDetail } from './components/FindingDetail';

type Tab = 'runs' | 'ledger';

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>('runs');
  const [selectedEngine, setSelectedEngine] = useState('mock');

  const [runningTileId, setRunningTileId] = useState<string | null>(null);
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const phaseTimer = useRef<number | null>(null);

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
        if (def) setSelectedEngine(def.name);
      })
      .catch((e: unknown) => {
        if (!cancelled) setBootError(e instanceof ApiError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(
    () => () => {
      if (phaseTimer.current !== null) window.clearInterval(phaseTimer.current);
    },
    [],
  );

  const onRun = useCallback(
    (tileId: string) => {
      setRunningTileId(tileId);
      setRunError(null);
      setRunResult(null);
      setPhaseIndex(0);
      // Animate the three phases while the (synchronous) run is in flight. The mock
      // run is fast; this just gives the loop a visible shape. Real streaming is future work.
      let i = 0;
      phaseTimer.current = window.setInterval(() => {
        i = Math.min(i + 1, 2);
        setPhaseIndex(i);
      }, 350);
      const stop = () => {
        if (phaseTimer.current !== null) {
          window.clearInterval(phaseTimer.current);
          phaseTimer.current = null;
        }
      };
      api
        .createRun(tileId, selectedEngine)
        .then((res) => {
          setRunResult(res);
          setLedgerRefreshKey((k) => k + 1);
        })
        .catch((e: unknown) => {
          setRunError(e instanceof ApiError ? e.message : String(e));
        })
        .finally(() => {
          stop();
          setRunningTileId(null);
        });
    },
    [selectedEngine],
  );

  const runningTileName = tiles.find((t) => t.tile_id === runningTileId)?.name ?? runningTileId;

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
            <button className={tab === 'runs' ? 'tab active' : 'tab'} onClick={() => setTab('runs')}>
              Tiles &amp; runs
            </button>
            <button
              className={tab === 'ledger' ? 'tab active' : 'tab'}
              onClick={() => setTab('ledger')}
            >
              Vulnerability ledger
            </button>
          </nav>

          <main className="stack">
            {tab === 'runs' ? (
              <>
                <TilesGrid
                  tiles={tiles}
                  engines={engines}
                  selectedEngine={selectedEngine}
                  onSelectEngine={setSelectedEngine}
                  onRun={onRun}
                  runningTileId={runningTileId}
                />
                <RunConsole
                  running={runningTileId !== null}
                  phaseIndex={phaseIndex}
                  tileName={runningTileName}
                  result={runResult}
                  error={runError}
                  onOpenFinding={setSelectedFindingId}
                />
              </>
            ) : (
              <LedgerViewer
                tiles={tiles}
                refreshKey={ledgerRefreshKey}
                onOpenFinding={setSelectedFindingId}
              />
            )}
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
