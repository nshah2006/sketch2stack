import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Info, type Status } from './api'

/**
 * One place that knows about the robot server.
 * - Loads /api/info once (and again whenever the server restarts).
 * - Polls /api/status while someone is watching (useLiveStatus).
 * - Exposes the server_id so stored run ids from an older server are ignored.
 */
type Backend = { info: Info | null; online: boolean; serverId: string | null; refresh: () => void }

const Ctx = createContext<Backend>({ info: null, online: false, serverId: null, refresh: () => {} })

export function BackendProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<Info | null>(null)
  const [online, setOnline] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const ctrl = new AbortController()
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      try {
        const i = await api.info(ctrl.signal)
        if (!alive) return
        setInfo(i)
        setOnline(true)
      } catch {
        if (!alive) return
        setOnline(false)
        timer = setTimeout(load, 3000) // keep trying until the server is up
      }
    }
    load()
    return () => {
      alive = false
      ctrl.abort()
      clearTimeout(timer)
    }
  }, [tick])

  // Notice server restarts (new server_id) or outages with a slow heartbeat.
  useEffect(() => {
    if (!info) return
    const ctrl = new AbortController()
    const id = setInterval(async () => {
      try {
        const s = await api.status(ctrl.signal)
        setOnline(true)
        if (s.server_id !== info.server_id) setTick((t) => t + 1)
      } catch {
        if (!ctrl.signal.aborted) setOnline(false)
      }
    }, 5000)
    return () => {
      clearInterval(id)
      ctrl.abort()
    }
  }, [info])

  return (
    <Ctx.Provider value={{ info, online, serverId: info?.server_id ?? null, refresh: () => setTick((t) => t + 1) }}>
      {children}
    </Ctx.Provider>
  )
}

export const useBackend = () => useContext(Ctx)

/** Poll /api/status every `ms` while `enabled`. Never applies a response that arrives after unmount
 *  or after a newer one (sequence numbers), so the view can't jump backwards. */
export function useLiveStatus(enabled: boolean, ms = 400) {
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)
  const applied = useRef(0)

  useEffect(() => {
    if (!enabled) return
    const ctrl = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      const mine = ++seq.current
      try {
        const s = await api.status(ctrl.signal)
        if (ctrl.signal.aborted || mine < applied.current) return
        applied.current = mine
        setStatus(s)
        setError(null)
      } catch (e) {
        if (ctrl.signal.aborted) return
        setError((e as Error).message)
      }
      if (!ctrl.signal.aborted) timer = setTimeout(poll, ms)
    }
    poll()
    return () => {
      ctrl.abort()
      clearTimeout(timer)
    }
  }, [enabled, ms])

  return { status, error }
}
