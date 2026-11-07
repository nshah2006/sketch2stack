import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Eraser, Maximize2, PenLine, Redo2, Sparkles, Trash2, Undo2 } from 'lucide-react'
import { PromptInput } from '@/components/ui/ai-chat-input'
import { AgentOrb, VoiceBars, useVoiceLevels } from '@/components/voice/VoiceKit'
import type { Stroke } from '../../types'
import { TEMPLATES } from '../../mocks/templates'
import { useBackend } from '../../backend'
import { SketchCanvas } from './SketchCanvas'
import { Ruler } from './Ruler'

type Props = {
  strokes: Stroke[]
  prompt: string
  onStrokes: (s: Stroke[]) => void
  onPrompt: (p: string) => void
  onGenerate: () => void
  projectName: string
  onRename: (name: string) => void
  /** Scale the drawing up to fill the build strip instead of reading the board 1:1. */
  fitStrip: boolean
  onFitStrip: (v: boolean) => void
}

const WIDTHS = [3, 6, 11]

/** Bounding box of what was drawn, in cm. Mirrors webapi._fit so the readout
 *  matches what the planner will actually build. */
function drawnSize(strokes: Stroke[], widthCm: number, heightCm: number, fitStrip: boolean) {
  const pts = strokes.filter((s) => !s.erase).flatMap((s) => s.points)
  if (!pts.length) return null
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  let w = (Math.max(...xs) - Math.min(...xs)) * widthCm
  let h = (Math.max(...ys) - Math.min(...ys)) * heightCm
  if (fitStrip && w > 0 && h > 0) {
    const s = Math.min(widthCm / w, heightCm / h)
    w *= s
    h *= s
  }
  return { w, h }
}

export function SketchStage({
  strokes,
  prompt,
  onStrokes,
  onPrompt,
  onGenerate,
  projectName,
  onRename,
  fitStrip,
  onFitStrip,
}: Props) {
  const [tool, setTool] = useState<'pen' | 'eraser'>('pen')
  const [width, setWidth] = useState(6)
  const [redo, setRedo] = useState<Stroke[]>([])
  const [promptOpen, setPromptOpen] = useState(false)
  const [listening, setListening] = useState(false)
  const voice = useVoiceLevels()
  const sideW = typeof window !== 'undefined' && window.innerWidth < 640 ? 132 : 220

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
      const tag = (e.target as HTMLElement).tagName
      if (!(e.metaKey || e.ctrlKey) || tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key.toLowerCase() === 'z') {
        e.preventDefault()
        e.shiftKey ? redoFn() : undo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // The board is the build strip 1:1, so its aspect has to be the strip's.
  const { info } = useBackend()
  const widthCm = info?.grid.width ?? 20
  const heightCm = info?.grid.max_height ?? 12
  const aspect = widthCm / heightCm

  const empty = strokes.filter((s) => !s.erase).length === 0
  const canGenerate = !empty || prompt.trim().length > 0
  const size = drawnSize(strokes, widthCm, heightCm, fitStrip)

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
      <div className="flex min-h-[260px] flex-1">
      <div className="relative grid min-w-0 flex-1 place-items-center" style={{ containerType: 'size' }}>
        <div
          className="panel dot-grid relative overflow-hidden"
          style={{ aspectRatio: `${widthCm} / ${heightCm}`, width: `min(100cqw, 100cqh * ${aspect})` }}
        >
          <SketchCanvas strokes={strokes} onCommit={commit} tool={tool} width={width} />
          <Ruler widthCm={widthCm} heightCm={heightCm} muted={fitStrip} />

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

          {/* Size readout + scale mode */}
          <div className="absolute right-3 top-3 flex items-center gap-2">
            <span
              className="rounded-full border border-line bg-ink/80 px-2.5 py-1 font-mono text-[11px] text-muted backdrop-blur"
              title={fitStrip ? 'Size after scaling up to fill the strip' : 'Real size of your sketch'}
            >
              {size ? `${size.w.toFixed(1)} x ${size.h.toFixed(1)} cm` : `board ${widthCm} x ${heightCm} cm`}
            </span>
            <button
              onClick={() => onFitStrip(!fitStrip)}
              aria-pressed={fitStrip}
              title={
                fitStrip
                  ? 'Fit to strip: the sketch is scaled up to fill the build strip, so only its shape matters'
                  : 'True size: the board is the build strip 1:1, so what you draw is what gets built'
              }
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors active:scale-95 ${
                fitStrip
                  ? 'border-pink/60 bg-pink/15 text-pink-soft'
                  : 'border-line bg-ink/80 text-muted backdrop-blur hover:border-pink/40 hover:text-pink-soft'
              }`}
            >
              <Maximize2 size={12} />
              Fit to strip
            </button>
          </div>

          {/* Toolbar */}
          <div className="absolute left-7 top-3 flex flex-col gap-1 rounded-xl border border-line bg-ink/80 p-1 backdrop-blur">
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

        {/* The agent appears to the RIGHT of the board while you dictate, never on top of it */}
        <AnimatePresence initial={false}>
          {listening && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: sideW + 40, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ type: 'spring', duration: 0.5, bounce: 0.1 }}
              className="flex shrink-0 items-center overflow-hidden"
              aria-live="polite"
            >
              {/* ml = gap to the board, mr = buffer from the screen edge when Projects is closed */}
              <div className="ml-4 mr-6 flex flex-col items-center justify-center gap-3 rounded-2xl border border-pink/30 bg-surface px-4 py-6 shadow-glow" style={{ width: sideW }}>
                <AgentOrb levelRef={voice.levelRef} kickRef={voice.kickRef} listening className="aspect-square w-full max-w-[160px]" />
                <span className="label text-center !text-pink-soft">Listening…</span>
                <p className="text-center text-xs text-muted">Describe your build. Tap the orb button to stop.</p>
                <VoiceBars bandsRef={voice.bandsRef} kickRef={voice.kickRef} active count={sideW > 160 ? 24 : 14} />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Describe (text or voice) + Generate */}
      <div className="flex items-end justify-center gap-2">
        {/* Slot grows with the input so input + Generate stay centered as one group */}
        <div
          className="relative h-12 min-w-0"
          style={{
            width: `min(100%, ${promptOpen ? 680 : 440}px)`,
            flex: '0 1 auto',
            transition: 'width 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
          }}
        >
          <div className="absolute inset-x-0 bottom-0 z-20 flex justify-center">
            <PromptInput
              onExpandedChange={setPromptOpen}
              onRecordingChange={setListening}
              onLevels={voice.onLevels}
              onWord={voice.onWord}
              showLevels={false}
              value={prompt}
              onChange={onPrompt}
              onSubmit={() => canGenerate && onGenerate()}
              clearOnSubmit={false}
              placeholder="Describe it, or tap the mic and say it"
              allowAttachments={false}
              collapsedWidth={440}
              expandedWidth={680}
            />
          </div>
        </div>
        <button className="btn-pink h-12 shrink-0 rounded-full px-5 sm:px-6" disabled={!canGenerate} onClick={onGenerate}>
          <Sparkles size={16} />
          <span className="hidden sm:inline">Generate builds</span>
          <span className="sm:hidden">Generate</span>
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
