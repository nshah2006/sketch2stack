/**
 * The front-view outline of a real block. A roof is a gable, an arch has a hole
 * in it, a cylinder reads as round -- drawing them all as rectangles made the
 * board lie about what the arm is going to pick up.
 *
 * Every glyph is drawn in a 100x100 box and stretched to the block's real
 * width and height, so the silhouette is right at any size.
 */
export function BlockGlyph({ shape, color, className = '' }: {
  shape: string
  color: string
  className?: string
}) {
  const common = {
    fill: color,
    stroke: 'rgba(0,0,0,0.55)',
    strokeWidth: 2,
    vectorEffect: 'non-scaling-stroke' as const,
  }
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className={className} aria-hidden>
      {shape === 'roof' || shape === 'triangle' ? (
        // gable: a pitched roof, nothing can sit on it
        <polygon points="2,98 50,2 98,98" {...common} />
      ) : shape === 'arch' ? (
        // a doorway through the middle, flat on top so blocks can sit on it
        <path d="M2,98 L2,2 L98,2 L98,98 L72,98 L72,58 A22,26 0 0 0 28,58 L28,98 Z" {...common} />
      ) : shape === 'cylinder' ? (
        // round from above: straight sides, curved top and bottom edges
        <g>
          <path d="M2,12 L2,88 A48,12 0 0 0 98,88 L98,12 Z" {...common} />
          <ellipse cx="50" cy="12" rx="48" ry="10" fill={color}
                   stroke="rgba(0,0,0,0.55)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
          <ellipse cx="50" cy="12" rx="48" ry="10" fill="rgba(255,255,255,0.18)" />
        </g>
      ) : (
        <rect x="2" y="2" width="96" height="96" rx="3" {...common} />
      )}
    </svg>
  )
}
