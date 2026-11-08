import type { Build, Stroke } from './types'

/** Talks to the Python backend (`python -m sidekick ui`). In dev, vite proxies /api to it. */

export type StepState = 'todo' | 'active' | 'done' | 'failed'

export type Status = {
  server_id: string
  run_id: number
  busy: boolean
  mode: 'idle' | 'building' | 'waiting' | 'done' | 'stopped'
  action: string
  prompt: string | null
  safety: boolean
  paused: boolean
  result: null | 'done' | 'stopped' | 'incomplete' | 'error'
  step: number
  total: number
  steps: { label: string; state: StepState; index: number }[]
  log: string[]
  fps: number
}

export type InventoryItem = { name: string; count: number; colors: Record<string, number>; shape: string }

/** One block type as the robot knows it. `size` and every pose are real cm. */
export type CatalogType = {
  id: string
  name: string
  shape: string
  size: [number, number, number]
  top: boolean
  colors: Record<string, number>
  poses: { name: string; size: [number, number, number] }[]
  count: number
}

export type Info = {
  server_id: string
  unit_cm: number
  sim: boolean
  use_color: boolean
  grid: { width: number; depth: number; slots: number; max_height: number; depth_slot: number }
  inventory: Record<string, InventoryItem>
  catalog: { max_grip: number; types: CatalogType[] }
}

export type Problem = { index: number | null; level: 'error' | 'warn'; msg: string }

export class ApiError extends Error {
  status: number
  body: Record<string, unknown>
  constructor(status: number, msg: string, body: Record<string, unknown> = {}) {
    super(msg)
    this.status = status
    this.body = body
  }
}

async function call<T>(path: string, body?: unknown, opts: { signal?: AbortSignal; timeout?: number } = {}): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), opts.timeout ?? 8000)
  const onAbort = () => ctrl.abort()
  opts.signal?.addEventListener('abort', onAbort)
  try {
    const res = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
      cache: 'no-store',
    })
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>
    if (!res.ok) {
      const probs = (data.problems as Problem[] | undefined)?.filter((p) => p.level === 'error')
      const msg = (data.error as string) || probs?.map((p) => p.msg).join('; ') || `Request failed (${res.status})`
      throw new ApiError(res.status, msg, data)
    }
    return data as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    if (opts.signal?.aborted) throw e
    throw new ApiError(0, "Can't reach the robot server. Is `python -m sidekick ui` running?")
  } finally {
    clearTimeout(timer)
    opts.signal?.removeEventListener('abort', onAbort)
  }
}

export const api = {
  info: (signal?: AbortSignal) => call<Info>('/api/info', undefined, { signal, timeout: 30000 }),
  status: (signal?: AbortSignal) => call<Status>('/api/status', undefined, { signal, timeout: 4000 }),
  /** `fit` scales the sketch up to fill the build strip; omit it to read the board at true size. */
  generate: (strokes: Stroke[], prompt: string, requestId: number, fit = false,
             color?: string | null, signal?: AbortSignal) =>
    call<{ request_id: number; builds: Build[] }>(
      '/api/generate', { strokes, prompt, request_id: requestId, fit, color: color ?? null },
      { signal, timeout: 60000 }),
  dictate: (text: string, build: Build | null, requestId: number, signal?: AbortSignal) =>
    call<{ request_id: number; reply: string; builds: Build[] }>('/api/dictate', { text, build, request_id: requestId }, { signal, timeout: 30000 }),
  /** Validate a build: problems, score, and the height gravity settles each block to
   *  (`z` is keyed by block index, in cm). */
  check: (build: Build) =>
    call<{ problems: Problem[]; stability: number; z: Record<string, number>; order: number[] }>(
      '/api/check', { build }),
  build: (build: Build, owner?: string) =>
    call<{ ok: boolean; run_id: number; server_id: string; problems: Problem[] }>('/api/build', { build, owner }, { timeout: 30000 }),
  stop: (runId: number) => call<{ ok: boolean }>('/api/stop', { run_id: runId }),
  /** Change the blocks still to come on a running build. Without `apply` this
   *  only reports what it would do, so an open mic can't alter a live build. */
  revise: (text: string, runId: number, apply = false) =>
    call<{ ok: boolean; reply: string; applied: boolean; remaining?: number; fixed?: number }>(
      '/api/revise', { text, run_id: runId, apply }, { timeout: 30000 }),
  pause: (runId: number) => call<{ ok: boolean }>('/api/pause', { run_id: runId }),
  resume: (runId: number) => call<{ ok: boolean }>('/api/resume', { run_id: runId }),
  simPoke: () => call<{ ok: boolean }>('/api/sim/poke', {}),
  currentRun: () => call<{ server_id: string; run_id: number; busy: boolean; build: Build | null; owner?: string | null }>('/api/run'),
}

export const FRAME_URL = '/api/frame.jpg'
