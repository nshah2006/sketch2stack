import { BLOCK_HEX } from '../../mocks/builds'
import type { BlockColor } from '../../types'
import type { CatalogType } from '../../api'

/** Every colour we own, most blocks first. "Any" lets the tiler use whatever
 *  there is most of, which is usually the right answer. */
export function coloursOwned(types: CatalogType[]) {
  const total: Record<string, number> = {}
  for (const t of types) for (const [c, n] of Object.entries(t.colors)) total[c] = (total[c] ?? 0) + n
  return Object.entries(total).sort((a, b) => b[1] - a[1])
}

export function ColourPicker({ types, value, onChange }: {
  types: CatalogType[]
  value: string | null
  onChange: (c: string | null) => void
}) {
  const owned = coloursOwned(types)
  if (!owned.length) return null
  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="Block colour">
      <button
        onClick={() => onChange(null)}
        aria-pressed={value === null}
        title="Any colour: use whatever we have most of"
        className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
          value === null ? 'border-pink bg-pink/15 text-pink-soft' : 'border-line text-muted hover:text-fg'
        }`}
      >
        Any
      </button>
      {owned.map(([c, n]) => (
        <button
          key={c}
          onClick={() => onChange(c === value ? null : c)}
          aria-pressed={value === c}
          title={`${c}: ${n} blocks owned`}
          style={{ background: BLOCK_HEX[c as BlockColor] ?? '#d4a373' }}
          className={`h-5 w-5 rounded-full border transition-transform ${
            value === c ? 'scale-110 border-fg' : 'border-black/40 hover:scale-105'
          }`}
        />
      ))}
    </div>
  )
}
