import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, Mic } from 'lucide-react'
import { PromptInput } from '@/components/ui/ai-chat-input'
import { AgentOrb, VoiceBars, type VoiceLevels } from '@/components/voice/VoiceKit'
import { uid } from '../../store/storage'

/** What the agent can see and do during a build. */
export type ArmAgent = {
  phase: 'running' | 'paused' | 'safety' | 'halted' | 'failed' | 'done'
  live: boolean
  sim: boolean
  done: number
  total: number
  current?: string
  pause: () => Promise<unknown>
  resume: () => Promise<unknown>
  stop: () => Promise<unknown>
  poke: () => Promise<unknown>
  again: () => void
}

type Msg = { id: string; from: 'user' | 'agent'; text: string }

/** Turns what you said into an arm action. Keyword rules for now; an LLM can replace `interpret`. */
function interpret(text: string, a: ArmAgent): { reply: string; run?: () => unknown } {
  const t = text.toLowerCase()
  const has = (re: RegExp) => re.test(t)
  if (has(/\b(stop|halt|emergency|freeze|e-?stop)\b/))
    return a.live ? { reply: 'Stopping the arm now. All servos holding.', run: a.stop } : { reply: "Nothing's moving, so there's nothing to stop." }
  if (has(/\b(again|restart|rebuild|redo|one more)\b/)) return { reply: 'Starting the build again from the first block.', run: a.again }
  if (has(/\b(pause|hold on|hold|wait|one sec)\b/))
    return a.phase === 'running' ? { reply: 'Pausing after this move.', run: a.pause } : { reply: `It's not running right now (${a.phase}).` }
  if (has(/\b(resume|continue|go on|keep going|unpause|carry on|go ahead)\b/))
    return a.phase === 'paused' ? { reply: 'Resuming.', run: a.resume } : { reply: a.phase === 'running' ? "It's already going." : `Can't resume from ${a.phase}. Try "build again".` }
  if (has(/\b(reach|poke|test safety|hand in)\b/))
    return a.sim ? { reply: 'Simulating a hand near the arm. Watch it freeze, then carry on.', run: a.poke } : { reply: 'That test only exists in the simulator.' }
  if (has(/\b(status|where|progress|how far|what step|which step|doing|left)\b/))
    return {
      reply:
        a.phase === 'done'
          ? `Done: all ${a.total} blocks placed.`
          : `${a.done} of ${a.total} blocks placed${a.current ? `. Now: ${a.current.toLowerCase()}` : ''}.`,
    }
  if (has(/\b(faster|slower|speed)\b/)) return { reply: 'Speed is set when the robot server starts (--speed). Live speed control is not wired yet.' }
  if (has(/\b(skip|swap|change|color|colour|taller|bigger|move)\b/))
    return { reply: "Changing the build mid-run isn't supported yet. Stop it, edit the build, then build again." }
  return { reply: 'I can pause, resume, stop, give you the status, run the reach-in test, or build again. Try "how far along are we?"' }
}

const CHIPS = ['How far along?', 'Pause', 'Resume', 'Reach in (sim)', 'Build again']

type DockProps = {
  open: boolean
  onOpenChange: (o: boolean) => void
  agent: ArmAgent
  /** Shared with the listening card the page shows beside the camera. */
  voice: VoiceLevels
  onListeningChange?: (listening: boolean) => void
  className?: string
}

/** The one Talk in the build phase: a bottom dock with the moving agent orb, chat, chips and voice. */
export function AgentDock({ open, onOpenChange, agent, voice, onListeningChange, className }: DockProps) {
  const [recording, setRecording] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [text, setText] = useState('')
  const [pendingVoice, setPendingVoice] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([{ id: 'hi', from: 'agent', text: 'Talk or type to steer the build. Try “pause” or “how far along?”' }])
  const agentRef = useRef(agent)
  agentRef.current = agent
  const textRef = useRef(text)
  textRef.current = text
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' }), [msgs, thinking])

  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onOpenChange(false)
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open, onOpenChange])

  const send = (raw: string) => {
    const said = raw.trim()
    if (!said) return
    setText('')
    setMsgs((m) => [...m.slice(-30), { id: uid(), from: 'user', text: said }])
    setThinking(true)
    setTimeout(async () => {
      const { reply, run } = interpret(said, agentRef.current)
      setThinking(false)
      setMsgs((m) => [...m, { id: uid(), from: 'agent', text: reply }])
      try {
        await run?.()
      } catch (e) {
        setMsgs((m) => [...m, { id: uid(), from: 'agent', text: `That didn't work: ${(e as Error).message}` }])
      }
    }, 450)
  }

  // Hands-free: when you stop talking, what you said is sent.
  const onRecordingChange = (r: boolean) => {
    setRecording(r)
    onListeningChange?.(r)
    if (r) setPendingVoice(false)
    if (!r && textRef.current.trim()) send(textRef.current)
  }

  const status = recording ? 'Listening…' : thinking ? 'Working on it…' : agent.live ? `${agent.done}/${agent.total} placed · ${agent.phase}` : 'Build ' + agent.phase

  return (
    <div className={`flex justify-center ${className ?? ''}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        {!open ? (
          <motion.div
            key="pill"
            layoutId="arm-agent"
            style={{ borderRadius: 999 }}
            transition={{ type: 'spring', duration: 0.5, bounce: 0.15 }}
            className="flex items-center gap-1 border border-pink/40 bg-surface p-1 pr-1.5 shadow-glow"
          >
            <button onClick={() => onOpenChange(true)} className="flex items-center gap-2.5 rounded-full py-1 pl-1 pr-3 text-sm transition-colors hover:bg-pink-dim">
              <AgentOrb levelRef={voice.levelRef} kickRef={voice.kickRef} glow={false} className="h-9 w-9" />
              <span className="font-medium">Talk to the arm</span>
            </button>
            <button
              onClick={() => {
                setPendingVoice(true)
                onOpenChange(true)
              }}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-pink/50 bg-ink text-pink transition-colors hover:border-pink hover:bg-pink-dim"
              aria-label="Talk to the arm with your voice"
            >
              <Mic size={15} />
            </button>
          </motion.div>
        ) : (
          <motion.div
            key="window"
            layoutId="arm-agent"
            role="dialog"
            aria-label="Arm agent"
            style={{ borderRadius: 24 }}
            transition={{ type: 'spring', duration: 0.5, bounce: 0.15 }}
            className="w-full overflow-hidden border border-line bg-surface shadow-[0_0_32px_rgba(255,46,147,0.08)]"
          >
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { delay: 0.12 } }}>
              <div className="flex items-center justify-between px-4 pt-3">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-semibold">Arm agent</span>
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                      key={status}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.15 }}
                      className={`label ${recording ? '!text-pink-soft' : ''}`}
                    >
                      {status}
                    </motion.span>
                  </AnimatePresence>
                </div>
                <button className="icon-btn h-8 w-8" onClick={() => onOpenChange(false)} aria-label="Minimize agent">
                  <ChevronDown size={16} />
                </button>
              </div>

              <div className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-3 px-4 pt-2 sm:grid-cols-[112px_minmax(0,1fr)]">
                <div className="flex flex-col items-center gap-1">
                  <AgentOrb levelRef={voice.levelRef} kickRef={voice.kickRef} listening={recording} busy={thinking} className="aspect-square w-full" />
                  <VoiceBars bandsRef={voice.bandsRef} kickRef={voice.kickRef} active={recording} count={14} className="h-6" />
                </div>
                <div ref={logRef} className="h-28 space-y-1.5 overflow-y-auto pr-1 text-sm">
                  {msgs.map((m) => (
                    <motion.p
                      key={m.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ type: 'spring', duration: 0.3, bounce: 0 }}
                      className={m.from === 'user' ? 'text-fg' : 'text-pink-soft'}
                    >
                      <span className="label mr-2 !text-[10px]">{m.from === 'user' ? 'You' : 'Arm'}</span>
                      {m.text}
                    </motion.p>
                  ))}
                  {thinking && (
                    <div className="flex gap-1 py-1">
                      {[0, 1, 2].map((i) => (
                        <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-pink" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.15 }} />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex gap-1.5 overflow-x-auto px-4 pb-2 pt-1">
                {CHIPS.filter((c) => agent.sim || !c.includes('sim')).map((c) => (
                  <button
                    key={c}
                    onClick={() => send(c.replace(' (sim)', ''))}
                    className="shrink-0 rounded-full border border-line px-2.5 py-1 text-xs text-muted transition-colors hover:border-pink/60 hover:text-pink-soft active:scale-95"
                  >
                    {c}
                  </button>
                ))}
              </div>

              <div className="px-3 pb-3">
                <PromptInput
                  value={text}
                  onChange={setText}
                  onSubmit={(v) => send(v)}
                  placeholder="Tell the arm what to do, or tap the mic"
                  allowAttachments={false}
                  collapsedWidth="100%"
                  expandedWidth="100%"
                  showLevels={false}
                  onRecordingChange={onRecordingChange}
                  onLevels={voice.onLevels}
                  onWord={voice.onWord}
                  startVoiceSignal={pendingVoice ? 1 : 0}
                  simulatedTranscript="How far along are we"
                />
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
