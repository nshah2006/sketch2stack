import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import type { Block, Stroke } from '../../types'
import { BUILDS, BLOCK_HEX } from '../../mocks/builds'
import { BlockScene } from '../build/BlockScene'

type Phase = 'draw' | 'snap' | '3d'

const HOUSE_PATHS = [
  'M102 250 C101 215 99 185 101 152 C150 149 250 151 299 150 C301 185 300 220 298 250 C240 252 160 249 102 250',
  'M92 154 C125 130 165 108 200 88 C236 108 272 130 309 153',
  'M178 250 C177 230 178 214 179 200 C192 199 208 199 221 200 C222 216 222 234 221 250',
]

// Front view of the Cottage build: unit = 50px, origin (100, 250).
const U = 50
const TILES = [
  { x: 0, y: 0, w: 2, h: 1, c: 'red' },
  { x: 2, y: 0, w: 2, h: 1, c: 'blue' },
  { x: 0, y: 1, w: 1, h: 1, c: 'yellow' },
  { x: 1, y: 1, w: 2, h: 1, c: 'red' },
  { x: 3, y: 1, w: 1, h: 1, c: 'yellow' },
] as const

const LABELS: Record<Phase, string> = {
  draw: '01  Sketch',
  snap: '02  Snap to blocks',
  '3d': '03  Build in 3D',
}

type Props = {
  strokes?: Stroke[]
  /** Blocks to reveal in the 3D phase (the first generated build); a sample house until they arrive. */
  blocks?: Block[]
  loop?: boolean
  onDone?: () => void
  className?: string
}

export function SketchTo3D({ strokes, blocks, loop = false, onDone, className }: Props) {
  const [phase, setPhase] = useState<Phase>('draw')
  const [cycle, setCycle] = useState(0)

  useEffect(() => {
    setPhase('draw')
    const t = [
      setTimeout(() => setPhase('snap'), 1700),
      setTimeout(() => setPhase('3d'), 2900),
      setTimeout(() => (loop ? setCycle((c) => c + 1) : onDone?.()), loop ? 11000 : 5600),
    ]
    return () => t.forEach(clearTimeout)
  }, [cycle, loop, onDone])

  const userPaths = strokes?.filter((s) => !s.erase && s.points.length > 1)
  const drawPaths =
    userPaths && userPaths.length
      ? userPaths.map((s) => 'M' + s.points.map(([x, y]) => `${50 + x * 300} ${y * 300}`).join(' L'))
      : HOUSE_PATHS

  const phaseIdx = phase === 'draw' ? 0 : phase === 'snap' ? 1 : 2

  return (
    <div className={`relative overflow-hidden ${className ?? ''}`}>
      <div className="absolute inset-0 pink-grid opacity-60 [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]" />

      <AnimatePresence>
        {phase !== '3d' && (
          <motion.svg
            key={`svg-${cycle}`}
            viewBox="0 0 400 300"
            className="absolute inset-0 h-full w-full"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.97, filter: 'blur(4px)', transition: { duration: 0.5 } }}
          >
            {drawPaths.map((d, i) => (
              <motion.path
                key={i}
                d={d}
                fill="none"
                stroke="var(--pink)"
                strokeWidth={3.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ pathLength: 0, opacity: 1 }}
                animate={{ pathLength: 1, opacity: phase === 'snap' ? 0.25 : 1 }}
                transition={{
                  pathLength: { duration: 1.4 / drawPaths.length, delay: (i * 1.4) / drawPaths.length, ease: 'easeInOut' },
                  opacity: { duration: 0.4 },
                }}
                style={{ filter: 'drop-shadow(0 0 6px rgba(255,46,147,0.6))' }}
              />
            ))}

            {phase === 'snap' && (
              <g>
                {TILES.map((t, i) => (
                  <motion.rect
                    key={i}
                    x={100 + t.x * U + 2}
                    y={250 - (t.y + 1) * U + 2}
                    width={t.w * U - 4}
                    height={t.h * U - 4}
                    rx={4}
                    fill={BLOCK_HEX[t.c]}
                    stroke="#0a0a0b"
                    strokeWidth={2}
                    initial={{ scale: 0.3, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: 'spring', duration: 0.45, bounce: 0.35, delay: i * 0.08 }}
                    style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
                  />
                ))}
                <motion.path
                  d="M100 150 L300 150 L200 90 Z"
                  fill={BLOCK_HEX.pink}
                  stroke="#0a0a0b"
                  strokeWidth={2}
                  strokeLinejoin="round"
                  initial={{ scale: 0.3, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: 'spring', duration: 0.45, bounce: 0.35, delay: TILES.length * 0.08 }}
                  style={{ transformBox: 'fill-box', transformOrigin: 'center bottom' }}
                />
              </g>
            )}
          </motion.svg>
        )}
      </AnimatePresence>

      {phase === '3d' && (
        <motion.div
          key={`3d-${cycle}`}
          className="absolute inset-0"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5 }}
        >
          <BlockScene blocks={blocks?.length ? blocks : BUILDS[0].blocks} intro introDelay={0.1} stagger={0.07} className="h-full w-full" />
        </motion.div>
      )}

      <div className="absolute bottom-4 left-4 flex items-center gap-3">
        <AnimatePresence mode="wait">
          <motion.span
            key={phase}
            className="font-mono text-xs tracking-[0.14em] text-pink-soft"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
          >
            {LABELS[phase].toUpperCase()}
          </motion.span>
        </AnimatePresence>
      </div>
      <div className="absolute bottom-0 left-0 right-0 flex h-[3px] gap-1 px-4 pb-0">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-full flex-1 overflow-hidden rounded-full bg-line">
            <motion.div
              className="h-full origin-left bg-pink"
              initial={false}
              animate={{ scaleX: i <= phaseIdx ? 1 : 0 }}
              transition={{ duration: i === phaseIdx ? 1.1 : 0.2, ease: 'linear' }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
