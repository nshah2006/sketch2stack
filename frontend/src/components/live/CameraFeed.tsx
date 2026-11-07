import { useEffect, useState } from 'react'
import { VideoOff } from 'lucide-react'
import { FRAME_URL } from '../../api'

const NOISE = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.5'/></svg>")`

/** Live overhead view from the robot server (real camera with overlays, or the simulator's map).
 *  Loads one frame at a time so a slow connection never queues up old frames. */
export function CameraFeed({ status, action, live = true }: { status: string; action: string; live?: boolean }) {
  const [src, setSrc] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [t, setT] = useState(0)

  useEffect(() => {
    if (!live) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const next = () => {
      const img = new Image()
      img.onload = () => {
        if (!alive) return
        setSrc(img.src)
        setOffline(false)
        timer = setTimeout(next, 150)
      }
      img.onerror = () => {
        if (!alive) return
        setOffline(true)
        timer = setTimeout(next, 1500)
      }
      img.src = `${FRAME_URL}?t=${Date.now()}`
    }
    next()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [live])

  useEffect(() => {
    const id = setInterval(() => setT((x) => x + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const ts = `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`
  const showImg = live && src && !offline

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-2xl border border-line bg-black">
      {showImg ? (
        <img src={src} alt="Overhead view of the table" className="absolute inset-0 h-full w-full object-contain" />
      ) : (
        <>
          <div className="absolute -inset-[10%] opacity-[0.12] [animation:noise_0.4s_steps(4)_infinite]" style={{ backgroundImage: NOISE }} />
          <div className="absolute inset-x-0 h-1/3 bg-gradient-to-b from-transparent via-pink/[0.06] to-transparent [animation:scan_4s_linear_infinite]" />
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
            <VideoOff className="text-muted" />
            <span className="font-mono text-xs tracking-[0.14em] text-muted">CAMERA OFFLINE</span>
            <span className="font-mono text-[11px] text-muted/60">start the robot server to see the table</span>
          </div>
        </>
      )}

      <div className="absolute left-3 top-3 flex items-center gap-2 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[11px]">
        <span className={`h-2 w-2 rounded-full ${status === 'running' ? 'animate-pulse bg-pink' : 'bg-muted'}`} />
        <span className="text-fg/80">CAM 01 · {status.toUpperCase()}</span>
      </div>
      <span className="absolute right-3 top-3 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-fg/70">{ts}</span>
      <div className="absolute inset-x-3 bottom-3 truncate rounded-md bg-black/70 px-2.5 py-1.5 font-mono text-[11px] text-pink-soft backdrop-blur">
        &gt; {action}
      </div>
    </div>
  )
}
