import { AlertTriangle, Bot, Loader2, PenLine, RefreshCw } from 'lucide-react'
import type { Build, Stroke } from '../../types'
import { BuildCarousel } from './BuildCarousel'
import { InventoryPanel } from './InventoryPanel'
import { ExportMenu } from './ExportMenu'
import { SketchThumb } from './Thumbs'

type Props = {
  builds: Build[]
  index: number
  onIndex: (i: number) => void
  strokes: Stroke[]
  prompt: string
  projectId: string
  onEditSketch: () => void
  onRegenerate: () => void
  onBuild: () => void
  starting?: boolean
}

export function ChooseStage({ builds, index, onIndex, strokes, prompt, projectId, onEditSketch, onRegenerate, onBuild, starting }: Props) {
  const build = builds[index]
  const errors = build.problems?.filter((p) => p.level === 'error') ?? []
  const warns = build.problems?.filter((p) => p.level === 'warn') ?? []
  return (
    <div className="grid h-full min-h-0 gap-4 overflow-y-auto p-4 lg:grid-cols-[220px_minmax(0,1fr)_260px] lg:overflow-hidden lg:p-6">
      {/* Your sketch */}
      <aside className="flex flex-col gap-3">
        <span className="label">Your sketch</span>
        <div className="panel dot-grid aspect-[4/3] overflow-hidden p-2">
          <SketchThumb strokes={strokes} className="h-full w-full" />
        </div>
        {prompt && <p className="rounded-lg border border-line bg-surface px-3 py-2 text-xs text-muted">“{prompt}”</p>}
        <button className="btn-ghost" onClick={onEditSketch}>
          <PenLine size={15} /> Edit sketch
        </button>
        <button className="btn-ghost" onClick={onRegenerate}>
          <RefreshCw size={15} /> Regenerate
        </button>
      </aside>

      <section className="min-h-[420px] lg:min-h-0">
        <BuildCarousel builds={builds} index={index} onIndex={onIndex} />
      </section>

      <aside className="flex flex-col gap-3">
        <InventoryPanel blocks={build.blocks} />
        {(errors.length > 0 || warns.length > 0) && (
          <ul className="panel space-y-1.5 p-3 text-xs">
            {[...errors, ...warns].slice(0, 4).map((p, i) => (
              <li key={i} className={`flex gap-2 ${p.level === 'error' ? 'text-pink-soft' : 'text-muted'}`}>
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>
                  {p.index !== null && p.index !== undefined ? `Block ${p.index + 1}: ` : ''}
                  {p.msg}
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-auto flex flex-col gap-2">
          <ExportMenu build={build} projectId={projectId} />
          <button className="btn-pink py-3 text-base disabled:opacity-50" onClick={onBuild} disabled={starting || errors.length > 0}>
            {starting ? <Loader2 size={18} className="animate-spin" /> : <Bot size={18} />} {starting ? 'Starting…' : 'Build this'}
          </button>
        </div>
      </aside>
    </div>
  )
}
