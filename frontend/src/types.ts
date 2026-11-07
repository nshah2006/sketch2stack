export type BlockShape = 'cube' | 'brick' | 'plank' | 'arch' | 'cylinder' | 'triangle'
export type BlockColor = 'pink' | 'red' | 'blue' | 'yellow' | 'green' | 'white' | 'orange'

/** One toy block. x,y,z = min corner in block units, y is up. */
export type Block = {
  id: string
  x: number
  y: number
  z: number
  size: [number, number, number]
  color: BlockColor
  shape: BlockShape
  /** Robot block type (catalog id), pose (0 as shown, 1 on its side, 2 on its end), quarter turn (0|90). */
  type?: string
  pose?: number
  rot?: number
}

export type Build = {
  id: string
  name: string
  blurb: string
  stability: number
  blocks: Block[]
  source?: 'sketch' | 'preset'
  problems?: { index: number | null; level: 'error' | 'warn'; msg: string }[]
}

/** Normalized 0..1 coordinates so strokes scale with any canvas size. */
export type Stroke = {
  points: [number, number][]
  width: number
  erase: boolean
}

export type ProjectStatus = 'draft' | 'generated' | 'built'

export type Project = {
  id: string
  name: string
  createdAt: number
  updatedAt: number
  status: ProjectStatus
  strokes: Stroke[]
  prompt: string
  buildIds: string[]
  /** The generated builds themselves (ids alone can't be resolved once the server restarts). */
  builds?: Build[]
  selectedBuild: number
}

/** A build the robot was asked to run. Valid only for the server that issued it. */
export type Run = { runId: number; serverId: string; build: Build; startedAt: number; projectId: string | null }

export type User = {
  name: string
  email: string
}

export type Stage = 'sketch' | 'generating' | 'choose' | 'live'
