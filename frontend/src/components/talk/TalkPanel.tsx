import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Keyboard, Mic, MicOff, Send, X } from 'lucide-react'
import { VOICE_SCRIPT, type ChatMsg } from '../../mocks/chat'
import { useBackend } from '../../backend'
import type { Build } from '../../types'
import { uid } from '../../store/storage'

type Props = {
  open: boolean
  onOpenChange: (o: boolean) => void
  /** Sends a request to the backend; resolves to the agent's reply ('' if a newer request replaced it). */
  onSubmit: (text: string) => Promise<string>
  /** The build on screen (choose stage), so chips can offer edits that apply to it. */
  build: Build | null
}

export function TalkPanel({ open, onOpenChange, onSubmit, build }: Props) {
  const { online, info } = useBackend()
  const [mode, setMode] = useState<'voice' | 'chat'>('voice')
  const [msgs, setMsgs] = useState<ChatMsg[]>([
    { id: 'hi', from: 'agent', text: 'Hi! Describe what to build ("a plank and a roof on top") and I will put it on the Choose screen. I never start the arm myself.' },
  ])
  const [typing, setTyping] = useState(false)

  const send = async (text: string) => {
    if (!text.trim()) return
    setMsgs((m) => [...m, { id: uid(), from: 'user', text }])
    setTyping(true)
    const reply = await onSubmit(text)
    setTyping(false)
    if (reply) setMsgs((m) => [...m, { id: uid(), from: 'agent', text: reply }])
  }

  // Only offer edits the catalog supports for the build on screen.
  const chips = (() => {
    if (!build) return ['A plank and a roof on top', 'Two cubes with a roof on top', 'Make a house']
    const out = ['Make it taller', 'Use fewer blocks']
    const inv = info?.inventory ?? {}
    for (const have of new Set(build.blocks.map((b) => b.color as string))) {
      const types = build.blocks.filter((b) => b.color === have).map((b) => b.type ?? '')
      const all = new Set(Object.values(inv).flatMap((i) => Object.keys(i.colors)))
      const target = [...all].find((c) => c !== have && types.every((t) => (inv[t]?.colors[c] ?? 0) > 0))
      if (target) {
        out.push(`Swap ${have} for ${target}`)
        break
      }
    }
    return [...out, 'Why this build?']
  })()

  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onOpenChange(false)
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open, onOpenChange])

  return (
    <>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label="Talk to the agent"
            initial={{ opacity: 0, scale: 0.9, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8, transition: { duration: 0.15 } }}
            transition={{ type: 'spring', duration: 0.4, bounce: 0.15 }}
            style={{ transformOrigin: 'bottom right' }}
            className="fixed bottom-24 right-4 z-50 flex h-[min(560px,calc(100dvh-8rem))] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_24px_80px_rgba(0,0,0,0.6)] md:right-6"
          >
            <header className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <div className="text-sm font-semibold">Build agent</div>
                <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{online ? 'connected to the arm server' : 'server offline'}</div>
              </div>
              <div className="flex items-center gap-1">
                <div className="flex rounded-lg border border-line p-0.5 text-xs">
                  {(['voice', 'chat'] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode(m)}
                      className={`relative flex items-center gap-1.5 rounded-md px-2.5 py-1 capitalize transition-colors ${mode === m ? 'text-black' : 'text-muted hover:text-fg'}`}
                    >
                      {mode === m && <motion.span layoutId="talk-tab" className="absolute inset-0 rounded-md bg-pink" transition={{ type: 'spring', duration: 0.3, bounce: 0.15 }} />}
                      <span className="relative flex items-center gap-1.5">
                        {m === 'voice' ? <Mic size={12} /> : <Keyboard size={12} />}
                        {m}
                      </span>
                    </button>
                  ))}
                </div>
                <button className="icon-btn" onClick={() => onOpenChange(false)} aria-label="Close">
                  <X size={16} />
                </button>
              </div>
            </header>

            {mode === 'voice' ? <Voice onTranscript={(heard, reply) => setMsgs((m) => [...m, { id: uid(), from: 'user', text: heard }, { id: uid(), from: 'agent', text: reply }])} /> : <Chat msgs={msgs} typing={typing} chips={chips} onSend={send} />}
          </motion.div>
        )}
      </AnimatePresence>

      <MicOrb open={open} onClick={() => onOpenChange(!open)} />
    </>
  )
}

function MicOrb({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <motion.button
      onClick={onClick}
      aria-label={open ? 'Close agent' : 'Talk to agent'}
      whileTap={{ scale: 0.92 }}
      className="fixed bottom-20 right-4 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-pink text-black shadow-glow-lg md:bottom-6 md:right-6"
    >
      {!open && <span className="absolute inset-0 animate-ping rounded-full bg-pink opacity-25 [animation-duration:2.4s]" />}
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={open ? 'x' : 'mic'}
          initial={{ rotate: -90, opacity: 0, scale: 0.5 }}
          animate={{ rotate: 0, opacity: 1, scale: 1 }}
          exit={{ rotate: 90, opacity: 0, scale: 0.5 }}
          transition={{ duration: 0.15 }}
        >
          {open ? <X size={22} /> : <Mic size={22} />}
        </motion.span>
      </AnimatePresence>
    </motion.button>
  )
}

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking'

function Voice({ onTranscript }: { onTranscript: (heard: string, reply: string) => void }) {
  const [state, setState] = useState<VoiceState>('idle')
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  const start = () => {
    timers.current.forEach(clearTimeout)
    setHeard('')
    setReply('')
    setState('listening')
    const words = VOICE_SCRIPT.heard.split(' ')
    words.forEach((_, i) => timers.current.push(setTimeout(() => setHeard(words.slice(0, i + 1).join(' ')), 300 + i * 180)))
    const t1 = 300 + words.length * 180 + 400
    timers.current.push(setTimeout(() => setState('thinking'), t1))
    timers.current.push(
      setTimeout(() => {
        setState('speaking')
        setReply(VOICE_SCRIPT.reply)
        onTranscript(VOICE_SCRIPT.heard, VOICE_SCRIPT.reply)
      }, t1 + 1100),
    )
    timers.current.push(setTimeout(() => setState('idle'), t1 + 3600))
  }

  const stop = () => {
    timers.current.forEach(clearTimeout)
    setState('idle')
  }

  const active = state !== 'idle'
  const label = { idle: 'Tap to talk', listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking' }[state]

  return (
    <div className="flex flex-1 flex-col items-center justify-between gap-4 p-6">
      <div className="flex w-full flex-1 flex-col items-center justify-center gap-6">
        <div className="relative flex h-40 w-40 items-center justify-center">
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className="absolute inset-0 rounded-full border border-pink/40"
              animate={active ? { scale: [1, 1.5 + i * 0.15], opacity: [0.5, 0] } : { scale: 1, opacity: 0.15 }}
              transition={active ? { duration: 2, repeat: Infinity, delay: i * 0.6, ease: 'easeOut' } : { duration: 0.3 }}
            />
          ))}
          <motion.button
            onClick={active ? stop : start}
            whileTap={{ scale: 0.94 }}
            animate={{ scale: state === 'listening' ? [1, 1.06, 1] : 1 }}
            transition={state === 'listening' ? { duration: 1.2, repeat: Infinity } : { duration: 0.2 }}
            className="relative flex h-28 w-28 items-center justify-center rounded-full bg-[radial-gradient(circle_at_35%_30%,#ff8cc6,#ff2e93_55%,#a3105a)] text-black shadow-glow-lg"
            aria-label={active ? 'Stop' : 'Start talking'}
          >
            {active ? <MicOff size={30} /> : <Mic size={30} />}
          </motion.button>
        </div>

        <Waveform active={state === 'listening' || state === 'speaking'} />
        <span className="label">{label}</span>
      </div>

      <div className="w-full space-y-2 text-sm">
        <AnimatePresence>
          {heard && (
            <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="text-fg">
              <span className="label mr-2">You</span>
              {heard}
            </motion.p>
          )}
          {reply && (
            <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="text-pink-soft">
              <span className="label mr-2">Agent</span>
              {reply}
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex h-10 items-center gap-1" aria-hidden>
      {Array.from({ length: 24 }, (_, i) => (
        <motion.span
          key={i}
          className="w-1 rounded-full bg-pink"
          animate={active ? { height: [4, 8 + ((i * 37) % 28), 6, 4 + ((i * 53) % 32), 4] } : { height: 4 }}
          transition={active ? { duration: 0.9 + (i % 5) * 0.12, repeat: Infinity, ease: 'easeInOut', delay: (i % 7) * 0.05 } : { duration: 0.3 }}
          style={{ opacity: 0.5 + ((i * 13) % 50) / 100 }}
        />
      ))}
    </div>
  )
}

function Chat({ msgs, typing, chips, onSend }: { msgs: ChatMsg[]; typing: boolean; chips: string[]; onSend: (t: string) => void }) {
  const [text, setText] = useState('')
  const list = useRef<HTMLDivElement>(null)
  // Scroll only the message list. scrollIntoView also scrolls overflow:hidden ancestors
  // and shoved the whole app out of view (black screen) when a chip was clicked.
  useEffect(() => {
    const el = list.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [msgs, typing])

  return (
    <>
      <div ref={list} className="flex-1 space-y-2 overflow-y-auto p-4">
        {msgs.map((m) => (
          <motion.div
            key={m.id}
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: 'spring', duration: 0.3, bounce: 0 }}
            className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${m.from === 'user' ? 'ml-auto rounded-br-sm bg-pink text-black' : 'rounded-bl-sm bg-raised'}`}
          >
            {m.text}
          </motion.div>
        ))}
        {typing && (
          <div className="flex w-14 gap-1 rounded-2xl rounded-bl-sm bg-raised px-3.5 py-3">
            {[0, 1, 2].map((i) => (
              <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-muted" animate={{ y: [0, -3, 0] }} transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.12 }} />
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-1.5 overflow-x-auto px-4 pb-2">
        {chips.map((s) => (
          <button key={s} onClick={() => onSend(s)} className="shrink-0 rounded-full border border-line px-2.5 py-1 text-xs text-muted transition-colors hover:border-pink/60 hover:text-pink-soft">
            {s}
          </button>
        ))}
      </div>
      <form
        className="flex gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault()
          onSend(text)
          setText('')
        }}
      >
        <input className="input" placeholder="Ask the agent…" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn-pink px-3" aria-label="Send" disabled={!text.trim()}>
          <Send size={16} />
        </button>
      </form>
    </>
  )
}
