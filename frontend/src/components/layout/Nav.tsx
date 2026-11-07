import { motion } from 'motion/react'
import { Blocks, FlaskConical, PenLine, Video, type LucideProps } from 'lucide-react'
import { AgentOrb } from '@/components/voice/VoiceKit'
import type { Stage } from '../../types'
import { Logo } from './Logo'
import { ProfileMenu } from './ProfileMenu'

export type NavTarget = 'sketch' | 'choose' | 'live' | 'talk' | 'labs'

type Props = {
  stage: Stage
  hasBuilds: boolean
  onNav: (t: NavTarget) => void
  /** Agent dock open: the agent item lights up. */
  talkOpen?: boolean
  /** The agent only exists while a build is running. */
  canTalk?: boolean
}

/** The agent's icon is the same wireframe sphere it shows in the pop-up. */
function AgentIcon({ size = 19, className }: LucideProps) {
  const px = Number(size) + 7 // the sphere reads small next to line icons
  return (
    <span className={className} style={{ width: px, height: px, margin: -3.5 }}>
      <AgentOrb glow={false} className="h-full w-full" />
    </span>
  )
}

const ITEMS = [
  { id: 'sketch', label: 'Draw', icon: PenLine },
  { id: 'choose', label: 'Builds', icon: Blocks },
  { id: 'live', label: 'Build live', icon: Video },
  { id: 'talk', label: 'Talk', icon: AgentIcon },
  { id: 'labs', label: 'Labs', icon: FlaskConical },
] as const

function isActive(stage: Stage, id: string, talkOpen = false) {
  if (id === 'talk') return talkOpen
  return stage === id || (stage === 'generating' && id === 'sketch')
}

export function LeftRail({ stage, hasBuilds, onNav, talkOpen, canTalk }: Props) {
  return (
    <nav className="hidden w-[76px] shrink-0 flex-col items-center gap-2 border-r border-line py-4 md:flex">
      <Logo compact />
      <div className="mt-6 flex flex-1 flex-col gap-1">
        {ITEMS.map((it) => {
          const active = isActive(stage, it.id, talkOpen)
          const disabled = (!hasBuilds && (it.id === 'choose' || it.id === 'live')) || (it.id === 'talk' && !canTalk)
          return (
            <button
              key={it.id}
              onClick={() => onNav(it.id)}
              disabled={disabled}
              className={`group relative flex w-14 flex-col items-center gap-1 rounded-xl py-2.5 text-[10px] transition-colors disabled:opacity-30 ${active ? 'text-pink' : 'text-muted hover:text-fg'}`}
            >
              {active && <motion.span layoutId="rail-active" className="absolute inset-0 rounded-xl bg-pink-dim" transition={{ type: 'spring', duration: 0.35, bounce: 0.15 }} />}
              <it.icon size={19} className="relative" />
              <span className="relative">{it.label}</span>
            </button>
          )
        })}
      </div>
      <ProfileMenu />
    </nav>
  )
}

export function BottomNav({ stage, hasBuilds, onNav, talkOpen, canTalk }: Props) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-ink/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      {ITEMS.map((it) => {
        const active = isActive(stage, it.id, talkOpen)
        const disabled = (!hasBuilds && (it.id === 'choose' || it.id === 'live')) || (it.id === 'talk' && !canTalk)
        return (
          <button
            key={it.id}
            onClick={() => onNav(it.id)}
            disabled={disabled}
            className={`flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] disabled:opacity-30 ${active ? 'text-pink' : 'text-muted'}`}
          >
            <it.icon size={19} />
            {it.label}
          </button>
        )
      })}
    </nav>
  )
}

const STEPS: { id: Stage; label: string }[] = [
  { id: 'sketch', label: 'Sketch' },
  { id: 'choose', label: 'Choose build' },
  { id: 'live', label: 'Build live' },
]

export function Stepper({ stage }: { stage: Stage }) {
  const idx = stage === 'generating' ? 0.5 : STEPS.findIndex((s) => s.id === stage)
  return (
    <ol className="flex items-center gap-2 text-xs">
      {STEPS.map((s, i) => {
        const done = i < idx
        const current = i === idx || (stage === 'generating' && i === 0)
        return (
          <li key={s.id} className="flex items-center gap-2">
            <span className={`flex items-center gap-2 ${current ? 'text-fg' : done ? 'text-pink-soft' : 'text-muted'}`}>
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full border font-mono text-[10px] transition-colors ${
                  current ? 'border-pink bg-pink text-black' : done ? 'border-pink text-pink' : 'border-line'
                }`}
              >
                {i + 1}
              </span>
              <span className="hidden sm:inline">{s.label}</span>
            </span>
            {i < STEPS.length - 1 && (
              <span className="relative h-px w-6 overflow-hidden bg-line sm:w-10">
                <motion.span className="absolute inset-0 origin-left bg-pink" initial={false} animate={{ scaleX: idx > i ? Math.min(idx - i, 1) : 0 }} transition={{ duration: 0.5 }} />
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
