import { Blocks, PenLine } from 'lucide-react'

export type BoardMode = 'draw' | 'blocks'

/** Draw a shape and let the tiler guess at it, or place real blocks yourself. */
export function BoardModeToggle({ mode, onMode }: { mode: BoardMode; onMode: (m: BoardMode) => void }) {
  return (
    <div className="flex rounded-full border border-line p-0.5">
      {([['draw', 'Draw', PenLine], ['blocks', 'Blocks', Blocks]] as const).map(([k, label, Icon]) => (
        <button
          key={k}
          onClick={() => onMode(k)}
          aria-pressed={mode === k}
          title={k === 'draw' ? 'Sketch a shape; the tiler picks the blocks'
                              : 'Place real blocks yourself, at their real sizes'}
          className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors ${
            mode === k ? 'bg-pink text-black' : 'text-muted hover:text-pink-soft'
          }`}
        >
          <Icon size={13} /> {label}
        </button>
      ))}
    </div>
  )
}
