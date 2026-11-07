import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FileJson, ImageDown, Link2, Share2 } from 'lucide-react'
import type { Build } from '../../types'
import { buildSteps } from '../../mocks/builds'
import { useToast } from '../Toast'

export function ExportMenu({ build, projectId }: { build: Build; projectId: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const toast = useToast()

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  const items = [
    {
      icon: ImageDown,
      label: 'Snapshot PNG',
      run: () => toast('PNG export coming soon'),
    },
    {
      icon: FileJson,
      label: 'Step list (JSON)',
      run: () => {
        const data = { build: build.id, steps: buildSteps(build.blocks).map((s) => ({ ...s.block, step: s.index + 1 })) }
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
        const a = document.createElement('a')
        a.href = url
        a.download = `${build.id}-steps.json`
        a.click()
        URL.revokeObjectURL(url)
        toast('Step list downloaded')
      },
    },
    {
      icon: Link2,
      label: 'Copy share link',
      run: async () => {
        try {
          await navigator.clipboard.writeText(`${location.origin}/share/${projectId}/${build.id}`)
          toast('Link copied (placeholder URL)')
        } catch {
          toast('Clipboard blocked')
        }
      },
    },
  ]

  return (
    <div ref={ref} className="relative">
      <button className="btn-ghost w-full" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Share2 size={16} /> Export / share
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.1 } }}
            transition={{ type: 'spring', duration: 0.25, bounce: 0 }}
            style={{ transformOrigin: 'bottom center' }}
            className="absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-xl border border-line bg-raised p-1 shadow-2xl"
          >
            {items.map((it) => (
              <button
                key={it.label}
                onClick={() => {
                  it.run()
                  setOpen(false)
                }}
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-muted transition-colors hover:bg-pink-dim hover:text-fg"
              >
                <it.icon size={15} /> {it.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
