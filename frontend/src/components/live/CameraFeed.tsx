import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { VideoOff } from 'lucide-react'

const NOISE = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.5'/></svg>")`

const DETECTIONS = [
  { x: 14, y: 58, w: 16, h: 14, label: 'red_brick', conf: 0.94 },
  { x: 38, y: 64, w: 11, h: 13, label: 'yellow_cube', conf: 0.91 },
  { x: 62, y: 52, w: 17, h: 15, label: 'blue_brick', conf: 0.88 },
  { x: 47, y: 22, w: 14, h: 22, label: 'gripper', conf: 0.97 },
]

export function CameraFeed({ status, action }: { status: string; action: string }) {
  const [t, setT] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setT((x) => x + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const ts = `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-2xl border border-line bg-black">
      {/* noise + scanline */}
      <div className="absolute -inset-[10%] opacity-[0.12] [animation:noise_0.4s_steps(4)_infinite]" style={{ backgroundImage: NOISE }} />
      <div className="absolute inset-x-0 h-1/3 bg-gradient-to-b from-transparent via-pink/[0.06] to-transparent [animation:scan_4s_linear_infinite]" />
      <div className="absolute inset-0 bg-[repeating-linear-gradient(0deg,transparent_0,transparent_2px,rgba(0,0,0,0.35)_3px)]" />

      {/* placeholder message */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
        <VideoOff className="text-muted" />
        <span className="font-mono text-xs tracking-[0.14em] text-muted">CAMERA OFFLINE</span>
        <span className="font-mono text-[11px] text-muted/60">overhead feed will stream here</span>
      </div>

      {/* fake detections */}
      {DETECTIONS.map((d, i) => (
        <motion.div
          key={d.label}
          className="absolute"
          style={{ left: `${d.x}%`, top: `${d.y}%`, width: `${d.w}%`, height: `${d.h}%` }}
          initial={{ opacity: 0, scale: 1.2 }}
          animate={{ opacity: 1, scale: 1, x: [0, 2, -1, 0], y: [0, -1, 2, 0] }}
          transition={{
            opacity: { delay: 0.3 + i * 0.15 },
            scale: { delay: 0.3 + i * 0.15, type: 'spring', bounce: 0.3 },
            x: { duration: 2.5 + i * 0.3, repeat: Infinity },
            y: { duration: 2.1 + i * 0.4, repeat: Infinity },
          }}
        >
          {(['left-0 top-0 border-l-2 border-t-2', 'right-0 top-0 border-r-2 border-t-2', 'left-0 bottom-0 border-l-2 border-b-2', 'right-0 bottom-0 border-r-2 border-b-2'] as const).map((c) => (
            <span key={c} className={`absolute h-3 w-3 border-pink ${c}`} />
          ))}
          <span className="absolute -top-5 left-0 whitespace-nowrap bg-pink px-1 font-mono text-[10px] text-black">
            {d.label} {d.conf.toFixed(2)}
          </span>
        </motion.div>
      ))}

      {/* HUD */}
      <div className="absolute left-3 top-3 flex items-center gap-2 font-mono text-[11px]">
        <span className={`h-2 w-2 rounded-full ${status === 'running' ? 'animate-pulse bg-pink' : 'bg-muted'}`} />
        <span className="text-fg/80">CAM 01 · {status.toUpperCase()}</span>
      </div>
      <span className="absolute right-3 top-3 font-mono text-[11px] tabular-nums text-fg/70">{ts}</span>
      <div className="absolute inset-x-3 bottom-3 truncate rounded-md bg-black/70 px-2.5 py-1.5 font-mono text-[11px] text-pink-soft backdrop-blur">
        &gt; {action}
      </div>
    </div>
  )
}
