import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, Check, OctagonX, Pause, Play, RotateCcw } from 'lucide-react'
import type { Build } from '../../types'
import { buildSteps } from '../../mocks/builds'
import { BlockScene } from '../build/BlockScene'
import { CameraFeed } from './CameraFeed'

type Status = 'running' | 'paused' | 'halted' | 'done'

export function LiveStage({ build, onBack, onDone }: { build: Build; onBack: () => void; onDone: () => void }) {
  const steps = useMemo(() => buildSteps(build.blocks), [build])
  const [step, setStep] = useState(0)
  const [status, setStatus] = useState<Status>('running')
  const listRef = useRef<HTMLOListElement>(null)

  useEffect(() => {
    if (status !== 'running') return
    const id = setInterval(() => setStep((s) => Math.min(s + 1, steps.length)), 2600)
    return () => clearInterval(id)
  }, [status, steps.length])

  useEffect(() => {
    if (status === 'running' && step >= steps.length) {
      setStatus('done')
      onDone()
    }
  }, [step, status, steps.length, onDone])

  useEffect(() => {
    listRef.current?.querySelector('[data-current="true"]')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [step])

  const ghostIds = useMemo(() => new Set(steps.slice(step + 1).map((s) => s.block.id)), [steps, step])
  const cur = steps[Math.min(step, steps.length - 1)]
  const action =
    status === 'halted' ? 'E-STOP engaged. All servos holding.' : status === 'done' ? 'Build complete. Arm returning home.' : status === 'paused' ? 'Paused.' : `${cur.label} ${cur.detail}`

  const reset = () => {
    setStep(0)
    setStatus('running')
  }

  return (
    <div className="grid h-full min-h-0 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:overflow-hidden lg:p-6">
      <section className="flex min-h-0 flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="label">Build phase · robot view</span>
            <h2 className="mt-1 text-xl font-semibold tracking-tight">Building “{build.name}”</h2>
          </div>
          <button className="btn-ghost" onClick={onBack}>
            <ArrowLeft size={15} /> Builds
          </button>
        </div>

        <AnimatePresence>
          {status === 'halted' && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="flex items-center gap-3 rounded-xl border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                <OctagonX size={18} /> Emergency stop. Clear the area, then reset to start over.
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <CameraFeed status={status} action={action} />

        <div className="flex flex-wrap items-center gap-2">
          {status === 'running' ? (
            <button className="btn-ghost" onClick={() => setStatus('paused')}>
              <Pause size={15} /> Pause
            </button>
          ) : status === 'paused' ? (
            <button className="btn-pink" onClick={() => setStatus('running')}>
              <Play size={15} /> Resume
            </button>
          ) : (
            <button className="btn-ghost" onClick={reset}>
              <RotateCcw size={15} /> Reset
            </button>
          )}
          <div className="ml-auto flex items-center gap-3">
            <span className="font-mono text-xs tabular-nums text-muted">
              {Math.min(step + (status === 'done' ? 0 : 1), steps.length)}/{steps.length}
            </span>
            <button
              className="btn bg-red-600 font-semibold text-white hover:bg-red-500 hover:shadow-[0_0_24px_rgba(239,68,68,0.5)]"
              onClick={() => setStatus('halted')}
              disabled={status === 'halted' || status === 'done'}
            >
              <OctagonX size={16} /> E-STOP
            </button>
          </div>
        </div>
      </section>

      <aside className="flex min-h-0 flex-col gap-3">
        <div className="panel relative aspect-[4/3] overflow-hidden dot-grid">
          <span className="label absolute left-3 top-3 z-10">Target</span>
          <BlockScene blocks={build.blocks} animate={false} ghostIds={ghostIds} highlightId={status === 'done' ? undefined : cur.block.id} className="h-full w-full" />
        </div>

        <div className="panel flex min-h-[200px] flex-1 flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="label">Build steps</span>
            <div className="h-1 w-24 overflow-hidden rounded-full bg-line">
              <motion.div className="h-full bg-pink" animate={{ width: `${(Math.min(step + (status === 'done' ? 1 : 0), steps.length) / steps.length) * 100}%` }} />
            </div>
          </div>
          <ol ref={listRef} className="flex-1 space-y-1 overflow-y-auto p-2">
            {steps.map((s, i) => {
              const done = i < step || status === 'done'
              const current = i === step && status !== 'done'
              return (
                <li
                  key={s.block.id}
                  data-current={current}
                  className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${current ? 'bg-pink-dim' : ''}`}
                >
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-[10px] ${
                      done ? 'border-pink bg-pink text-black' : current ? 'border-pink text-pink' : 'border-line text-muted'
                    }`}
                  >
                    {done ? <Check size={12} strokeWidth={3} /> : i + 1}
                  </span>
                  <div className="min-w-0">
                    <div className={`capitalize ${done ? 'text-muted' : ''}`}>{s.label}</div>
                    <div className="font-mono text-[11px] text-muted">{s.detail}</div>
                  </div>
                  {current && status === 'running' && <span className="ml-auto h-1.5 w-1.5 animate-pulse rounded-full bg-pink" />}
                </li>
              )
            })}
          </ol>
        </div>
      </aside>
    </div>
  )
}
