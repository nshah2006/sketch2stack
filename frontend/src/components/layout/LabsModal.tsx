import { useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Gauge, Glasses, Mic2, ShieldAlert, Users, Video, X } from 'lucide-react'

const IDEAS = [
  { icon: ShieldAlert, title: 'Feasibility check', body: 'Warn before building if the camera cannot find enough blocks or the stack would tip.' },
  { icon: Gauge, title: 'Difficulty slider', body: 'Trade detail for speed: fewer, bigger blocks vs. more faithful builds.' },
  { icon: Video, title: 'Build replay', body: 'Time-lapse of the arm building, auto-saved to the project.' },
  { icon: Mic2, title: 'Voice sketching', body: '“Draw a bridge with two towers” without touching the board.' },
  { icon: Users, title: 'Draw together', body: 'Multiple people on one board, one build.' },
  { icon: Glasses, title: 'AR preview', body: 'Place the 3D build on your real table through a phone camera before the arm starts.' },
]

export function LabsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[60] flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            role="dialog"
            aria-label="Labs"
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ type: 'spring', duration: 0.4, bounce: 0.1 }}
            className="relative max-h-[85dvh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-line bg-surface p-6"
          >
            <button className="icon-btn absolute right-3 top-3" onClick={onClose} aria-label="Close">
              <X size={17} />
            </button>
            <span className="label">Labs</span>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">Coming next</h2>
            <p className="mt-1 text-sm text-muted">Ideas on the roadmap. Not built yet.</p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {IDEAS.map((it, i) => (
                <motion.div
                  key={it.title}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.05 + i * 0.04, type: 'spring', duration: 0.4, bounce: 0 }}
                  className="rounded-xl border border-line bg-raised p-4"
                >
                  <it.icon size={18} className="text-pink" />
                  <div className="mt-3 text-sm font-medium">{it.title}</div>
                  <div className="mt-1 text-xs leading-relaxed text-muted">{it.body}</div>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
