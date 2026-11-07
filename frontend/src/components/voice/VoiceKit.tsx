import { useEffect, useRef, type MutableRefObject } from 'react'
import { cn } from '@/lib/utils'
import WireframeForms from '@/components/ui/wireframe-forms'

/*
 * One look for the voice agent everywhere:
 *   AgentOrb  - the wireframe sphere = "the agent"
 *   VoiceBars - a row of bars = "listening"
 * Both read mic levels from refs every frame (no React renders while you talk).
 * A noise gate keeps them almost still in silence; each recognized word "kicks"
 * them and taps the phone's vibration motor, so it feels like it reacts to you.
 */

export type VoiceLevels = {
  levelRef: MutableRefObject<number>
  bandsRef: MutableRefObject<number[]>
  kickRef: MutableRefObject<number>
  onLevels: (bands: number[]) => void
  onWord: () => void
}

const GATE = 0.07 // below this the room is "silent"

export function useVoiceLevels(): VoiceLevels {
  const levelRef = useRef(0)
  const bandsRef = useRef<number[]>([0, 0, 0, 0, 0])
  const kickRef = useRef(0)
  const kit = useRef<VoiceLevels | null>(null)
  if (!kit.current) {
    let lastBuzz = 0
    kit.current = {
      levelRef,
      bandsRef,
      kickRef,
      onLevels: (b) => {
        const gated = b.map((x) => Math.max(0, (x - GATE) / (1 - GATE)))
        bandsRef.current = gated
        const avg = gated.reduce((a, x) => a + x, 0) / gated.length
        levelRef.current = Math.min(1, avg * 2.2)
      },
      onWord: () => {
        kickRef.current = 1
        const now = performance.now()
        if (now - lastBuzz > 120) {
          lastBuzz = now
          try {
            navigator.vibrate?.(12)
          } catch {
            /* not supported */
          }
        }
      },
    }
  }
  return kit.current
}

export function AgentOrb({
  levelRef,
  kickRef,
  listening = false,
  busy = false,
  glow = true,
  className,
}: {
  levelRef?: MutableRefObject<number>
  kickRef?: MutableRefObject<number>
  /** Hold still in silence, move with speech. */
  listening?: boolean
  /** Spin faster (agent is working). */
  busy?: boolean
  glow?: boolean
  className?: string
}) {
  return (
    <div className={cn('relative', className)}>
      {glow && <div className="pointer-events-none absolute inset-[-25%] rounded-full bg-[radial-gradient(circle,rgba(255,46,147,0.18),transparent_65%)]" />}
      <WireframeForms variant="sphere" speed={busy ? 2.4 : 1.2} length={1.05} levelRef={levelRef} kickRef={kickRef} listening={listening} />
    </div>
  )
}

export function VoiceBars({
  bandsRef,
  kickRef,
  active,
  count = 32,
  className,
}: {
  bandsRef: MutableRefObject<number[]>
  kickRef?: MutableRefObject<number>
  active: boolean
  count?: number
  className?: string
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const activeRef = useRef(active)
  activeRef.current = active

  useEffect(() => {
    const bars = Array.from(wrap.current?.children ?? []) as HTMLElement[]
    const n = bars.length
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const cur = new Array(n).fill(0.15)
    let ripple = 0
    let raf = 0
    const tick = (now: number) => {
      const t = now / 1000
      const bands = bandsRef.current
      // A word sends a ripple out from the middle.
      if (kickRef && kickRef.current > 0.5) ripple = 1
      ripple *= 0.9
      for (let i = 0; i < n; i++) {
        const wave = 0.5 + 0.5 * Math.sin(t * 1.1 + i * 0.42) * Math.sin(t * 0.37 + i * 0.13)
        const pos = Math.abs(i - (n - 1) / 2) / ((n - 1) / 2) // 0 middle .. 1 edges
        let target = reduce ? 0.2 : 0.12 + wave * 0.28 // idle: slow rolling wave
        if (activeRef.current) {
          const band = bands[Math.min(4, Math.floor(pos * 5))] ?? 0
          // listening: flat line in silence, tall where the voice is
          target = 0.05 + band * 0.95 + band * wave * 0.15 + ripple * Math.max(0, 0.5 - Math.abs(pos - (1 - ripple))) * 0.8
        }
        const k = target > cur[i] ? 0.5 : 0.14 // snap up, ease down
        cur[i] += (target - cur[i]) * k
        bars[i].style.transform = `scaleY(${Math.min(Math.max(cur[i], 0.04), 1).toFixed(3)})`
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [bandsRef, kickRef, count])

  return (
    <div ref={wrap} className={cn('flex h-9 items-center justify-center gap-[3px]', className)} aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        <span
          key={i}
          className={cn('h-full w-[3px] origin-center rounded-full transition-colors duration-300', active ? 'bg-pink' : 'bg-pink/40')}
          style={{ transform: 'scaleY(0.15)' }}
        />
      ))}
    </div>
  )
}
