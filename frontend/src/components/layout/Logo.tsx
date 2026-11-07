export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="relative flex items-center gap-2.5">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden>
        <path d="M4 22 C8 14 12 9 16 5" stroke="var(--pink)" strokeWidth="2.4" strokeLinecap="round" fill="none" />
        <rect x="13" y="15" width="11" height="8" rx="1.5" fill="var(--pink)" />
        <rect x="16" y="9" width="8" height="6" rx="1.5" fill="var(--pink-soft)" />
      </svg>
      {!compact && (
        <span className="text-lg font-semibold tracking-tight">
          Sketch<span className="text-pink">2</span>Stack
        </span>
      )}
    </div>
  )
}
