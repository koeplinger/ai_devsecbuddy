import type {
  CallStats,
  EngineInfo,
  Finding,
  FindingFilters,
  Health,
  Resume,
  RunEvent,
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
  telemetry: () => request<CallStats>('/telemetry'),
  createRun: (tile_id: string, engine_name?: string, model?: string) =>
    request<RunResult>('/runs', {
      method: 'POST',
      body: JSON.stringify({ tile_id, engine_name, model }),
    }),
  // Cancel a streaming run by its job id: removes it from the queue if not yet started,
  // or force-stops it if running. The run's own stream then ends with a 'cancelled' event.
  cancelRun: (jobId: string) =>
    request<{ cancelled: boolean; job_id: string; state: string }>(
      `/runs/${encodeURIComponent(jobId)}/cancel`,
      { method: 'POST' },
    ),
  // Stream a run as NDJSON, invoking onEvent for each progress event. Resolves when
  // the stream ends; rejects (ApiError) on a non-2xx start (404/400/409) or a network
  // drop. `signal` lets the caller abort (e.g. on unmount).
  streamRun: async (
    tile_id: string,
    engine_name: string | undefined,
    model: string | undefined,
    onEvent: (event: RunEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    let res: Response;
    try {
      res = await fetch(`${BASE}/runs/stream`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tile_id, engine_name, model }),
        signal,
      });
    } catch (err) {
      if (signal?.aborted) return;
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
    if (!res.body) throw new ApiError(0, 'Streaming not supported by this browser.');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const flush = (chunk: string) => {
      buffer += chunk;
      let nl: number;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (line) onEvent(JSON.parse(line) as RunEvent);
      }
    };
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        flush(decoder.decode(value, { stream: true }));
      }
    } catch (err) {
      if (signal?.aborted) return;
      throw new ApiError(0, `Run stream interrupted (${String(err)})`);
    }
    // A clean end leaves an empty buffer (every event ends in '\n'). A non-empty
    // tail means the connection dropped mid-event — surface it instead of throwing
    // an unhandled rejection out of the read loop's try.
    const tail = buffer.trim();
    if (tail) {
      try {
        onEvent(JSON.parse(tail) as RunEvent);
      } catch {
        if (!signal?.aborted) throw new ApiError(0, 'Run stream ended mid-event (truncated).');
      }
    }
  },
  listRuns: (tile_id?: string) =>
    request<RunRow[]>(`/runs${queryString({ tile_id })}`),
  getRun: (run_id: string) => request<RunRow>(`/runs/${encodeURIComponent(run_id)}`),
  listFindings: (filters: FindingFilters) =>
    request<Finding[]>(`/findings${queryString(filters as Record<string, string | undefined>)}`),
  getFinding: (id: string) => request<Finding>(`/findings/${encodeURIComponent(id)}`),
  deleteFindings: (ids: string[]) =>
    request<{ deleted: number }>('/findings', {
      method: 'DELETE',
      body: JSON.stringify({ ids }),
    }),

  // ---- resumes (the sample corpus) ----
  resumes: () => request<Resume[]>('/resumes'),
  createResume: (applicant_name: string, resume_text: string, gender: string, ethnicity: string) =>
    request<Resume>('/resumes', {
      method: 'POST',
      body: JSON.stringify({ applicant_name, resume_text, gender, ethnicity }),
    }),
  updateResume: (
    id: string,
    applicant_name: string,
    resume_text: string,
    gender: string,
    ethnicity: string,
  ) =>
    request<Resume>(`/resumes/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify({ applicant_name, resume_text, gender, ethnicity }),
    }),
  deleteResume: (id: string) =>
    request<{ deleted: boolean }>(`/resumes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  // Delete every resume (including user edits) and restore the shipped defaults.
  resetResumes: () => request<Resume[]>('/resumes/reset', { method: 'POST' }),
  // PDF upload uses multipart/form-data, so it bypasses the JSON request() helper.
  extractResumePdf: async (file: File): Promise<{ text: string; pages: number; chars: number }> => {
    const form = new FormData();
    form.append('file', file);
    let res: Response;
    try {
      res = await fetch(`${BASE}/resumes/extract`, { method: 'POST', body: form });
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
    return (await res.json()) as { text: string; pages: number; chars: number };
  },
};
