import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronLeft, ChevronRight, Hand, Rotate3d } from 'lucide-react'
import type { Build } from '../../types'
import { BlockScene } from './BlockScene'

type Props = {
  builds: Build[]
  index: number
  onIndex: (i: number) => void
}

const variants = {
  enter: (dir: number) => ({ x: dir * 120, opacity: 0, scale: 0.96 }),
  center: { x: 0, opacity: 1, scale: 1 },
  exit: (dir: number) => ({ x: dir * -120, opacity: 0, scale: 0.96 }),
}

export function BuildCarousel({ builds, index, onIndex }: Props) {
  const [dir, setDir] = useState(1)
  const [orbit, setOrbit] = useState(false)
  const build = builds[index]

  const go = (d: number) => {
    setDir(d)
    onIndex((index + d + builds.length) % builds.length)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return
      if (e.key === 'ArrowRight') go(1)
      if (e.key === 'ArrowLeft') go(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="label flex items-center gap-2">
            Interpretation {index + 1} of {builds.length}
            {build.problems?.some((p) => p.level === 'error') && (
              <span className="rounded-full border border-red-500/50 bg-red-500/10 px-2 py-0.5 font-sans text-[10px] normal-case tracking-normal text-red-300">
                Arm can’t build this one
              </span>
            )}
          </span>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={build.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
              <h2 className="mt-1 text-xl font-semibold tracking-tight">{build.name}</h2>
              <p className="mt-0.5 text-sm text-muted">{build.blurb}</p>
            </motion.div>
          </AnimatePresence>
        </div>
        <Stability value={build.stability} />
      </div>

      <div data-build-view className="panel relative min-h-[280px] flex-1 overflow-hidden dot-grid">
        <AnimatePresence initial={false} custom={dir} mode="popLayout">
          <motion.div
            key={build.id}
            custom={dir}
            variants={variants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ type: 'spring', duration: 0.45, bounce: 0.15 }}
            drag={orbit ? false : 'x'}
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={0.5}
            onDragEnd={(_, info) => {
              if (info.offset.x < -80 || info.velocity.x < -500) go(1)
              else if (info.offset.x > 80 || info.velocity.x > 500) go(-1)
            }}
            className={`absolute inset-0 ${orbit ? '' : 'cursor-grab active:cursor-grabbing'}`}
          >
            <BlockScene blocks={build.blocks} interactive={orbit} autoRotate className="h-full w-full" />
          </motion.div>
        </AnimatePresence>

        <button onClick={() => go(-1)} className="absolute left-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-line bg-ink/80 backdrop-blur transition hover:border-pink hover:text-pink active:scale-95" aria-label="Previous interpretation">
          <ChevronLeft size={20} />
        </button>
        <button onClick={() => go(1)} className="absolute right-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-line bg-ink/80 backdrop-blur transition hover:border-pink hover:text-pink active:scale-95" aria-label="Next interpretation">
          <ChevronRight size={20} />
        </button>

        <div className="absolute right-3 top-3 flex rounded-lg border border-line bg-ink/80 p-0.5 text-xs backdrop-blur">
          <button onClick={() => setOrbit(false)} className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 transition-colors ${!orbit ? 'bg-pink text-black' : 'text-muted hover:text-fg'}`}>
            <Hand size={13} /> Swipe
          </button>
          <button onClick={() => setOrbit(true)} className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 transition-colors ${orbit ? 'bg-pink text-black' : 'text-muted hover:text-fg'}`}>
            <Rotate3d size={13} /> Orbit
          </button>
        </div>

        <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-2">
          {builds.map((b, i) => (
            <button
              key={b.id}
              onClick={() => {
                setDir(i > index ? 1 : -1)
                onIndex(i)
              }}
              aria-label={`Show ${b.name}`}
              className="relative h-2 w-6 overflow-hidden rounded-full bg-line"
            >
              {i === index && <motion.span layoutId="carousel-dot" className="absolute inset-0 rounded-full bg-pink" transition={{ type: 'spring', duration: 0.35, bounce: 0.2 }} />}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function Stability({ value }: { value: number }) {
  const r = 18
  const c = 2 * Math.PI * r
  return (
    <div className="flex shrink-0 items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2">
      <svg width="44" height="44" viewBox="0 0 44 44" className="-rotate-90">
        <circle cx="22" cy="22" r={r} stroke="var(--line)" strokeWidth="4" fill="none" />
        <motion.circle
          cx="22"
          cy="22"
          r={r}
          stroke="var(--pink)"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={false}
          animate={{ strokeDashoffset: c * (1 - value / 100) }}
          transition={{ type: 'spring', duration: 0.6, bounce: 0 }}
        />
      </svg>
      <div>
        <div className="font-mono text-lg leading-none tabular-nums">{value}%</div>
        <div className="label mt-1 !text-[10px]">Stability</div>
      </div>
    </div>
  )
}
