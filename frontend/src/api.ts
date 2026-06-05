import type {
  EngineInfo,
  Finding,
  FindingFilters,
  Health,
  RunResult,
  RunRow,
  Tile,
} from './types';

const BASE =
  (import.meta.env.VITE_API_BASE?.replace(/\/$/, '')) || 'http://localhost:8000';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'content-type': 'application/json' },
      ...init,
    });
  } catch (err) {
    throw new ApiError(0, `Cannot reach the backend at ${BASE}. Is it running? (${String(err)})`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function queryString(params: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) qs.set(key, value);
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export const api = {
  base: BASE,
  health: () => request<Health>('/health'),
  tiles: () => request<Tile[]>('/tiles'),
  engines: () => request<EngineInfo[]>('/engines'),
  createRun: (tile_id: string, engine_name?: string) =>
    request<RunResult>('/runs', {
      method: 'POST',
      body: JSON.stringify({ tile_id, engine_name }),
    }),
  listRuns: (tile_id?: string) =>
    request<RunRow[]>(`/runs${queryString({ tile_id })}`),
  getRun: (run_id: string) => request<RunRow>(`/runs/${encodeURIComponent(run_id)}`),
  listFindings: (filters: FindingFilters) =>
    request<Finding[]>(`/findings${queryString(filters as Record<string, string | undefined>)}`),
  getFinding: (id: string) => request<Finding>(`/findings/${encodeURIComponent(id)}`),
};
