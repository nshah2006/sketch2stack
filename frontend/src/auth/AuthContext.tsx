import { createContext, useContext, useState, type ReactNode } from 'react'
import type { User } from '../types'
import { load, save } from '../store/storage'

const KEY = 's2s.session'

type AuthValue = {
  user: User | null
  login: (email: string, password: string) => Promise<void>
  signup: (name: string, email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthCtx = createContext<AuthValue | null>(null)

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

// MOCK: any credentials pass. Replace with real auth (Cognito/Supabase/etc).
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => load<User | null>(KEY, null))

  const set = (u: User | null) => {
    setUser(u)
    save(KEY, u)
  }

  const value: AuthValue = {
    user,
    async login(email) {
      await delay(700)
      const name = email.split('@')[0].replace(/[._-]/g, ' ')
      set({ name: name.replace(/\b\w/g, (c) => c.toUpperCase()) || 'Builder', email })
    },
    async signup(name, email) {
      await delay(900)
      set({ name: name.trim() || 'Builder', email })
    },
    logout() {
      set(null)
    },
  }

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}
