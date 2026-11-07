import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowRight, Eye, EyeOff, Loader2, Lock, ShieldCheck } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { SketchTo3D } from '../components/anim/SketchTo3D'
import { Logo } from '../components/layout/Logo'

export function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const { user, login, signup } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  if (user) return <Navigate to="/app" replace />

  const isSignup = mode === 'signup'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    if (!/^\S+@\S+\.\S+$/.test(email)) return setErr('Enter a valid email.')
    if (pw.length < 6) return setErr('Password needs at least 6 characters.')
    if (isSignup && !name.trim()) return setErr('Tell us your name.')
    setBusy(true)
    try {
      if (isSignup) await signup(name, email, pw)
      else await login(email, pw)
      const from = (loc.state as { from?: string } | null)?.from
      nav(from ?? '/app', { replace: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.15fr_1fr]">
      {/* Hero */}
      <div className="relative flex flex-col justify-between overflow-hidden border-b border-line p-6 lg:border-b-0 lg:border-r lg:p-10">
        <div className="absolute -left-40 -top-40 h-[520px] w-[520px] rounded-full bg-pink/10 blur-3xl" />
        <Logo />
        <SketchTo3D loop className="relative mx-auto my-6 aspect-[4/3] w-full max-w-xl" />
        <div className="relative max-w-md">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight lg:text-4xl">
            Draw it flat. <span className="text-pink">Watch it stand up.</span>
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Sketch on a 2D board, pick from block-built interpretations, and let the arm stack it for real.
          </p>
        </div>
      </div>

      {/* Form */}
      <div className="flex items-center justify-center p-6 lg:p-10">
        <motion.form
          key={mode}
          onSubmit={submit}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: 'spring', duration: 0.45, bounce: 0 }}
          className="w-full max-w-sm"
          noValidate
        >
          <span className="label">{isSignup ? 'Create account' : 'Welcome back'}</span>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">
            {isSignup ? 'Start your first build' : 'Sign in to your projects'}
          </h2>

          <div className="mt-8 space-y-4">
            {isSignup && (
              <Field label="Name">
                <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" autoComplete="name" />
              </Field>
            )}
            <Field label="Email">
              <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@school.edu" autoComplete="email" />
            </Field>
            <Field label="Password">
              <div className="relative">
                <input
                  className="input pr-10"
                  type={show ? 'text' : 'password'}
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  placeholder="••••••••"
                  autoComplete={isSignup ? 'new-password' : 'current-password'}
                />
                <button type="button" onClick={() => setShow((s) => !s)} className="icon-btn absolute right-0.5 top-0.5" aria-label={show ? 'Hide password' : 'Show password'}>
                  {show ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </Field>
          </div>

          {err && (
            <motion.p initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} className="mt-3 text-sm text-pink-soft" role="alert">
              {err}
            </motion.p>
          )}

          <button className="btn-pink mt-6 w-full py-3" disabled={busy}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : null}
            {isSignup ? 'Create account' : 'Sign in'}
            {!busy && <ArrowRight size={16} />}
          </button>

          <p className="mt-5 text-center text-sm text-muted">
            {isSignup ? 'Already have an account? ' : 'New here? '}
            <Link to={isSignup ? '/login' : '/signup'} className="text-pink hover:underline">
              {isSignup ? 'Sign in' : 'Create one'}
            </Link>
          </p>

          <div className="mt-8 flex items-start gap-3 rounded-xl border border-line bg-surface p-3 text-xs text-muted">
            <ShieldCheck size={16} className="mt-0.5 shrink-0 text-pink" />
            <span>
              Your sketches and builds are private to your account. <Lock size={10} className="inline" /> Demo mode: any email and password works.
            </span>
          </div>
        </motion.form>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>
      {children}
    </label>
  )
}
