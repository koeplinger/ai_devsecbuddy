import type { EngineInfo, Tile } from '../types';

interface Props {
  tiles: Tile[];
  engines: EngineInfo[];
  selectedEngine: string;
  onSelectEngine: (name: string) => void;
  onRun: (tileId: string) => void;
  runningTileId: string | null;
}

export function TilesGrid({
  tiles,
  engines,
  selectedEngine,
  onSelectEngine,
  onRun,
  runningTileId,
}: Props) {
  const busy = runningTileId !== null;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>AI application tiles</h2>
        <label className="engine-select">
          Engine
          <select
            value={selectedEngine}
            onChange={(e) => onSelectEngine(e.target.value)}
            disabled={busy}
          >
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
      </div>
      <p className="hint">
        The same probe suite runs against every tile; differences in findings isolate to
        guardrail strength — that is the shift-left payoff this demo shows.
      </p>
      <div className="tiles">
        {tiles.map((tile) => (
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
              disabled={busy}
            >
              {runningTileId === tile.tile_id ? 'Running…' : 'Run assessment'}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
