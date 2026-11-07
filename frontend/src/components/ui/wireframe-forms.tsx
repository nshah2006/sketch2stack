import { useEffect, useRef, type CSSProperties, type MutableRefObject } from 'react'
import { cn } from '@/lib/utils'

/*
 * Rotating wireframe forms (cube / cylinders / sphere) on a 2D canvas.
 * Ported from the "Wireframe Forms" WireframeEngine. The original wrapped it in an
 * iframe page that pulled Tailwind CDN, GSAP and Iconify; this keeps only the engine,
 * so it's one canvas and one rAF loop with no outside scripts.
 */

export type WireframeVariant = 'cube' | 'cylinders' | 'sphere'

export type WireframeFormsProps = {
  variant?: WireframeVariant
  /** Rotation speed multiplier (0..3). */
  speed?: number
  /** Line width multiplier. */
  size?: number
  /** Shape scale (0.35..2.5). */
  length?: number
  opacity?: number
  /** Stroke color as "r, g, b". */
  rgb?: string
  /** 0..1 live intensity (e.g. mic level). Read every frame; changing it never re-renders. */
  levelRef?: MutableRefObject<number>
  /** 0..1 impulse (e.g. a word was heard). Decays on its own. */
  kickRef?: MutableRefObject<number>
  /** Listening: sit almost still in silence so speech reads clearly. */
  listening?: boolean
  className?: string
  style?: CSSProperties
}

type P3 = { x: number; y: number; z: number }

function buildShape(variant: WireframeVariant) {
  const points: P3[] = []
  const edges: [number, number][] = []
  if (variant === 'cube') {
    const s = 80
    points.push({ x: s, y: s, z: s }, { x: -s, y: -s, z: s }, { x: -s, y: s, z: -s }, { x: s, y: -s, z: -s })
    points.push({ x: -s, y: -s, z: -s }, { x: s, y: s, z: -s }, { x: s, y: -s, z: s }, { x: -s, y: s, z: s })
    edges.push([0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3], [4, 5], [4, 6], [4, 7], [5, 6], [5, 7], [6, 7])
  } else if (variant === 'cylinders') {
    const r = 70
    const seg = 24
    for (let i = 0; i < seg; i++) {
      const t = (i / seg) * Math.PI * 2
      points.push({ x: Math.cos(t) * r, y: Math.sin(t) * r, z: -30 }, { x: Math.cos(t) * r, y: Math.sin(t) * r, z: 30 })
      const n = (i + 1) % seg
      edges.push([i * 2, n * 2], [i * 2 + 1, n * 2 + 1], [i * 2, i * 2 + 1])
    }
    const off = points.length
    for (let i = 0; i < seg; i++) {
      const t = (i / seg) * Math.PI * 2
      points.push({ x: Math.cos(t) * r, y: -30, z: Math.sin(t) * r }, { x: Math.cos(t) * r, y: 30, z: Math.sin(t) * r })
      const n = (i + 1) % seg
      edges.push([off + i * 2, off + n * 2], [off + i * 2 + 1, off + n * 2 + 1], [off + i * 2, off + i * 2 + 1])
    }
  } else {
    // Icosahedron with a smaller inner one, spokes between them.
    const t = (1 + Math.sqrt(5)) / 2
    const s = 50
    const base = [
      [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
      [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
      [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
    ]
    base.forEach(([x, y, z]) => points.push({ x: x * s, y: y * s, z: z * s }))
    const dist = (a: P3, b: P3) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)
    for (let i = 0; i < 12; i++) for (let j = i + 1; j < 12; j++) if (dist(points[i], points[j]) < s * 2.1) edges.push([i, j])
    base.forEach(([x, y, z]) => points.push({ x: x * s * 0.5, y: y * s * 0.5, z: z * s * 0.5 }))
    for (let i = 0; i < 12; i++) {
      for (let j = i + 1; j < 12; j++) if (dist(points[12 + i], points[12 + j]) < s * 1.1) edges.push([12 + i, 12 + j])
      edges.push([i, 12 + i])
    }
  }
  return { points, edges }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export default function WireframeForms({
  variant = 'sphere',
  speed = 1,
  size = 1,
  length = 1,
  opacity = 1,
  rgb = '255, 46, 147',
  levelRef,
  kickRef,
  listening = false,
  className,
  style,
}: WireframeFormsProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // Props read inside the loop without restarting it.
  const live = useRef({ speed, size, length, opacity, rgb, listening })
  live.current = { speed: clamp(speed, 0, 3), size: clamp(size, 0.25, 8), length: clamp(length, 0.35, 2.5), opacity: clamp(opacity, 0.05, 1), rgb, listening }

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const { points, edges } = buildShape(variant)
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let w = 0
    let h = 0
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)

    let ax = 0
    let ay = 0
    let lvl = 0
    let kick = 0
    let base = 1
    let raf = 0
    let last = performance.now()

    const frame = (now: number) => {
      const dt = Math.min((now - last) / 16.67, 3) // in 60fps frames, capped after tab switches
      last = now
      const k = live.current
      // Fast attack, slower release: it jumps with your voice and settles when you stop.
      const target = levelRef?.current ?? 0
      lvl += (target - lvl) * Math.min((target > lvl ? 0.45 : 0.1) * dt, 1)
      // A heard word kicks it; the kick decays quickly like a tap.
      if (kickRef && kickRef.current > 0) {
        kick = Math.max(kick, kickRef.current)
        kickRef.current = 0
      }
      kick *= Math.pow(0.86, dt)
      // Listening in silence: nearly still. Idle: calm drift.
      base += ((k.listening ? 0.12 : 1) - base) * Math.min(0.08 * dt, 1)
      const spin = reduce ? 0.15 : base + lvl * 9 + kick * 7
      ay += 0.005 * k.speed * spin * dt
      ax += 0.002 * k.speed * spin * dt

      const breathe = reduce ? 1 : 1 + Math.sin(now / 1400) * (k.listening ? 0.01 : 0.03)
      const fit = (Math.min(w, h) / 300) * k.length * breathe * (1 + lvl * 0.22 + kick * 0.14)
      const cx = w / 2
      const cy = h / 2
      const cosY = Math.cos(ay), sinY = Math.sin(ay), cosX = Math.cos(ax), sinX = Math.sin(ax)

      const proj = points.map((p) => {
        const x = p.x * cosY - p.z * sinY
        let z = p.z * cosY + p.x * sinY
        const y = p.y * cosX - z * sinX
        z = z * cosX + p.y * sinX
        const s = 400 / (400 + z)
        return { x: x * s * fit + cx, y: y * s * fit + cy, z }
      })

      ctx.clearRect(0, 0, w, h)
      ctx.lineWidth = 0.9 * k.size
      const glow = Math.min(1, 0.4 + lvl * 0.6 + kick * 0.4)
      for (const [a, b] of edges) {
        const p1 = proj[a], p2 = proj[b]
        const alpha = Math.max(0.1, 1 - (p1.z + p2.z) / 2 / 200)
        ctx.strokeStyle = `rgba(${k.rgb}, ${alpha * glow * k.opacity})`
        ctx.beginPath()
        ctx.moveTo(p1.x, p1.y)
        ctx.lineTo(p2.x, p2.y)
        ctx.stroke()
      }
      for (const p of proj) {
        const alpha = Math.max(0.1, 1 - p.z / 200)
        if (alpha > 0.5) {
          ctx.fillStyle = `rgba(${k.rgb}, ${alpha * k.opacity})`
          const r = 1.2 + lvl * 1.6 + kick * 1.2
          ctx.fillRect(p.x - r, p.y - r, r * 2, r * 2)
        }
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [variant, levelRef, kickRef])

  return <canvas ref={canvasRef} className={cn('block h-full w-full', className)} style={style} aria-hidden />
}
