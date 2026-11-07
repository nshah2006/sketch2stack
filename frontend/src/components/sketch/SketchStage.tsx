import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Eraser, PenLine, Redo2, ShieldCheck, Sparkles, Trash2, Undo2, Wand2 } from 'lucide-react'
import { PromptInput } from '@/components/ui/ai-chat-input'
import { AgentOrb, VoiceBars, useVoiceLevels } from '@/components/voice/VoiceKit'
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

// UI only for now: the generator doesn't take style/detail yet.
const STYLES = ['Faithful', 'Creative', 'Sturdy']
const STYLE_ICONS = { Faithful: PenLine, Creative: Wand2, Sturdy: ShieldCheck }
const DETAIL = ['Few blocks', 'Balanced', 'Detailed']

export function SketchStage({ strokes, prompt, onStrokes, onPrompt, onGenerate, projectName, onRename }: Props) {
  const [tool, setTool] = useState<'pen' | 'eraser'>('pen')
  const [width, setWidth] = useState(6)
  const [redo, setRedo] = useState<Stroke[]>([])
  const [promptOpen, setPromptOpen] = useState(false)
  const [listening, setListening] = useState(false)
  const voice = useVoiceLevels()

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

          {/* Same agent look as the Talk pop-up: sphere + bars while you dictate */}
          <AnimatePresence>
            {listening && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: 0.2 } }}
                className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-ink/45 backdrop-blur-[2px]"
              >
                <motion.div
                  initial={{ scale: 0.85, y: 12 }}
                  animate={{ scale: 1, y: 0 }}
                  exit={{ scale: 0.92, y: 6 }}
                  transition={{ type: 'spring', duration: 0.45, bounce: 0.2 }}
                  className="flex flex-col items-center gap-2 rounded-3xl border border-pink/30 bg-surface/85 px-8 pb-5 pt-6 shadow-glow"
                >
                  <AgentOrb levelRef={voice.levelRef} kickRef={voice.kickRef} listening className="h-32 w-32" />
                  <span className="label !text-pink-soft">Listening… describe your build</span>
                  <VoiceBars bandsRef={voice.bandsRef} kickRef={voice.kickRef} active count={28} />
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>

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
              models={STYLES}
              modelIcons={STYLE_ICONS}
              efforts={DETAIL}
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
