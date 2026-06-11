import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { ActiveRun, EngineInfo, Health, RunEvent, Tile, TileRun } from './types';
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
  // Any non-rate-limit event means the scorer resumed — clear the rate-limit banner.
  if (ev.type !== 'rate_limited' && run.rateLimit) run = { ...run, rateLimit: undefined };
  // Prefix each log line with the backend-stamped local date/time + timezone (stable across
  // a refresh/replay since it's part of the event, not the moment we render it).
  const ts = ev.ts ? `${ev.ts}  ` : '';
  const withLine = (line: string, patch: Partial<TileRun> = {}): TileRun => ({
    ...run,
    ...patch,
    lines: [...run.lines, ts + line],
  });
  switch (ev.type) {
    case 'queued': {
      // Ignore a stale position update that races in after the run already started/ended
      // (the first 'queued' arrives while status is still 'queued').
      if (run.status !== 'queued') return run;
      const patch = {
        status: 'queued' as const,
        jobId: ev.id,
        queuePosition: ev.position,
      };
      // Append a line only the first time (position updates just patch, no log spam).
      if (run.jobId) return { ...run, ...patch };
      return withLine(
        ev.position > 1 ? `⏳ queued · position ${ev.position}…` : '⏳ queued — starting soon…',
        patch,
      );
    }
    case 'run_started':
      return withLine(`▶ Run started — ${ev.total_probes} probes · engine ${ev.engine_name}`, {
        status: 'running',
        queuePosition: undefined,
        totalProbes: ev.total_probes,
      });
    case 'phase':
      if (ev.phase === 'baseline')
        return withLine('① Passive learning — building behavioural baseline…');
      if (ev.phase === 'probing')
        return withLine(`② Active probing — ${run.totalProbes ?? ''} attack vectors…`.trim());
      return withLine('③ Actionable reporting — recording findings…');
    case 'learning':
      return withLine(`   learning from ${ev.name} (${ev.index}/${ev.total})…`);
    case 'baseline_done':
      return withLine(`   baseline captured · ${ev.sample_count} clean samples`);
    case 'probe_started':
      return withLine(`   ▸ ${ev.index}/${ev.total}  ${ev.vector_id} (${ev.category}) running…`, {
        current: { index: ev.index, total: ev.total, label: `${ev.vector_id} (${ev.category})` },
        probeLine: run.lines.length, // index of the line appended below (pre-append length)
      });
    case 'name_swap': {
      const swap = `       ↔ name swap (${ev.axis}): ${ev.from} → ${ev.to}`;
      return withLine(ev.interest ? `${swap}\n          ⤷ interests → ${ev.interest}` : swap);
    }
    case 'probe_target':
      return withLine(`       · testing resume: ${ev.name}`);
    case 'rate_limited': {
      const rl = { attempt: ev.attempt, remaining_s: ev.remaining_s, wait_s: ev.wait_s };
      // log a line only when a new pause starts; later ticks just refresh the countdown
      if (run.rateLimit?.attempt === ev.attempt) return { ...run, rateLimit: rl };
      return withLine(
        `   ⏳ rate limited — pausing ${ev.wait_s}s before retry (attempt ${ev.attempt})…`,
        { rateLimit: rl },
      );
    }
    case 'probe_done': {
      // Complete the probe's own line item: append its end result with an icon — ✅ the
      // model passed the test, ❌ it failed (vulnerability found), ⚠️ + description when the
      // response was unusable (an error: the probe couldn't be scored at all).
      const verdict = ev.unscorable
        ? ` ⚠️ error — ${ev.detail || 'response unusable'}`
        : ev.success
          ? ' ❌'
          : ' ✅';
      const idx = run.probeLine;
      if (idx == null || idx >= run.lines.length) {
        // Defensive: no tracked header line — fall back to a standalone status line.
        return withLine(`       ${verdict.trim()} — ${ev.vector_id}`, { probeLine: undefined });
      }
      const lines = [...run.lines];
      lines[idx] = lines[idx].replace(/ running…$/, '') + verdict;
      return { ...run, lines, probeLine: undefined };
    }
    case 'result': {
      // Overall verdict: FAIL if any probe found a vulnerability; PASS if the tile held off
      // every probe; INCONCLUSIVE if the model returned unusable output the probes couldn't
      // even score (not a vuln, but not a clean pass either).
      const vulns = ev.summary.vulnerabilities_found;
      const unscorable = ev.summary.unscorable ?? 0;
      const verdict =
        vulns > 0
          ? `✗ FAIL — ${vulns} vulnerabilit${vulns === 1 ? 'y' : 'ies'} found across ${ev.summary.probes_run} probes`
          : unscorable > 0
            ? `⚠ INCONCLUSIVE — 0 vulnerabilities, but ${unscorable} probe${unscorable === 1 ? '' : 's'} unscorable (model too weak to evaluate)`
            : `✓ PASS — no vulnerabilities found across ${ev.summary.probes_run} probes`;
      return withLine(verdict, {
        status: 'done',
        current: undefined,
        result: {
          run_id: ev.run_id,
          tile_id: ev.tile_id,
          engine_name: ev.engine_name,
          summary: ev.summary,
          findings: ev.findings,
        },
      });
    }
    case 'error': {
      // A run-level error aborts the in-flight probe: mark its line item with the error
      // icon (the description follows on the line below + in the error banner).
      if (run.probeLine != null && run.probeLine < run.lines.length) {
        const lines = [...run.lines];
        lines[run.probeLine] = lines[run.probeLine].replace(/ running…$/, '') + ' ⚠️';
        run = { ...run, lines, probeLine: undefined };
      }
      return withLine(`⚠ ${ev.message}`, { status: 'error', current: undefined, error: ev.message });
    }
    case 'cancelled':
      return withLine(
        ev.reason === 'removed_from_queue' ? '✕ removed from queue' : '✕ stopped',
        { status: 'cancelled', current: undefined, queuePosition: undefined },
      );
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

  // One run per tile, keyed by tile_id. Runs are serialized server-side.
  const [runs, setRuns] = useState<Record<string, TileRun>>({});
  const aborters = useRef<Record<string, AbortController>>({});
  // Synchronous "is this tile running" guard — updated imperatively so a rapid
  // double-click can't slip past it on a stale `runs` snapshot (the button's
  // disabled state still re-renders, but this closes the race window).
  const runningRef = useRef<Set<string>>(new Set());
  // Tiles whose ✕ was clicked while still queued, BEFORE the backend job id arrived. We
  // cancel the moment the 'queued' event supplies the id, so a job can never be enqueued
  // server-side with the client having discarded its only handle to cancel it.
  const pendingCancel = useRef<Set<string>>(new Set());
  // Live mirror of `runs` for the unmount cleanup (so we can cancel in-flight jobs).
  const runsRef = useRef<Record<string, TileRun>>({});

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

  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);

  // On unmount: cancel any still-queued/running jobs on the server (aborting the fetch
  // alone does NOT stop the decoupled worker), then tear down the streams.
  useEffect(() => {
    const controllers = aborters.current;
    return () => {
      Object.values(runsRef.current).forEach((r) => {
        if ((r.status === 'queued' || r.status === 'running') && r.jobId) {
          api.cancelRun(r.jobId).catch(() => {});
        }
      });
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

  // Drive one tile's run from a stream — used both to kick off a new run (POST) and to
  // reconnect to an existing one after a refresh (GET attach). The TileRun is rebuilt purely
  // from the event stream via applyEvent, so a reconnect replays the durable backend log and
  // then tails live events identically to the original run.
  const consumeRunStream = useCallback(
    (tileId: string, startStream: (onEvent: (ev: RunEvent) => void, signal: AbortSignal) => Promise<void>) => {
      aborters.current[tileId]?.abort();
      const controller = new AbortController();
      aborters.current[tileId] = controller;
      runningRef.current.add(tileId);

      const update = (fn: (run: TileRun) => TileRun) =>
        setRuns((prev) => (prev[tileId] ? { ...prev, [tileId]: fn(prev[tileId]) } : prev));

      startStream((ev) => {
        update((run) => applyEvent(run, ev));
        if (ev.type === 'result') setLedgerRefreshKey((k) => k + 1);
        // ✕ was clicked before the job id arrived — cancel now that we have it, then drop the card.
        if (ev.type === 'queued' && pendingCancel.current.has(tileId)) {
          pendingCancel.current.delete(tileId);
          api.cancelRun(ev.id).catch(() => {});
          controller.abort();
          setRuns((prev) => {
            const next = { ...prev };
            delete next[tileId];
            return next;
          });
        }
      }, controller.signal)
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          // Reconnect raced eviction (the run finished + was superseded) — drop the card
          // silently rather than show a spurious error.
          if (e instanceof ApiError && e.status === 404) {
            setRuns((prev) => {
              const next = { ...prev };
              delete next[tileId];
              return next;
            });
            return;
          }
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
    [],
  );

  const onRun = useCallback(
    (tileId: string) => {
      const tile = tiles.find((t) => t.tile_id === tileId);
      // Guard against a second concurrent start for this tile. Uses a ref (not the
      // `runs` state) so it reads the live value, immune to stale closures / batching.
      if (runningRef.current.has(tileId)) return;

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
          // Runs are serialized server-side; a run starts queued and flips to running
          // when the single worker reaches it (the 'run_started' event).
          status: 'queued',
          startedAt: Date.now(),
          lines: [`connecting to ${engine}${model ? ` · ${model}` : ''}…`],
        },
      }));
      consumeRunStream(tileId, (onEvent, signal) =>
        api.streamRun(tileId, engine, model, onEvent, signal));
    },
    [selectedEngine, selectedModel, engines, tiles, consumeRunStream],
  );

  // Rebuild the Run console after a page load / refresh: for each run the backend is still
  // tracking, seed a fresh queued card and reconnect to its stream (which replays the full
  // log, then tails). A tile already streaming this session is skipped.
  const reconnectRun = useCallback(
    (r: ActiveRun) => {
      if (runningRef.current.has(r.tile_id)) return;
      setRuns((prev) => ({
        ...prev,
        [r.tile_id]: {
          tileId: r.tile_id,
          tileName: r.tile_name,
          engine: r.engine,
          model: r.model ?? '',
          status: 'queued',
          startedAt: Date.now(),
          lines: [],
        },
      }));
      consumeRunStream(r.tile_id, (onEvent, signal) => api.attachRun(r.job_id, onEvent, signal));
    },
    [consumeRunStream],
  );

  useEffect(() => {
    let cancelled = false;
    api
      .activeRuns()
      .then((active) => {
        if (!cancelled) active.forEach(reconnectRun);
      })
      .catch(() => {
        /* no backend / no active runs — nothing to restore */
      });
    return () => {
      cancelled = true;
    };
  }, [reconnectRun]);

  // Remove a card and abort its (now-defunct) stream. Does NOT stop the backend job —
  // callers that need that call api.cancelRun first (the worker is decoupled from the stream).
  const dismissCard = useCallback((tileId: string) => {
    runningRef.current.delete(tileId);
    aborters.current[tileId]?.abort();
    delete aborters.current[tileId];
    setRuns((prev) => {
      const next = { ...prev };
      delete next[tileId];
      return next;
    });
  }, []);

  // The run card's ✕ overloads by run state:
  //  - queued  → remove from the queue (cancel on the server) + drop the card. If the job
  //              id hasn't arrived yet, remember the intent and cancel the moment it does.
  //  - running → force-stop the scorer; the 'cancelled' event flips the card to 'stopped'
  //              (NOT auto-dismissed — click ✕ again to remove it).
  //  - done/error/cancelled → dismiss the card.
  const appendLine = (tileId: string, line: string, patch: Partial<TileRun> = {}) =>
    setRuns((prev) =>
      prev[tileId]
        ? { ...prev, [tileId]: { ...prev[tileId], ...patch, lines: [...prev[tileId].lines, line] } }
        : prev,
    );
  const onCloseCard = useCallback(
    (run: TileRun) => {
      if (run.status === 'queued') {
        if (run.jobId) {
          api.cancelRun(run.jobId).catch(() => {});
          dismissCard(run.tileId);
        } else {
          // job id not here yet — keep the stream open so we learn it, cancel on arrival
          pendingCancel.current.add(run.tileId);
          appendLine(run.tileId, 'cancelling…');
        }
      } else if (run.status === 'running' && run.jobId) {
        api.cancelRun(run.jobId).catch(() => {});
        // drop the rate-limit countdown right away so it doesn't linger next to "stopping…"
        appendLine(run.tileId, 'stopping…', { rateLimit: undefined });
      } else {
        dismissCard(run.tileId);
      }
    },
    [dismissCard],
  );

  const runningTiles = useMemo(
    () =>
      new Set(
        Object.values(runs)
          .filter((r) => r.status === 'running' || r.status === 'queued')
          .map((r) => r.tileId),
      ),
    [runs],
  );
  const runList = useMemo(
    () => Object.values(runs).sort((a, b) => b.startedAt - a.startedAt),
    [runs],
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
                  onClose={onCloseCard}
                />
              </>
            )}
            {tab === 'ledger' && (
              <LedgerViewer
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
        Findings persist to the vulnerability ledger. The same probe suite runs against every tile,
        to measure guardrail strength.
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
