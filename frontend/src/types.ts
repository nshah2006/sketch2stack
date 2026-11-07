export type BlockShape = 'cube' | 'brick' | 'plank' | 'arch' | 'cylinder' | 'triangle'
export type BlockColor = 'pink' | 'red' | 'blue' | 'yellow' | 'green' | 'white'

/** One toy block. x,y,z = min corner in block units, y is up. */
export type Block = {
  id: string
  x: number
  y: number
  z: number
  size: [number, number, number]
  color: BlockColor
  shape: BlockShape
}

export type Build = {
  id: string
  name: string
  blurb: string
  stability: number
  blocks: Block[]
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
  selectedBuild: number
}

export type User = {
  name: string
  email: string
}

export type Stage = 'sketch' | 'generating' | 'choose' | 'live'
