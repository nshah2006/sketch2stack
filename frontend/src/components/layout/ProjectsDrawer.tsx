import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Copy, FolderOpen, MoreHorizontal, PenLine, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import type { Project } from '../../types'
import { useProjects } from '../../store/projects'
import { IsoThumb, SketchThumb } from '../build/Thumbs'

export type ProjectAction = 'open' | 'edit' | 'regenerate'

type Props = {
  open: boolean
  onClose: () => void
  activeId: string | null
  onAction: (p: Project, a: ProjectAction) => void
  onNew: () => void
}

const STATUS: Record<Project['status'], string> = {
  draft: 'border-line text-muted',
  generated: 'border-pink/50 text-pink-soft',
  built: 'border-pink bg-pink text-black',
}

function ago(ts: number) {
  const d = Math.floor((Date.now() - ts) / 86_400_000)
  if (d <= 0) return 'Today'
  if (d === 1) return 'Yesterday'
  return `${d} days ago`
}

export function ProjectsDrawer({ open, onClose, activeId, onAction, onNew }: Props) {
  const { projects } = useProjects()
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<'all' | Project['status']>('all')

  const shown = projects.filter((p) => (filter === 'all' || p.status === filter) && p.name.toLowerCase().includes(q.toLowerCase()))

  return (
    <AnimatePresence initial={false}>
      {open && (
        <>
          {/* scrim on small screens */}
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="fixed inset-0 z-30 bg-black/60 xl:hidden" />
          <motion.aside
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', duration: 0.4, bounce: 0 }}
            className="fixed bottom-0 right-0 top-0 z-40 flex w-[min(340px,92vw)] flex-col border-l border-line bg-surface xl:static xl:z-auto xl:w-[320px]"
          >
            <header className="flex items-center justify-between px-4 pb-3 pt-4">
              <div>
                <span className="label">Your projects</span>
                <div className="mt-0.5 text-sm text-muted">{projects.length} saved</div>
              </div>
              <div className="flex gap-1">
                <button className="icon-btn" onClick={onNew} aria-label="New project" title="New project">
                  <Plus size={17} />
                </button>
                <button className="icon-btn" onClick={onClose} aria-label="Close projects">
                  <X size={17} />
                </button>
              </div>
            </header>

            <div className="space-y-2 px-4 pb-3">
              <div className="relative">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
                <input className="input py-2 pl-9 text-xs" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <div className="flex gap-1 text-[11px]">
                {(['all', 'draft', 'generated', 'built'] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`rounded-full px-2.5 py-1 capitalize transition-colors ${filter === f ? 'bg-pink text-black' : 'text-muted hover:text-fg'}`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            <ul className="flex-1 space-y-2 overflow-y-auto px-4 pb-4">
              <AnimatePresence initial={false}>
                {shown.map((p) => (
                  <ProjectCard key={p.id} p={p} active={p.id === activeId} onAction={onAction} />
                ))}
              </AnimatePresence>
              {!shown.length && <li className="py-10 text-center text-sm text-muted">No projects match.</li>}
            </ul>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function ProjectCard({ p, active, onAction }: { p: Project; active: boolean; onAction: Props['onAction'] }) {
  const { remove, duplicate } = useProjects()
  const [menu, setMenu] = useState(false)
  const build = p.builds?.length ? p.builds[p.selectedBuild] ?? p.builds[0] : null

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 40, transition: { duration: 0.18 } }}
      transition={{ type: 'spring', duration: 0.35, bounce: 0 }}
      className={`group relative rounded-xl border p-2.5 transition-colors ${active ? 'border-pink/70 bg-pink-dim' : 'border-line bg-raised hover:border-pink/40'}`}
    >
      <button className="block w-full text-left" onClick={() => onAction(p, 'open')}>
        <div className="grid grid-cols-2 gap-1.5">
          <div className="aspect-[4/3] overflow-hidden rounded-lg bg-surface dot-grid">
            <SketchThumb strokes={p.strokes} className="h-full w-full" />
          </div>
          <div className="flex aspect-[4/3] items-center justify-center overflow-hidden rounded-lg bg-surface p-2">
            {build ? <IsoThumb blocks={build.blocks} className="h-full w-full" /> : <span className="label !text-[9px]">No build</span>}
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 pr-7">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{p.name}</div>
            <div className="text-[11px] text-muted">{ago(p.updatedAt)}</div>
          </div>
          <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] capitalize ${STATUS[p.status]}`}>{p.status}</span>
        </div>
      </button>

      <button className="icon-btn absolute bottom-2.5 right-1.5 h-7 w-7" onClick={() => setMenu((m) => !m)} aria-label="Project actions">
        <MoreHorizontal size={15} />
      </button>
      <AnimatePresence>
        {menu && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.1 } }}
            transition={{ type: 'spring', duration: 0.2, bounce: 0 }}
            onMouseLeave={() => setMenu(false)}
            className="absolute bottom-10 right-1.5 z-10 w-48 origin-bottom-right rounded-xl border border-line bg-ink p-1 shadow-2xl"
          >
            {[
              { icon: FolderOpen, label: 'Open', run: () => onAction(p, 'open') },
              { icon: PenLine, label: 'Edit drawing', run: () => onAction(p, 'edit') },
              { icon: RefreshCw, label: 'Generate new builds', run: () => onAction(p, 'regenerate') },
              { icon: Copy, label: 'Duplicate', run: () => duplicate(p.id) },
              { icon: Trash2, label: 'Delete', run: () => remove(p.id), danger: true },
            ].map((it) => (
              <button
                key={it.label}
                onClick={() => {
                  it.run()
                  setMenu(false)
                }}
                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                  it.danger ? 'text-muted hover:bg-red-500/10 hover:text-red-400' : 'text-muted hover:bg-raised hover:text-fg'
                }`}
              >
                <it.icon size={14} /> {it.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}
