import { AlertTriangle, Check } from 'lucide-react'
import type { Block } from '../../types'
import { BLOCK_HEX } from '../../mocks/builds'
import { useBackend } from '../../backend'

/** Blocks this build needs vs. blocks the team owns (from the robot server's catalog). */
export function InventoryPanel({ blocks }: { blocks: Block[] }) {
  const { info } = useBackend()
  const byColor = info?.use_color ?? false
  const need = new Map<string, { label: string; color: Block['color']; need: number; have: number }>()
  for (const b of blocks) {
    const type = b.type ?? b.shape
    const item = info?.inventory[type]
    const key = byColor ? `${b.color} ${type}` : type
    const cur = need.get(key) ?? {
      label: byColor ? `${b.color} ${item?.name ?? type}` : item?.name ?? type,
      color: b.color,
      need: 0,
      have: item ? (byColor ? item.colors[b.color] ?? 0 : item.count) : 0,
    }
    cur.need++
    need.set(key, cur)
  }
  const rows = [...need.values()]
  const missing = rows.filter((r) => r.have < r.need)
  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between">
        <span className="label">Blocks needed</span>
        <span className="font-mono text-xs text-muted">{blocks.length} total</span>
      </div>
      <ul className="mt-3 space-y-2">
        {rows.map((r) => {
          const ok = r.have >= r.need
          return (
            <li key={r.label} className="flex items-center gap-3 text-sm">
              <span className="h-3.5 w-3.5 shrink-0 rounded-[3px] border border-black/40" style={{ background: BLOCK_HEX[r.color] ?? '#999' }} />
              <span className="flex-1">{r.label}</span>
              <span className={`font-mono text-xs tabular-nums ${ok ? 'text-muted' : 'text-pink-soft'}`}>
                {r.need}/{r.have} owned
              </span>
              {ok ? <Check size={14} className="text-green-400" /> : <AlertTriangle size={14} className="text-pink" />}
            </li>
          )
        })}
      </ul>
      <p className="mt-3 border-t border-line pt-3 text-xs text-muted">
        {!info
          ? 'Robot server offline: start `python -m sidekick ui`.'
          : missing.length
            ? `Not enough ${missing.map((m) => m.label.toLowerCase()).join(', ')}. Try another interpretation.`
            : byColor
              ? 'Put these in the supply zones; the camera finds them.'
              : "You'll hand each block to the arm on the pickup spot when it asks."}
      </p>
    </div>
  )
}
