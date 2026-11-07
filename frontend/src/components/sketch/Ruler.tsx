/**
 * Centimetre rulers for the sketch board.
 *
 * The board is the build strip at 1:1 (see webapi._fit), so a centimetre on
 * these rulers is a centimetre of real blocks. When the user turns on "fit to
 * strip" the drawing gets scaled up to fill the strip instead, and the numbers
 * stop meaning anything -- so the rulers dim and say so.
 */
type Props = {
  /** Strip size in cm: width along x, height along z. */
  widthCm: number
  heightCm: number
  /** True while the sketch is being auto-scaled, which makes the scale a lie. */
  muted?: boolean
}

/** Label every `major` cm, draw a tick every `minor` cm. */
const MAJOR = 5
const MINOR = 1

function ticks(total: number) {
  const out: { cm: number; major: boolean }[] = []
  for (let cm = 0; cm <= total + 1e-6; cm += MINOR) {
    out.push({ cm, major: Math.abs(cm % MAJOR) < 1e-6 })
  }
  return out
}

export function Ruler({ widthCm, heightCm, muted = false }: Props) {
  const dim = muted ? 'opacity-40' : ''
  return (
    <>
      {/* bottom: width */}
      <div className={`pointer-events-none absolute inset-x-0 bottom-0 h-5 select-none transition-opacity ${dim}`}>
        {ticks(widthCm).map(({ cm, major }) => (
          <div key={cm} className="absolute bottom-0" style={{ left: `${(cm / widthCm) * 100}%` }}>
            <div
              className={`absolute bottom-0 w-px -translate-x-1/2 ${major ? 'h-2.5 bg-muted/70' : 'h-1.5 bg-muted/35'}`}
            />
            {major && cm > 0 && cm < widthCm && (
              <span className="absolute bottom-3 -translate-x-1/2 font-mono text-[9px] leading-none text-muted/80">
                {cm}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* left: height, measured up from the table */}
      <div className={`pointer-events-none absolute inset-y-0 left-0 w-5 select-none transition-opacity ${dim}`}>
        {ticks(heightCm).map(({ cm, major }) => (
          <div key={cm} className="absolute left-0" style={{ bottom: `${(cm / heightCm) * 100}%` }}>
            <div
              className={`absolute left-0 h-px -translate-y-1/2 ${major ? 'w-2.5 bg-muted/70' : 'w-1.5 bg-muted/35'}`}
            />
            {major && cm > 0 && cm < heightCm && (
              <span className="absolute left-3 -translate-y-1/2 font-mono text-[9px] leading-none text-muted/80">
                {cm}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* unit, parked in the corner the two rulers share */}
      <span
        className={`pointer-events-none absolute bottom-0.5 left-1 select-none font-mono text-[9px] leading-none text-muted/60 transition-opacity ${dim}`}
      >
        cm
      </span>
    </>
  )
}
