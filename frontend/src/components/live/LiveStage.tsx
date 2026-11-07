import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, Check, Hand, Loader2, OctagonX, Pause, Play, RotateCcw, ServerCrash, X } from 'lucide-react'
import type { Build, Run } from '../../types'
import { api } from '../../api'
import { useBackend, useLiveStatus } from '../../backend'
import { useToast } from '../Toast'
import { BlockScene } from '../build/BlockScene'
import { CameraFeed } from './CameraFeed'
import { AgentDock, type ArmAgent } from '../talk/AgentDock'

type Phase = 'running' | 'paused' | 'safety' | 'halted' | 'failed' | 'done'

type Props = {
  run: Run | null
  onBack: () => void
  onDone: (run: Run) => void
  onRestart: (build: Build) => void
  starting?: boolean
  /** The arm agent dock (talk/type to steer the build). */
  agentOpen: boolean
  onAgentOpen: (open: boolean) => void
}

/** Everything on this screen comes from the robot server's status for THIS run.
 *  If the server restarted or a different build is running, it says so instead
 *  of showing someone else's progress. */
export function LiveStage({ run, onBack, onDone, onRestart, starting, agentOpen, onAgentOpen }: Props) {
  const { status, error } = useLiveStatus(!!run)
  const { info } = useBackend()
  const toast = useToast()
  const [pending, setPending] = useState(false)
  const reported = useRef<number | null>(null)
  const listRef = useRef<HTMLOListElement>(null)

  const stale: null | 'restarted' | 'other' =
    !run || !status ? null : status.server_id !== run.serverId ? 'restarted' : status.run_id !== run.runId ? 'other' : null
  const mine = run && status && !stale ? status : null

  const phase: Phase = !mine
    ? 'halted'
    : mine.result === 'done'
      ? 'done'
      : mine.result === 'stopped'
        ? 'halted'
        : mine.result
          ? 'failed'
          : mine.safety
            ? 'safety'
            : mine.paused
              ? 'paused'
              : 'running'

  const steps = mine?.steps ?? []
  const blockId = (i: number) => run?.build.blocks[steps[i]?.index]?.id
  const doneCount = steps.filter((s) => s.state === 'done').length
  const curIdx = Math.max(0, steps.findIndex((s) => s.state === 'active' || s.state === 'todo'))
  const ghostIds = useMemo(
    () => new Set(steps.map((s, i) => (s.state === 'todo' ? blockId(i) : undefined)).filter(Boolean) as string[]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mine?.steps, run],
  )
  const activeId = steps.findIndex((s) => s.state === 'active')

  // Mark the project built exactly once per run.
  useEffect(() => {
    if (run && phase === 'done' && reported.current !== run.runId) {
      reported.current = run.runId
      onDone(run)
    }
  }, [phase, run, onDone])

  useEffect(() => {
    listRef.current?.querySelector('[data-current="true"]')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [curIdx])

  const act = async (fn: (id: number) => Promise<unknown>) => {
    if (!run || pending) return
    setPending(true)
    try {
      await fn(run.runId)
    } catch (e) {
      toast((e as Error).message)
    } finally {
      setPending(false)
    }
  }

  if (!run) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <span className="label">Build phase</span>
        <p className="max-w-sm text-muted">Nothing is building. Pick an interpretation and press “Build this”.</p>
        <button className="btn-ghost" onClick={onBack}>
          <ArrowLeft size={15} /> Builds
        </button>
      </div>
    )
  }

  const action = stale
    ? stale === 'restarted'
      ? 'The robot server restarted. This build is no longer running.'
      : 'A different build is running on the arm now.'
    : !mine
      ? 'Connecting to the arm…'
      : phase === 'done'
        ? 'Build complete. Arm returning home.'
        : phase === 'halted'
          ? 'Stopped. All servos holding.'
          : phase === 'failed'
            ? `Build ${mine.result}. Check the log.`
            : phase === 'safety'
              ? 'Paused: hand near the arm. Resumes 1 s after the area is clear.'
              : mine.prompt ?? mine.action ?? ''

  const need = () => {
    if (!run || stale || !mine) throw new Error('not connected to this build')
    return run.runId
  }
  const agent: ArmAgent = {
    phase,
    live: !stale && !!mine?.busy,
    sim: !!info?.sim,
    done: doneCount,
    total: steps.length || run.build.blocks.length,
    current: steps[curIdx]?.label,
    pause: () => api.pause(need()),
    resume: () => api.resume(need()),
    stop: () => api.stop(need()),
    poke: () => api.simPoke(),
    again: () => onRestart(run.build),
  }

  return (
    <>
    <div className="grid h-full min-h-0 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:overflow-hidden lg:p-6">
      <section className="flex min-h-0 flex-col gap-3 lg:overflow-y-auto lg:pr-1">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="label">Build phase · {info?.sim ? 'simulator' : 'robot view'}</span>
            <h2 className="mt-1 text-xl font-semibold tracking-tight">Building “{run.build.name}”</h2>
          </div>
          <button className="btn-ghost" onClick={onBack}>
            <ArrowLeft size={15} /> Builds
          </button>
        </div>

        <AnimatePresence>
          {(stale || error || phase === 'safety' || phase === 'halted' || (mine?.prompt && phase === 'running')) && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
              {stale || error ? (
                <Banner tone="red" icon={<ServerCrash size={18} />}>
                  {error ?? action}
                </Banner>
              ) : phase === 'safety' ? (
                <Banner tone="red" icon={<Hand size={18} />}>
                  Hand near the arm: frozen. It resumes by itself 1 s after the area is clear.
                </Banner>
              ) : phase === 'halted' ? (
                <Banner tone="red" icon={<OctagonX size={18} />}>
                  Emergency stop. Clear the area, then start the build again.
                </Banner>
              ) : (
                <Banner tone="pink" icon={<Hand size={18} />}>
                  {mine?.prompt}
                </Banner>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        <CameraFeed status={stale ? 'offline' : phase} action={action} />

        <div className="flex flex-wrap items-center gap-2">
          {!stale && (phase === 'running' || phase === 'safety') ? (
            <button className="btn-ghost" onClick={() => act(api.pause)} disabled={pending}>
              <Pause size={15} /> Pause
            </button>
          ) : !stale && phase === 'paused' ? (
            <button className="btn-pink" onClick={() => act(api.resume)} disabled={pending}>
              <Play size={15} /> Resume
            </button>
          ) : (
            <button className="btn-ghost" onClick={() => onRestart(run.build)} disabled={starting || (!!mine && mine.busy)}>
              {starting ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />} Build again
            </button>
          )}
          {info?.sim && !stale && phase !== 'done' && (
            <button className="btn-ghost" onClick={() => api.simPoke().catch(() => {})} title="Simulated person reaches toward the arm">
              <Hand size={15} /> Sim: reach in
            </button>
          )}
          <div className="ml-auto flex items-center gap-3">
            <span className="font-mono text-xs tabular-nums text-muted">
              {doneCount}/{steps.length || run.build.blocks.length}
            </span>
            <button
              className="btn bg-red-600 font-semibold text-white hover:bg-red-500 hover:shadow-[0_0_24px_rgba(239,68,68,0.5)] disabled:opacity-50"
              onClick={() => act(api.stop)}
              disabled={!!stale || !mine || !mine.busy}
            >
              <OctagonX size={16} /> E-STOP
            </button>
          </div>
        </div>

        {/* Talk or type to steer the build: opens right under the controls */}
        <AgentDock open={agentOpen} onOpenChange={onAgentOpen} agent={agent} className="mt-auto pt-1" />
      </section>

      <aside className="flex min-h-0 flex-col gap-3">
        <div className="panel relative aspect-[4/3] overflow-hidden dot-grid">
          <span className="label absolute left-3 top-3 z-10">Target</span>
          <BlockScene
            blocks={run.build.blocks}
            animate={false}
            ghostIds={stale ? undefined : ghostIds}
            highlightId={phase === 'running' || phase === 'paused' || phase === 'safety' ? blockId(activeId) : undefined}
            className="h-full w-full"
          />
        </div>

        <div className="panel flex min-h-[200px] flex-1 flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="label">Build steps</span>
            <div className="h-1 w-24 overflow-hidden rounded-full bg-line">
              <motion.div className="h-full bg-pink" animate={{ width: `${steps.length ? (doneCount / steps.length) * 100 : 0}%` }} />
            </div>
          </div>
          <ol ref={listRef} className="flex-1 space-y-1 overflow-y-auto p-2">
            {steps.map((s, i) => {
              const done = s.state === 'done'
              const failed = s.state === 'failed'
              const current = s.state === 'active'
              return (
                <li
                  key={`${run.runId}-${i}`}
                  data-current={current}
                  className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${current ? 'bg-pink-dim' : ''}`}
                >
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-[10px] ${
                      done ? 'border-pink bg-pink text-black' : failed ? 'border-red-500 text-red-400' : current ? 'border-pink text-pink' : 'border-line text-muted'
                    }`}
                  >
                    {done ? <Check size={12} strokeWidth={3} /> : failed ? <X size={12} /> : i + 1}
                  </span>
                  <div className={`min-w-0 ${done ? 'text-muted' : ''}`}>{s.label}</div>
                  {current && phase === 'running' && <span className="ml-auto h-1.5 w-1.5 animate-pulse rounded-full bg-pink" />}
                </li>
              )
            })}
            {!steps.length && <li className="px-2.5 py-2 text-sm text-muted">{stale ? 'No progress for this build.' : 'Waiting for the arm…'}</li>}
          </ol>
          {mine && mine.log.length > 0 && (
            <div className="max-h-28 overflow-y-auto border-t border-line px-3 py-2 font-mono text-[11px] text-muted">
              {mine.log.slice(-6).map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
    </>
  )
}

function Banner({ tone, icon, children }: { tone: 'red' | 'pink'; icon: ReactNode; children: ReactNode }) {
  const cls = tone === 'red' ? 'border-red-500/50 bg-red-500/10 text-red-300' : 'border-pink/50 bg-pink-dim text-pink-soft'
  return <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-sm font-medium ${cls}`}>{icon} {children}</div>
}
