import type { Stroke } from '../types'

const s = (pts: [number, number][], width = 4): Stroke => ({ points: pts, width, erase: false })

/** Add a little hand wobble so templates look drawn, not ruled. */
function wobble(pts: [number, number][], seed = 1): [number, number][] {
  const out: [number, number][] = []
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i]
    const [x1, y1] = pts[i + 1]
    for (let t = 0; t < 1; t += 0.1) {
      const j = Math.sin((i * 10 + t * 10) * 1.7 + seed) * 0.003
      out.push([x0 + (x1 - x0) * t + j, y0 + (y1 - y0) * t - j])
    }
  }
  out.push(pts[pts.length - 1])
  return out
}

export const TEMPLATES: Record<string, { label: string; strokes: Stroke[] }> = {
  house: {
    label: 'House',
    strokes: [
      s(wobble([[0.25, 0.8], [0.25, 0.45], [0.75, 0.45], [0.75, 0.8], [0.25, 0.8]], 1)),
      s(wobble([[0.2, 0.47], [0.5, 0.2], [0.8, 0.47]], 2)),
      s(wobble([[0.44, 0.8], [0.44, 0.62], [0.56, 0.62], [0.56, 0.8]], 3)),
    ],
  },
  bridge: {
    label: 'Bridge',
    strokes: [
      s(wobble([[0.12, 0.45], [0.88, 0.45], [0.88, 0.52], [0.12, 0.52], [0.12, 0.45]], 4)),
      s(wobble([[0.18, 0.52], [0.18, 0.8], [0.3, 0.8], [0.3, 0.52]], 5)),
      s(wobble([[0.7, 0.52], [0.7, 0.8], [0.82, 0.8], [0.82, 0.52]], 6)),
    ],
  },
  tower: {
    label: 'Tower',
    strokes: [
      s(wobble([[0.38, 0.85], [0.38, 0.3], [0.62, 0.3], [0.62, 0.85], [0.38, 0.85]], 7)),
      s(wobble([[0.38, 0.3], [0.38, 0.22], [0.44, 0.22], [0.44, 0.3]], 8)),
      s(wobble([[0.56, 0.3], [0.56, 0.22], [0.62, 0.22], [0.62, 0.3]], 9)),
      s(wobble([[0.38, 0.55], [0.62, 0.55]], 10)),
    ],
  },
  arch: {
    label: 'Arch',
    strokes: [
      s(wobble([[0.25, 0.82], [0.25, 0.4], [0.75, 0.4], [0.75, 0.82], [0.62, 0.82], [0.62, 0.62], [0.56, 0.55], [0.44, 0.55], [0.38, 0.62], [0.38, 0.82], [0.25, 0.82]], 11)),
    ],
  },
}
