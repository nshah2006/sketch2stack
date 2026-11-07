import { useEffect, useRef } from 'react'
import type { Stroke } from '../../types'

const BASE = 800 // stroke widths are stored relative to an 800px-wide board

type Props = {
  strokes: Stroke[]
  onCommit: (s: Stroke) => void
  tool: 'pen' | 'eraser'
  width: number
}

export function SketchCanvas({ strokes, onCommit, tool, width }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const current = useRef<Stroke | null>(null)
  // The resize observer is set up once; it must redraw the latest strokes, not the first ones.
  const strokesRef = useRef(strokes)
  strokesRef.current = strokes

  const ctx2d = () => canvasRef.current?.getContext('2d') ?? null

  function drawStroke(ctx: CanvasRenderingContext2D, s: Stroke, from = 0) {
    const c = ctx.canvas
    const w = c.width
    const h = c.height
    const scale = w / BASE
    ctx.save()
    ctx.globalCompositeOperation = s.erase ? 'destination-out' : 'source-over'
    ctx.strokeStyle = '#ff2e93'
    ctx.lineWidth = s.width * scale * (s.erase ? 4 : 1)
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    if (!s.erase) {
      ctx.shadowColor = 'rgba(255,46,147,0.55)'
      ctx.shadowBlur = 10 * scale
    }
    ctx.beginPath()
    const pts = s.points
    const start = Math.max(from - 1, 0)
    ctx.moveTo(pts[start][0] * w, pts[start][1] * h)
    if (pts.length === 1) ctx.lineTo(pts[0][0] * w + 0.1, pts[0][1] * h)
    for (let i = start + 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * w, pts[i][1] * h)
    ctx.stroke()
    ctx.restore()
  }

  function redraw() {
    const ctx = ctx2d()
    if (!ctx) return
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height)
    for (const s of strokesRef.current) drawStroke(ctx, s)
  }

  // Keep backing store matched to display size × DPR.
  useEffect(() => {
    const c = canvasRef.current
    if (!c) return
    const ro = new ResizeObserver(() => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      c.width = Math.round(c.clientWidth * dpr)
      c.height = Math.round(c.clientHeight * dpr)
      redraw()
    })
    ro.observe(c)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(redraw) // strokes changed (undo/redo/clear/template)

  const pt = (e: React.PointerEvent): [number, number] => {
    const r = canvasRef.current!.getBoundingClientRect()
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]
  }

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 h-full w-full touch-none"
      style={{ cursor: tool === 'pen' ? 'crosshair' : 'cell' }}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        current.current = { points: [pt(e)], width, erase: tool === 'eraser' }
        const ctx = ctx2d()
        if (ctx) drawStroke(ctx, current.current)
      }}
      onPointerMove={(e) => {
        const s = current.current
        if (!s) return
        s.points.push(pt(e))
        const ctx = ctx2d()
        if (ctx) drawStroke(ctx, s, s.points.length - 1)
      }}
      onPointerUp={() => {
        if (current.current) onCommit(current.current)
        current.current = null
      }}
      onPointerCancel={() => {
        current.current = null
        redraw()
      }}
    />
  )
}
