import { useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { ContactShadows, Edges, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import type { Block } from '../../types'
import { BLOCK_HEX } from '../../mocks/builds'

const reduceMotion =
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Arches and roofs turned a quarter turn: build them unturned, then rotate the mesh. */
const turned = (b: Block) => b.rot === 90 && (b.shape === 'arch' || b.shape === 'triangle')

function useBlockGeometry(block: Block) {
  const [sx, h, sz] = block.size
  const [w, d] = turned(block) ? [sz, sx] : [sx, sz]
  return useMemo(() => {
    switch (block.shape) {
      case 'cylinder':
        return new THREE.CylinderGeometry(Math.min(w, d) * 0.47, Math.min(w, d) * 0.47, h, 28)
      case 'triangle': {
        const s = new THREE.Shape()
        s.moveTo(0, 0)
        s.lineTo(w, 0)
        s.lineTo(w / 2, h)
        s.closePath()
        const g = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false })
        g.translate(-w / 2, -h / 2, -d / 2)
        return g
      }
      case 'arch': {
        const r = Math.min(w * 0.3, h * 0.72)
        const s = new THREE.Shape()
        s.moveTo(0, 0)
        s.lineTo(w / 2 - r, 0)
        s.absarc(w / 2, 0, r, Math.PI, 0, true)
        s.lineTo(w, 0)
        s.lineTo(w, h)
        s.lineTo(0, h)
        s.closePath()
        const g = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false, curveSegments: 20 })
        g.translate(-w / 2, -h / 2, -d / 2)
        return g
      }
      default:
        return new THREE.BoxGeometry(w * 0.985, h * 0.985, d * 0.985)
    }
  }, [block.shape, w, h, d])
}

const easeOutBack = (p: number) => {
  const c1 = 1.5
  const c3 = c1 + 1
  return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2)
}

type BlockMeshProps = {
  block: Block
  delay: number
  animate: boolean
  highlight?: boolean
  ghost?: boolean
}

function BlockMesh({ block, delay, animate, highlight, ghost }: BlockMeshProps) {
  const geo = useBlockGeometry(block)
  const ref = useRef<THREE.Group>(null)
  const mat = useRef<THREE.MeshStandardMaterial>(null)
  const start = useRef<number | null>(null)
  const [w, h, d] = block.size
  const target = new THREE.Vector3(block.x + w / 2, block.y + h / 2, block.z + d / 2)

  useFrame(({ clock }) => {
    const g = ref.current
    if (!g) return
    if (start.current === null) start.current = clock.elapsedTime
    if (animate && !reduceMotion) {
      const t = clock.elapsedTime - start.current - delay
      const p = Math.min(Math.max(t / 0.55, 0), 1)
      const e = easeOutBack(p)
      g.position.set(target.x, target.y + (1 - e) * 5, target.z)
      g.visible = t > 0
      g.scale.setScalar(0.6 + 0.4 * Math.min(p * 2, 1))
    } else {
      g.position.copy(target)
      g.visible = true
      g.scale.setScalar(1)
    }
    if (mat.current) {
      mat.current.emissiveIntensity = highlight ? 0.45 + Math.sin(clock.elapsedTime * 5) * 0.3 : 0
    }
  })

  return (
    <group ref={ref} position={target}>
      <mesh geometry={geo} castShadow receiveShadow rotation={[0, turned(block) ? Math.PI / 2 : 0, 0]}>
        <meshStandardMaterial
          ref={mat}
          color={ghost ? '#ff2e93' : BLOCK_HEX[block.color]}
          roughness={0.42}
          metalness={0.02}
          emissive="#ff2e93"
          emissiveIntensity={0}
          transparent={ghost}
          opacity={ghost ? 0.08 : 1}
          wireframe={false}
        />
        <Edges threshold={20} color={ghost ? '#ff6fb5' : '#0a0a0b'} />
      </mesh>
    </group>
  )
}

/** Moves the camera from a flat front view (matches the 2D sketch) to a 3/4 view. */
function IntroCamera({ center, radius, delay }: { center: THREE.Vector3; radius: number; delay: number }) {
  const { camera } = useThree()
  const start = useRef<number | null>(null)
  useFrame(({ clock }) => {
    if (start.current === null) start.current = clock.elapsedTime
    const t = clock.elapsedTime - start.current
    const p = reduceMotion ? 1 : Math.min(Math.max((t - delay) / 1.6, 0), 1)
    const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2
    const orbit = reduceMotion ? 0 : Math.max(t - delay - 1.6, 0) * 0.15
    const ang = e * 0.75 + orbit
    const elev = 0.15 + e * 0.45
    const dist = radius * 3.1
    camera.position.set(
      center.x + Math.sin(ang) * dist * Math.cos(elev),
      center.y + Math.sin(elev) * dist,
      center.z + Math.cos(ang) * dist * Math.cos(elev),
    )
    camera.lookAt(center)
  })
  return null
}

export type BlockSceneProps = {
  blocks: Block[]
  animate?: boolean
  intro?: boolean
  introDelay?: number
  interactive?: boolean
  autoRotate?: boolean
  highlightId?: string
  ghostIds?: Set<string>
  stagger?: number
  className?: string
}

export function BlockScene({
  blocks,
  animate = true,
  intro = false,
  introDelay = 0,
  interactive = false,
  autoRotate = true,
  highlightId,
  ghostIds,
  stagger = 0.12,
  className,
}: BlockSceneProps) {
  const { center, radius, ordered } = useMemo(() => {
    const box = new THREE.Box3()
    for (const blk of blocks) {
      box.expandByPoint(new THREE.Vector3(blk.x, blk.y, blk.z))
      box.expandByPoint(new THREE.Vector3(blk.x + blk.size[0], blk.y + blk.size[1], blk.z + blk.size[2]))
    }
    const c = box.getCenter(new THREE.Vector3())
    const s = box.getSize(new THREE.Vector3())
    const ordered = [...blocks].sort((a, b) => a.y - b.y || a.x - b.x)
    return { center: c, radius: Math.max(s.x, s.y, s.z, 2), ordered }
  }, [blocks])

  return (
    <div className={className}>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ fov: 35, position: [center.x + radius * 2, center.y + radius * 1.6, center.z + radius * 2.6] }}
        gl={{ alpha: true, antialias: true }}
      >
        <hemisphereLight args={['#ffffff', '#2a0a1a', 0.9]} />
        <directionalLight position={[5, 10, 7]} intensity={1.6} castShadow shadow-mapSize={[1024, 1024]} />
        <pointLight position={[center.x - 4, center.y + 3, center.z - 4]} intensity={40} color="#ff2e93" />
        {ordered.map((blk, i) => (
          <BlockMesh
            key={blk.id}
            block={blk}
            delay={introDelay + i * stagger}
            animate={animate}
            highlight={blk.id === highlightId}
            ghost={ghostIds?.has(blk.id)}
          />
        ))}
        <ContactShadows position={[center.x, -0.001, center.z]} scale={radius * 4} opacity={0.55} blur={2.4} far={6} color="#000" />
        <gridHelper args={[radius * 6, Math.round(radius * 6), '#5a1638', '#1f1f24']} position={[center.x, -0.002, center.z]} />
        {intro ? (
          <IntroCamera center={center} radius={radius} delay={introDelay + ordered.length * stagger * 0.6} />
        ) : (
          <OrbitControls
            target={center}
            enablePan={false}
            enableZoom={interactive}
            enableRotate={interactive}
            autoRotate={autoRotate && !reduceMotion}
            autoRotateSpeed={0.8}
            minDistance={radius * 1.5}
            maxDistance={radius * 5}
            maxPolarAngle={Math.PI / 2.1}
          />
        )}
      </Canvas>
    </div>
  )
}
