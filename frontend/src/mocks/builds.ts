import type { Block, BlockColor, BlockShape, Build } from '../types'

export const BLOCK_HEX: Record<BlockColor, string> = {
  pink: '#ff2e93',
  red: '#e8384f',
  blue: '#3b82f6',
  yellow: '#facc15',
  green: '#22c55e',
  white: '#e7e5e4',
}

let n = 0
const b = (
  x: number,
  y: number,
  z: number,
  w: number,
  h: number,
  d: number,
  color: BlockColor,
  shape: BlockShape = 'cube',
): Block => ({ id: `b${n++}`, x, y, z, size: [w, h, d], color, shape })

export const BUILDS: Build[] = [
  {
    id: 'cottage',
    name: 'Cottage',
    blurb: 'Closest to your sketch. Two-layer walls, single pitched roof.',
    stability: 92,
    blocks: [
      b(0, 0, 0, 2, 1, 1, 'red', 'brick'),
      b(2, 0, 0, 2, 1, 1, 'blue', 'brick'),
      b(0, 1, 0, 1, 1, 1, 'yellow'),
      b(1, 1, 0, 2, 1, 1, 'red', 'brick'),
      b(3, 1, 0, 1, 1, 1, 'yellow'),
      b(0, 2, 0, 4, 1.2, 1, 'pink', 'triangle'),
    ],
  },
  {
    id: 'porch',
    name: 'Column porch',
    blurb: 'Swaps walls for pillars. Lighter, with an open doorway.',
    stability: 84,
    blocks: [
      b(0, 0, 0, 1, 2, 1, 'blue', 'cylinder'),
      b(3, 0, 0, 1, 2, 1, 'blue', 'cylinder'),
      b(1, 0, 0, 2, 1, 1, 'white', 'arch'),
      b(0, 2, 0, 4, 0.5, 1, 'yellow', 'plank'),
      b(0, 2.5, 0, 4, 1.2, 1, 'pink', 'triangle'),
    ],
  },
  {
    id: 'gate',
    name: 'Arch gate',
    blurb: 'Reads the doorway as an arch. Taller, narrower base.',
    stability: 78,
    blocks: [
      b(0, 0, 0, 1, 1, 1, 'green'),
      b(3, 0, 0, 1, 1, 1, 'green'),
      b(0, 1, 0, 1, 1, 1, 'yellow'),
      b(3, 1, 0, 1, 1, 1, 'yellow'),
      b(1, 0, 0, 2, 1, 1, 'white', 'arch'),
      b(1, 1, 0, 2, 1, 1, 'red', 'brick'),
      b(0, 2, 0, 4, 0.5, 1, 'blue', 'plank'),
      b(1, 2.5, 0, 2, 1, 1, 'pink', 'triangle'),
    ],
  },
  {
    id: 'bungalow',
    name: 'Deep bungalow',
    blurb: 'Adds depth for stability. Uses the most blocks.',
    stability: 95,
    blocks: [
      b(0, 0, 0, 2, 1, 1, 'red', 'brick'),
      b(2, 0, 0, 2, 1, 1, 'red', 'brick'),
      b(0, 0, 1, 2, 1, 1, 'blue', 'brick'),
      b(2, 0, 1, 2, 1, 1, 'blue', 'brick'),
      b(0, 1, 0, 1, 1, 1, 'yellow'),
      b(3, 1, 0, 1, 1, 1, 'yellow'),
      b(0, 1, 1, 4, 1, 1, 'white', 'plank'),
      b(1, 1, 0, 2, 1, 1, 'green', 'arch'),
      b(0, 2, 0, 4, 1.2, 2, 'pink', 'triangle'),
    ],
  },
]

export const buildById = (id: string) => BUILDS.find((x) => x.id === id) ?? BUILDS[0]

/** Robot placement order: bottom layer first, left to right, front to back. */
export function buildSteps(blocks: Block[]) {
  return [...blocks]
    .sort((a, b) => a.y - b.y || a.z - b.z || a.x - b.x)
    .map((blk, i) => ({
      index: i,
      block: blk,
      label: `Place ${blk.color} ${blk.shape}`,
      detail: `at (${blk.x}, ${blk.z}) · layer ${Math.floor(blk.y) + 1}`,
    }))
}

/** Mock table inventory the camera "sees". */
export const INVENTORY: Record<string, number> = {
  'red brick': 3,
  'blue brick': 2,
  'yellow cube': 4,
  'green cube': 2,
  'pink triangle': 1,
  'blue cylinder': 2,
  'white arch': 1,
  'green arch': 0,
  'yellow plank': 1,
  'blue plank': 1,
  'white plank': 0,
}

export function inventoryFor(blocks: Block[]) {
  const need = new Map<string, { color: BlockColor; shape: BlockShape; need: number }>()
  for (const blk of blocks) {
    const key = `${blk.color} ${blk.shape}`
    const cur = need.get(key) ?? { color: blk.color, shape: blk.shape, need: 0 }
    cur.need++
    need.set(key, cur)
  }
  return [...need.entries()].map(([key, v]) => ({ key, ...v, have: INVENTORY[key] ?? 0 }))
}
