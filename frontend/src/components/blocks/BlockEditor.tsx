import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw, RotateCw, Trash2, Undo2, Hammer } from 'lucide-react'
import { api, type CatalogType, type Problem } from '../../api'
import { useBackend } from '../../backend'
import { BLOCK_HEX } from '../../mocks/builds'
import type { Block, BlockColor, Build } from '../../types'
import { uid } from '../../store/storage'
import { Ruler } from '../sketch/Ruler'
import { BlockGlyph } from './BlockGlyph'

/**
 * Place real blocks by hand instead of sketching a shape for the tiler to guess
 * at. Sizes, colours and stock all come from the catalog (which matches the
 * inventory database), so the layout is exactly what the arm will build.
 *
 * Heights are not ours to choose: the planner settles each block by gravity, so
 * every edit goes to /api/check and the heights it returns are what we draw.
 * While a block is being dragged we settle it locally so it lands live under the
 * cursor; the server has the last word once it is dropped.
 */

export type Placed = {
  id: string
  type: string
  color: string
  pose: number
  rot: 0 | 90
  x: number        // cm from the left of the strip
  depth: number
  /** Height it was dropped at, in cm. The planner settles blocks in z_hint
   *  order, so this is what decides whether a new block lands on the stack or
   *  wedges underneath it. Recorded at drop time, never read back from the
   *  server, so adding a block can never reshuffle the ones already placed. */
  hint: number
}

const GRID = 0.5    // cm
const PULL = 1.6    // cm; how close an edge has to be before it snaps
const STACK_PULL = 3.0  // cm; stacking should line up, so pull harder onto the
                        // block we are about to land on than onto a nearby edge

export function dims(t: CatalogType, pose: number, rot: number) {
  const [w, d, h] = t.poses[Math.min(pose, t.poses.length - 1)].size
  return rot === 90 ? { w: d, d: w, h } : { w, d, h }
}

/** The colour of this type we have most of, ignoring any already used. */
function fullestColour(t: CatalogType, used: Record<string, number>) {
  let best = Object.keys(t.colors)[0] ?? 'natural'
  let most = -1
  for (const [c, n] of Object.entries(t.colors)) {
    const left = n - (used[`${t.id}:${c}`] ?? 0)
    if (left > most) { most = left; best = c }
  }
  return best
}

export function toBuild(placed: Placed[], types: Record<string, CatalogType>,
                        _heights: Record<string, number>, unit: number,
                        stability = 0, problems: Problem[] = []): Build {
  return {
    id: 'editor',
    name: 'Your block layout',
    blurb: 'Placed by hand, block by block.',
    stability,
    source: 'sketch',
    problems,
    blocks: placed.map((p): Block => {
      const t = types[p.type]
      const { w, d, h } = dims(t, p.pose, p.rot)
      return {
        id: p.id,
        x: p.x / unit,
        // z_hint: where the user dropped it, so gravity is applied bottom-up in
        // the order they built. Using the settled height here instead would send
        // a brand-new block in at 0 and slide it under everything.
        y: p.hint / unit,
        z: (p.depth * 3.0) / unit,
        size: [w / unit, h / unit, d / unit],
        color: p.color as BlockColor,
        shape: (t.shape === 'box' ? 'cube' : t.shape === 'roof' ? 'triangle' : t.shape) as Block['shape'],
        type: p.type,
        pose: p.pose,
        rot: p.rot,
      }
    }),
  }
}

type Drag = {
  kind: 'new' | 'move'
  id: string | null
  type: string
  color: string
  pose: number
  rot: 0 | 90
  x: number        // live, snapped
  cursorY: number  // cm up, straight from the cursor (so it feels picked up)
  /** Set once the pointer has actually been over the strip. */
  overBoard: boolean
  /** Height it would come to rest at right now, in cm. */
  land: number
  /** Ordering key it would take, so it can slide in between two blocks. */
  hint: number
}

type Props = {
  placed: Placed[]
  onPlaced: React.Dispatch<React.SetStateAction<Placed[]>>
  onBuild: (b: Build) => void
}

export function BlockEditor({ placed, onPlaced, onBuild }: Props) {
  const { info } = useBackend()
  const widthCm = info?.grid.width ?? 20
  const heightCm = info?.grid.max_height ?? 12
  const slots = info?.grid.slots ?? 1
  const depthCm = info?.grid.depth ?? 4
  const unit = info?.unit_cm ?? 3
  const types = useMemo(() => {
    const m: Record<string, CatalogType> = {}
    for (const t of info?.catalog.types ?? []) m[t.id] = t
    return m
  }, [info])

  const [sel, setSel] = useState<string | null>(null)
  const [heights, setHeights] = useState<Record<string, number>>({})
  const [problems, setProblems] = useState<Problem[]>([])
  const [stability, setStability] = useState(0)
  const [checking, setChecking] = useState(false)
  const [drag, setDrag] = useState<Drag | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<Drag | null>(null)   // authoritative during a drag

  // How many of each type/colour the layout already uses.
  const used = useMemo(() => {
    const u: Record<string, number> = {}
    for (const p of placed) {
      u[p.type] = (u[p.type] ?? 0) + 1
      u[`${p.type}:${p.color}`] = (u[`${p.type}:${p.color}`] ?? 0) + 1
    }
    return u
  }, [placed])

  // ---- geometry helpers -------------------------------------------------
  const cmAt = useCallback((clientX: number, clientY: number) => {
    const r = boardRef.current?.getBoundingClientRect()
    if (!r) return { x: 0, y: 0 }
    return {
      x: ((clientX - r.left) / r.width) * widthCm,
      y: ((r.bottom - clientY) / r.height) * heightCm,
    }
  }, [widthCm, heightCm])

  /** Pull a dragged block's left edge onto a neighbour's edge or centre, so
   *  stacks line up instead of landing a few millimetres off. */
  const snapX = useCallback((raw: number, w: number, ignore: string | null) => {
    // Candidates, each with how strongly it pulls. Anything we would come to
    // rest on pulls hardest, so a stack lines up instead of perching on a lip.
    const want: { at: number; pull: number }[] = [
      { at: 0, pull: PULL }, { at: widthCm - w, pull: PULL },
    ]
    placed.forEach((p) => {
      if (p.id === ignore) return
      const pw = dims(types[p.type], p.pose, p.rot).w
      const over = Math.min(raw + w, p.x + pw) - Math.max(raw, p.x) > 0.2
      const pull = over ? STACK_PULL : PULL
      want.push({ at: p.x, pull })                      // flush left
      want.push({ at: p.x + pw - w, pull })             // flush right
      want.push({ at: p.x + pw / 2 - w / 2, pull })     // centred on it
      want.push({ at: p.x + pw, pull: PULL })           // butted up beside it
      want.push({ at: p.x - w, pull: PULL })
    })
    let best = Math.round(raw / GRID) * GRID
    let score = Infinity
    for (const c of want) {
      const d = Math.abs(c.at - raw)
      if (d <= c.pull && d / c.pull < score) { score = d / c.pull; best = c.at }
    }
    return Math.max(0, Math.min(widthCm - w, best))
  }, [placed, types, widthCm])

  /** Work out where a drop belongs in the column it is over.
   *
   *  Not simply "on top": the blocks it is dropped *between* decide, so a piece
   *  can be slid in between two that are already stacked. z_hint only orders the
   *  blocks for the planner (the real height comes from whatever ends up under
   *  them), so inserting is a matter of picking a hint between the neighbours'.
   *
   *  -> z, the height it would rest at right now, and hint, its ordering key. */
  const placeAt = useCallback((x: number, w: number, ignore: string | null, atZ: number) => {
    const col = placed
      .map((p, i) => ({ p, h: dims(types[p.type], p.pose, p.rot).h,
                        z: heights[String(i)] ?? p.hint,
                        pw: dims(types[p.type], p.pose, p.rot).w }))
      .filter((e) => e.p.id !== ignore &&
                     Math.min(x + w, e.p.x + e.pw) - Math.max(x, e.p.x) > 0.2)
      .sort((a, b) => a.p.hint - b.p.hint)

    // everything whose middle sits below the cursor goes under the new block
    const below = col.filter((e) => e.z + e.h / 2 < atZ)
    const lower = below[below.length - 1]
    const upper = col[below.length]

    const z = lower ? lower.z + lower.h : 0
    let hint: number
    if (!lower && !upper) hint = 0
    else if (!lower) hint = upper.p.hint - 1
    else if (!upper) hint = lower.p.hint + 1
    else hint = (lower.p.hint + upper.p.hint) / 2     // slide it in between
    return { z, hint }
  }, [placed, types, heights])

  // ---- live validation ---------------------------------------------------
  useEffect(() => {
    if (!placed.length || !Object.keys(types).length) {
      setHeights({}); setProblems([]); setStability(0)
      return
    }
    let alive = true
    setChecking(true)
    const timer = setTimeout(async () => {
      try {
        const res = await api.check(toBuild(placed, types, heights, unit))
        if (!alive) return
        setHeights(res.z); setProblems(res.problems); setStability(res.stability)
      } catch {
        /* keep editing; the status strip just goes quiet */
      } finally {
        if (alive) setChecking(false)
      }
    }, 160)
    return () => { alive = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed, types, unit])

  // ---- dragging ----------------------------------------------------------
  // The listeners live as long as the editor does and read the drag from a ref.
  // Subscribing per-drag attached them a render late, so a quick flick of the
  // wrist was dropped on the floor.
  const live = useRef({ cmAt, snapX, placeAt, types, onPlaced })
  live.current = { cmAt, snapX, placeAt, types, onPlaced }

  useEffect(() => {
    const move = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      const { cmAt, snapX, placeAt, types } = live.current
      const { x, y } = cmAt(e.clientX, e.clientY)
      const w = dims(types[d.type], d.pose, d.rot).w
      const nx = snapX(x - w / 2, w, d.id)
      const spot = placeAt(nx, w, d.id, y)
      const next = { ...d, x: nx, cursorY: y, overBoard: true, land: spot.z, hint: spot.hint }
      dragRef.current = next
      setDrag(next)
    }
    const up = () => {
      const d = dragRef.current
      dragRef.current = null
      setDrag(null)
      // Never came over the strip: a cancelled pick-up, not a drop at whatever
      // x the palette button happened to sit at.
      if (!d || !d.overBoard) return
      const { onPlaced } = live.current
      if (d.kind === 'new') {
        const id = uid()
        onPlaced((prev) => [...prev, { id, type: d.type, color: d.color, pose: d.pose,
                                       rot: d.rot, depth: 0, x: d.x, hint: d.hint }])
        setSel(id)
      } else if (d.id) {
        onPlaced((prev) => prev.map((p) => (p.id === d.id ? { ...p, x: d.x, hint: d.hint } : p)))
      }
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [])

  const update = (id: string, patch: Partial<Placed>) =>
    onPlaced((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)))
  const remove = (id: string) => {
    onPlaced((prev) => prev.filter((p) => p.id !== id))
    setSel(null)
  }

  const selected = placed.find((p) => p.id === sel) ?? null

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!selected || (e.target as HTMLElement).tagName === 'INPUT') return
      const t = types[selected.type]
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault()
        const w = dims(t, selected.pose, selected.rot).w
        update(selected.id, {
          x: Math.max(0, Math.min(widthCm - w, selected.x + (e.key === 'ArrowLeft' ? -GRID : GRID))),
        })
      } else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault()
        update(selected.id, { pose: (selected.pose + 1) % t.poses.length })
      } else if (e.key === 'Backspace' || e.key === 'Delete') {
        e.preventDefault()
        remove(selected.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const startNew = (t: CatalogType, e: React.PointerEvent) => {
    const { x, y } = cmAt(e.clientX, e.clientY)
    const w = dims(t, 0, 0).w
    const nx = snapX(x - w / 2, w, null)
    const spot = placeAt(nx, w, null, y)
    const d: Drag = { kind: 'new', id: null, type: t.id, color: fullestColour(t, used),
                      pose: 0, rot: 0, x: nx, cursorY: y,
                      overBoard: false, land: spot.z, hint: spot.hint }
    dragRef.current = d
    setDrag(d)
  }

  const errors = problems.filter((p) => p.level === 'error')
  const dragDims = drag ? dims(types[drag.type], drag.pose, drag.rot) : null
  const dragLand = drag ? drag.land : 0

  const pct = (v: number, total: number) => `${(v / total) * 100}%`

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative grid min-h-[240px] flex-1 place-items-center" style={{ containerType: 'size' }}>
        <div
          ref={boardRef}
          className="panel dot-grid relative touch-none overflow-hidden"
          style={{ aspectRatio: `${widthCm} / ${heightCm}`, width: `min(100cqw, 100cqh * ${widthCm / heightCm})` }}
          onPointerDown={(e) => { if (e.target === e.currentTarget) setSel(null) }}
        >
          <Ruler widthCm={widthCm} heightCm={heightCm} />

          {placed.map((p, i) => {
            const t = types[p.type]
            if (!t) return null
            const { w, h } = dims(t, p.pose, p.rot)
            const z = heights[String(i)] ?? p.hint
            const bad = problems.some((q) => q.index === i && q.level === 'error')
            const warn = problems.some((q) => q.index === i && q.level === 'warn')
            const hidden = drag?.kind === 'move' && drag.id === p.id
            return (
              <div
                key={p.id}
                role="button"
                tabIndex={0}
                onPointerDown={(e) => {
                  e.stopPropagation()
                  setSel(p.id)
                  const { y } = cmAt(e.clientX, e.clientY)
                  const d: Drag = { kind: 'move', id: p.id, type: p.type, color: p.color,
                                    pose: p.pose, rot: p.rot, x: p.x, cursorY: y,
                                    overBoard: true, land: p.hint, hint: p.hint }
                  dragRef.current = d
                  setDrag(d)
                }}
                className={`absolute cursor-grab transition-[filter] ${hidden ? 'opacity-0' : ''} ${
                  sel === p.id ? 'drop-shadow-[0_0_6px_rgba(255,46,147,0.9)]' : ''
                }`}
                style={{ left: pct(p.x, widthCm),
                         // keep an over-tall block on screen: it is flagged as an
                         // error, and you cannot drag what you cannot see
                         bottom: pct(Math.min(z, Math.max(0, heightCm - h)), heightCm),
                         width: pct(w, widthCm), height: pct(h, heightCm),
                         opacity: hidden ? 0 : p.depth > 0 ? 0.6 : 1 }}
                title={`${t.name} ${p.color} · ${w}x${h} cm at x ${p.x}, ${z} cm up`}
              >
                <BlockGlyph shape={t.shape} color={BLOCK_HEX[p.color as BlockColor] ?? '#d4a373'}
                            className="h-full w-full" />
                {(bad || warn) && (
                  <span className={`pointer-events-none absolute inset-0 rounded-[3px] ring-2 ${
                    bad ? 'ring-red-400' : 'ring-yellow-300/80'}`} />
                )}
              </div>
            )
          })}

          {/* where it will land, and the block itself riding the cursor */}
          {drag && dragDims && (
            <>
              <div className="pointer-events-none absolute rounded-[3px] border-2 border-dashed border-pink/70 bg-pink/10"
                   style={{ left: pct(drag.x, widthCm), bottom: pct(dragLand, heightCm),
                            width: pct(dragDims.w, widthCm), height: pct(dragDims.h, heightCm) }} />
              <div className="pointer-events-none absolute opacity-80"
                   style={{ left: pct(drag.x, widthCm),
                            bottom: pct(Math.max(dragLand, drag.cursorY - dragDims.h / 2), heightCm),
                            width: pct(dragDims.w, widthCm), height: pct(dragDims.h, heightCm) }}>
                <BlockGlyph shape={types[drag.type].shape}
                            color={BLOCK_HEX[drag.color as BlockColor] ?? '#d4a373'}
                            className="h-full w-full" />
              </div>
            </>
          )}

          {!placed.length && !drag && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1 text-center">
              <p className="text-sm text-muted">Pick up a block and drop it on the strip</p>
              <p className="text-xs text-muted/60">Real sizes and real stock. It snaps to what is already there.</p>
            </div>
          )}
        </div>
      </div>

      {/* Selected block */}
      {selected && types[selected.type] && (() => {
        const t = types[selected.type]
        const d = dims(t, selected.pose, selected.rot)
        const turned = dims(t, selected.pose, selected.rot === 0 ? 90 : 0)
        const fits = turned.d <= depthCm + 0.01
        return (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-raised px-3 py-2">
            <span className="label">{t.name}</span>
            <span className="font-mono text-[11px] text-muted">{d.w} x {d.d} x {d.h} cm</span>

            {/* colours we actually own, most-stocked first */}
            <span className="flex items-center gap-1">
              {Object.entries(t.colors)
                .sort((a, b) => b[1] - a[1])
                .map(([c, n]) => {
                  const left = n - (used[`${t.id}:${c}`] ?? 0) + (selected.color === c ? 1 : 0)
                  return (
                    <button
                      key={c}
                      disabled={left <= 0}
                      title={`${c}: ${Math.max(0, left)} left`}
                      onClick={() => update(selected.id, { color: c })}
                      style={{ background: BLOCK_HEX[c as BlockColor] ?? '#d4a373' }}
                      className={`h-5 w-5 rounded-full border transition-transform disabled:opacity-25 ${
                        selected.color === c ? 'border-fg scale-110' : 'border-black/40 hover:scale-105'
                      }`}
                    />
                  )
                })}
            </span>

            <button
              className="btn border border-line px-2 py-1 text-xs disabled:opacity-30"
              disabled={t.poses.length < 2}
              title={t.poses.length < 2 ? 'This block only stands one way'
                                        : 'Tip it onto another face (you hand it over that way)'}
              onClick={() => update(selected.id, { pose: (selected.pose + 1) % t.poses.length })}
            >
              <RotateCw size={13} /> {t.poses[selected.pose].name}
            </button>
            <button
              className="btn border border-line px-2 py-1 text-xs disabled:opacity-30"
              disabled={!fits}
              title={fits ? 'Turn a quarter about the upright axis (the arm does this itself)'
                          : `Turned it would be ${turned.d} cm front-to-back, and the strip is only ${depthCm} cm deep`}
              onClick={() => update(selected.id, { rot: selected.rot === 0 ? 90 : 0 })}
            >
              <RefreshCw size={13} /> {selected.rot}&deg;
            </button>
            {slots > 1 && (
              <button className="btn border border-line px-2 py-1 text-xs"
                      onClick={() => update(selected.id, { depth: (selected.depth + 1) % slots })}>
                depth {selected.depth + 1}/{slots}
              </button>
            )}
            <button className="btn border border-line px-2 py-1 text-xs text-muted hover:text-fg"
                    onClick={() => remove(selected.id)}>
              <Trash2 size={13} /> Remove
            </button>
          </div>
        )
      })()}

      {/* Palette */}
      <div className="flex flex-wrap gap-2">
        {(info?.catalog.types ?? []).map((t) => {
          const left = t.count - (used[t.id] ?? 0)
          const [w, d, h] = t.size
          return (
            <button
              key={t.id}
              disabled={left <= 0}
              onPointerDown={(e) => { if (left > 0) startNew(t, e) }}
              title={`${t.name}: ${w} x ${d} x ${h} cm, ${left} of ${t.count} left`}
              className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors ${
                left > 0 ? 'cursor-grab border-line hover:border-pink/60' : 'border-line opacity-35'
              }`}
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center">
                <BlockGlyph shape={t.shape} color={BLOCK_HEX[fullestColour(t, used) as BlockColor] ?? '#d4a373'}
                            className="h-full w-full" />
              </span>
              <span className="flex flex-col">
                <span className="text-xs">{t.name}</span>
                <span className="font-mono text-[10px] text-muted">{w}x{d}x{h} &middot; {left} left</span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[11px] text-muted">
          {checking ? 'checking...' : `${placed.length} block${placed.length === 1 ? '' : 's'} · ${stability}% stable`}
        </span>
        {errors.length > 0 && <span className="text-[11px] text-red-400">{errors[0].msg}</span>}
        <div className="ml-auto flex gap-2">
          <button className="btn border border-line px-3 text-xs disabled:opacity-30"
                  disabled={!placed.length} onClick={() => { onPlaced([]); setSel(null) }}>
            <Undo2 size={14} /> Clear
          </button>
          <button
            className="btn-pink px-5"
            disabled={!placed.length || errors.length > 0 || checking}
            title={errors.length ? errors[0].msg : 'Send this exact layout to the arm'}
            onClick={() => onBuild(toBuild(placed, types, heights, unit, stability, problems))}
          >
            <Hammer size={15} /> Build these blocks
          </button>
        </div>
      </div>
    </div>
  )
}
