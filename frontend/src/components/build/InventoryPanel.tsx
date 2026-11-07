import { AlertTriangle, Check } from 'lucide-react'
import type { Block } from '../../types'
import { BLOCK_HEX, inventoryFor } from '../../mocks/builds'

export function InventoryPanel({ blocks }: { blocks: Block[] }) {
  const rows = inventoryFor(blocks)
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
            <li key={r.key} className="flex items-center gap-3 text-sm">
              <span className="h-3.5 w-3.5 shrink-0 rounded-[3px] border border-black/40" style={{ background: BLOCK_HEX[r.color] }} />
              <span className="flex-1 capitalize">{r.key}</span>
              <span className={`font-mono text-xs tabular-nums ${ok ? 'text-muted' : 'text-pink-soft'}`}>
                {Math.min(r.have, r.need)}/{r.need}
              </span>
              {ok ? <Check size={14} className="text-green-400" /> : <AlertTriangle size={14} className="text-pink" />}
            </li>
          )
        })}
      </ul>
      <p className="mt-3 border-t border-line pt-3 text-xs text-muted">
        {missing.length
          ? `Camera can't find ${missing.length} block type${missing.length > 1 ? 's' : ''} on the table. Add them or try another interpretation.`
          : 'Everything needed is on the table.'}
      </p>
    </div>
  )
}
