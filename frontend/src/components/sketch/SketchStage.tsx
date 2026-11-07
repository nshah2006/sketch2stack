import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Eraser, PenLine, Redo2, Sparkles, Trash2, Undo2, Wand2 } from 'lucide-react'
import type { Stroke } from '../../types'
import { TEMPLATES } from '../../mocks/templates'
import { SketchCanvas } from './SketchCanvas'

type Props = {
  strokes: Stroke[]
  prompt: string
  onStrokes: (s: Stroke[]) => void
  onPrompt: (p: string) => void
  onGenerate: () => void
  projectName: string
  onRename: (name: string) => void
}

const WIDTHS = [3, 6, 11]

export function SketchStage({ strokes, prompt, onStrokes, onPrompt, onGenerate, projectName, onRename }: Props) {
  const [tool, setTool] = useState<'pen' | 'eraser'>('pen')
  const [width, setWidth] = useState(6)
  const [redo, setRedo] = useState<Stroke[]>([])

  const commit = (s: Stroke) => {
    onStrokes([...strokes, s])
    setRedo([])
  }
  const undo = () => {
    if (!strokes.length) return
    setRedo((r) => [strokes[strokes.length - 1], ...r])
    onStrokes(strokes.slice(0, -1))
  }
  const redoFn = () => {
    if (!redo.length) return
    onStrokes([...strokes, redo[0]])
    setRedo((r) => r.slice(1))
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || (e.target as HTMLElement).tagName === 'INPUT') return
      if (e.key.toLowerCase() === 'z') {
        e.preventDefault()
        e.shiftKey ? redoFn() : undo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const empty = strokes.filter((s) => !s.erase).length === 0
  const canGenerate = !empty || prompt.trim().length > 0

  return (
    <div className="flex h-full flex-col gap-4 p-4 lg:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="label">Sketch board</span>
          <input
            value={projectName}
            onChange={(e) => onRename(e.target.value)}
            className="mt-1 block w-full max-w-xs rounded-md bg-transparent text-xl font-semibold tracking-tight outline-none focus:bg-raised"
            aria-label="Project name"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(TEMPLATES).map(([k, t]) => (
            <button
              key={k}
              className="rounded-full border border-line px-3 py-1.5 text-xs text-muted transition-colors hover:border-pink/60 hover:text-pink-soft active:scale-95"
              onClick={() => {
                onStrokes(t.strokes)
                setRedo([])
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      {/* Board */}
      <div className="relative grid min-h-[260px] flex-1 place-items-center" style={{ containerType: 'size' }}>
        <div className="panel dot-grid relative aspect-[4/3] overflow-hidden" style={{ width: 'min(100cqw, 100cqh * 4 / 3)' }}>
          <SketchCanvas strokes={strokes} onCommit={commit} tool={tool} width={width} />

          <AnimatePresence>
            {empty && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: 0.15 } }}
                className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-center"
              >
                <PenLine className="text-pink/60" />
                <p className="text-sm text-muted">Draw something buildable</p>
                <p className="text-xs text-muted/60">A house, a bridge, a tower. Simple outlines work best.</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Toolbar */}
          <div className="absolute left-3 top-3 flex flex-col gap-1 rounded-xl border border-line bg-ink/80 p-1 backdrop-blur">
            <ToolBtn active={tool === 'pen'} onClick={() => setTool('pen')} label="Pen">
              <PenLine size={16} />
            </ToolBtn>
            <ToolBtn active={tool === 'eraser'} onClick={() => setTool('eraser')} label="Eraser">
              <Eraser size={16} />
            </ToolBtn>
            <div className="mx-auto my-1 h-px w-5 bg-line" />
            {WIDTHS.map((w) => (
              <ToolBtn key={w} active={width === w} onClick={() => setWidth(w)} label={`Stroke ${w}`}>
                <span className="rounded-full bg-current" style={{ width: w + 2, height: w + 2 }} />
              </ToolBtn>
            ))}
            <div className="mx-auto my-1 h-px w-5 bg-line" />
            <ToolBtn onClick={undo} label="Undo (Ctrl+Z)" disabled={!strokes.length}>
              <Undo2 size={16} />
            </ToolBtn>
            <ToolBtn onClick={redoFn} label="Redo (Ctrl+Shift+Z)" disabled={!redo.length}>
              <Redo2 size={16} />
            </ToolBtn>
            <ToolBtn
              onClick={() => {
                onStrokes([])
                setRedo([])
              }}
              label="Clear"
              disabled={!strokes.length}
            >
              <Trash2 size={16} />
            </ToolBtn>
          </div>
        </div>
      </div>

      {/* Prompt + Generate */}
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Wand2 size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
          <input
            className="input pl-10"
            placeholder="Optional: describe it (e.g. ‘a red house with a tall roof’)"
            value={prompt}
            onChange={(e) => onPrompt(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && canGenerate && onGenerate()}
          />
        </div>
        <button className="btn-pink px-6" disabled={!canGenerate} onClick={onGenerate}>
          <Sparkles size={16} />
          Generate builds
        </button>
      </div>
    </div>
  )
}

function ToolBtn({
  children,
  active,
  label,
  ...rest
}: { children: React.ReactNode; active?: boolean; label: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors active:scale-95 disabled:opacity-30 ${
        active ? 'bg-pink text-black' : 'text-muted hover:bg-raised hover:text-fg'
      }`}
    >
      {children}
    </button>
  )
}
