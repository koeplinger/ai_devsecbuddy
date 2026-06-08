import type { EngineInfo, Tile } from '../types';

interface Props {
  tiles: Tile[];
  engines: EngineInfo[];
  selectedEngine: string;
  onSelectEngine: (name: string) => void;
  selectedModel: string;
  onSelectModel: (id: string) => void;
  onRun: (tileId: string) => void;
  runningTiles: Set<string>;
}

export function TilesGrid({
  tiles,
  engines,
  selectedEngine,
  onSelectEngine,
  selectedModel,
  onSelectModel,
  onRun,
  runningTiles,
}: Props) {
  const models = engines.find((e) => e.name === selectedEngine)?.models ?? [];
  // "Assess all" starts every tile that isn't already running (onRun guards the rest).
  const idleTiles = tiles.filter((t) => !runningTiles.has(t.tile_id));
  const runAll = () => idleTiles.forEach((t) => onRun(t.tile_id));
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>AI application tiles</h2>
        <div className="engine-controls">
          <label className="engine-select">
            Engine
            {/* Not disabled while runs are in flight: each run captures the engine +
                model at launch, so you can queue another tile (or switch) meanwhile. */}
            <select value={selectedEngine} onChange={(e) => onSelectEngine(e.target.value)}>
              {engines.map((e) => (
                <option
                  key={e.name}
                  value={e.name}
                  disabled={e.implemented === false || e.configured === false}
                >
                  {e.name}
                  {e.implemented === false
                    ? ' — wired in M6'
                    : e.configured === false
                      ? ' — needs setup'
                      : ''}
                  {e.default ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="engine-select">
            Model
            <select
              value={selectedModel}
              onChange={(e) => onSelectModel(e.target.value)}
              disabled={models.length <= 1}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                  {m.tier && m.tier !== 'n/a' ? ` — ${m.tier}` : ''}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn primary pill assess-all"
            onClick={runAll}
            disabled={idleTiles.length === 0}
            title={
              idleTiles.length === 0
                ? 'All tiles are already running'
                : 'Run an assessment on every tile with the selected engine + model'
            }
          >
            Assess all tiles
            {idleTiles.length > 0 && idleTiles.length < tiles.length ? ` (${idleTiles.length})` : ''}
          </button>
        </div>
      </div>
      <p className="hint">
        The same probe suite runs against every tile; differences in findings isolate to
        guardrail strength — that is the shift-left payoff this demo shows. Launch several
        tiles at once; each tile allows one live run, tracked in the run console below.
      </p>
      <div className="tiles">
        {tiles.map((tile) => {
          const running = runningTiles.has(tile.tile_id);
          return (
            <article key={tile.tile_id} className="tile-card">
              <header className="tile-head">
                <h3>{tile.name}</h3>
                <code className="tile-id">{tile.tile_id}</code>
              </header>
              <p className="tile-desc">{tile.description}</p>
              <div className="guardrails">
                {tile.guardrails.length === 0 ? (
                  <span className="pill pill-danger">no guardrails</span>
                ) : (
                  tile.guardrails.map((g) => (
                    <span key={g} className="pill pill-neutral">
                      {g.replace(/_/g, ' ')}
                    </span>
                  ))
                )}
              </div>
              <button
                className="btn primary"
                onClick={() => onRun(tile.tile_id)}
                disabled={running}
                aria-busy={running}
              >
                {running ? 'Running…' : 'Run assessment'}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
