import type { Block, Stroke } from '../../types'
import { BLOCK_HEX } from '../../mocks/builds'

const C = 0.866

function shade(hex: string, k: number) {
  const n = parseInt(hex.slice(1), 16)
  const f = (v: number) => Math.max(0, Math.min(255, Math.round(v * k)))
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`
}

/** Cheap isometric SVG of a build for cards and lists. */
export function IsoThumb({ blocks, className }: { blocks: Block[]; className?: string }) {
  const P = (x: number, y: number, z: number) => [(x - z) * C, (x + z) * 0.5 - y] as const
  const polys: { pts: string; fill: string }[] = []
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const sorted = [...blocks].sort((a, b) => a.x + a.z - (b.x + b.z) || a.y - b.y)
  for (const b of sorted) {
    const [w, h, d] = b.size
    const x0 = b.x, y0 = b.y, z0 = b.z, x1 = x0 + w, y1 = y0 + h, z1 = z0 + d
    const hex = BLOCK_HEX[b.color]
    const face = (pts: (readonly [number, number])[], k: number) => {
      for (const [px, py] of pts) {
        minX = Math.min(minX, px); maxX = Math.max(maxX, px)
        minY = Math.min(minY, py); maxY = Math.max(maxY, py)
      }
      polys.push({ pts: pts.map((p) => p.join(',')).join(' '), fill: shade(hex, k) })
    }
    face([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], 1.08)
    face([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], 0.72)
    face([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], 0.88)
  }
  const pad = 0.4
  const vb = `${minX - pad} ${minY - pad} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`
  return (
    <svg viewBox={vb} className={className} aria-hidden>
      {polys.map((p, i) => (
        <polygon key={i} points={p.pts} fill={p.fill} stroke="#0a0a0b" strokeWidth={0.04} strokeLinejoin="round" />
      ))}
    </svg>
  )
}

export function SketchThumb({ strokes, className }: { strokes: Stroke[]; className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden>
      {strokes.map((s, i) => (
        <polyline
          key={i}
          points={s.points.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
          fill="none"
          stroke={s.erase ? 'var(--surface)' : 'var(--pink)'}
          strokeWidth={s.erase ? s.width * 0.6 : Math.max(1.2, s.width * 0.3)}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  )
}
