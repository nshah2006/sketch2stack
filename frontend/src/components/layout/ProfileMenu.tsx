import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { LogOut, Settings, ShieldCheck } from 'lucide-react'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../Toast'

export function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-pink to-[#7a0f45] font-semibold text-black"
      style={{ width: size, height: size, fontSize: size * 0.36 }}
    >
      {initials || '?'}
    </span>
  )
}

export function ProfileMenu({ placement = 'right' }: { placement?: 'right' | 'below' }) {
  const { user, logout } = useAuth()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  if (!user) return null
  const pos = placement === 'right' ? 'bottom-0 left-full ml-3 origin-bottom-left' : 'right-0 top-full mt-2 origin-top-right'

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-label="Account" className="rounded-full ring-pink/50 transition hover:ring-2">
        <Avatar name={user.name} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.1 } }}
            transition={{ type: 'spring', duration: 0.25, bounce: 0 }}
            className={`absolute z-50 w-64 rounded-xl border border-line bg-raised p-1.5 shadow-2xl ${pos}`}
          >
            <div className="flex items-center gap-3 p-2.5">
              <Avatar name={user.name} size={40} />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{user.name}</div>
                <div className="truncate text-xs text-muted">{user.email}</div>
              </div>
            </div>
            <div className="mx-2 mb-1 flex items-center gap-2 rounded-lg bg-pink-dim px-2.5 py-1.5 text-[11px] text-pink-soft">
              <ShieldCheck size={13} /> Projects private to you
            </div>
            <button onClick={() => toast('Settings coming soon')} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted hover:bg-surface hover:text-fg">
              <Settings size={15} /> Account settings
            </button>
            <button onClick={logout} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted hover:bg-surface hover:text-pink">
              <LogOut size={15} /> Sign out
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
