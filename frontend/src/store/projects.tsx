import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Project } from '../types'
import { TEMPLATES } from '../mocks/templates'
import { BUILDS } from '../mocks/builds'
import { load, save, uid } from './storage'

const KEY = 's2s.projects'
const DAY = 86_400_000
const now = Date.now()

const SEED: Project[] = [
  {
    id: 'seed-house',
    name: 'Backyard house',
    createdAt: now - 2 * DAY,
    updatedAt: now - 2 * DAY,
    status: 'built',
    strokes: TEMPLATES.house.strokes,
    prompt: '',
    buildIds: BUILDS.map((b) => b.id),
    selectedBuild: 0,
  },
  {
    id: 'seed-gate',
    name: 'Castle gate',
    createdAt: now - 5 * DAY,
    updatedAt: now - 4 * DAY,
    status: 'generated',
    strokes: TEMPLATES.arch.strokes,
    prompt: 'gate with an arch',
    buildIds: ['gate', 'porch', 'cottage'],
    selectedBuild: 0,
  },
  {
    id: 'seed-tower',
    name: 'Tall tower (draft)',
    createdAt: now - 9 * DAY,
    updatedAt: now - 9 * DAY,
    status: 'draft',
    strokes: TEMPLATES.tower.strokes,
    prompt: '',
    buildIds: [],
    selectedBuild: 0,
  },
]

type ProjectsValue = {
  projects: Project[]
  upsert: (p: Partial<Project> & { id?: string }) => Project
  remove: (id: string) => void
  duplicate: (id: string) => void
}

const Ctx = createContext<ProjectsValue | null>(null)

export function ProjectsProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>(() => load(KEY, SEED))
  useEffect(() => save(KEY, projects), [projects])

  // Merges against the latest state so stale closures can't revert other fields.
  const upsert: ProjectsValue['upsert'] = (patch) => {
    const id = patch.id ?? uid()
    const fresh: Project = {
      name: 'Untitled sketch',
      createdAt: Date.now(),
      status: 'draft',
      strokes: [],
      prompt: '',
      buildIds: [],
      selectedBuild: 0,
      ...patch,
      id,
      updatedAt: Date.now(),
    }
    setProjects((ps) => {
      const existing = ps.find((p) => p.id === id)
      const next = existing ? { ...existing, ...patch, id, updatedAt: Date.now() } : fresh
      return [next, ...ps.filter((p) => p.id !== id)]
    })
    return fresh
  }

  const value: ProjectsValue = {
    projects,
    upsert,
    remove: (id) => setProjects((ps) => ps.filter((p) => p.id !== id)),
    duplicate: (id) =>
      setProjects((ps) => {
        const src = ps.find((p) => p.id === id)
        if (!src) return ps
        const copy = { ...src, id: uid(), name: `${src.name} copy`, createdAt: Date.now(), updatedAt: Date.now(), status: 'draft' as const }
        return [copy, ...ps]
      }),
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useProjects() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useProjects outside ProjectsProvider')
  return ctx
}
