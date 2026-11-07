import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import type { Stroke } from '../../types'
import { SketchTo3D } from './SketchTo3D'

const STEPS = ['Reading your sketch', 'Matching block shapes', 'Checking stability', 'Generating 4 interpretations']

export function GeneratingScreen({ strokes, onDone }: { strokes: Stroke[]; onDone: () => void }) {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI((x) => Math.min(x + 1, STEPS.length - 1)), 1300)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-4">
      <SketchTo3D strokes={strokes} onDone={onDone} className="panel aspect-[4/3] w-full max-w-2xl dot-grid" />
      <div className="flex h-7 items-center gap-3">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-pink opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-pink" />
        </span>
        <AnimatePresence mode="wait">
          <motion.span
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="text-sm text-muted"
          >
            {STEPS[i]}…
          </motion.span>
        </AnimatePresence>
      </div>
      <button className="label hover:text-pink" onClick={onDone}>
        Skip
      </button>
    </div>
  )
}
