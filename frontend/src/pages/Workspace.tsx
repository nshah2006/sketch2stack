import { useCallback, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FolderClock } from 'lucide-react'
import type { Project, Stage, Stroke } from '../types'
import { useProjects } from '../store/projects'
import { BUILDS, buildById } from '../mocks/builds'
import { BottomNav, LeftRail, Stepper, type NavTarget } from '../components/layout/Nav'
import { ProjectsDrawer, type ProjectAction } from '../components/layout/ProjectsDrawer'
import { ProfileMenu } from '../components/layout/ProfileMenu'
import { LabsModal } from '../components/layout/LabsModal'
import { SketchStage } from '../components/sketch/SketchStage'
import { GeneratingScreen } from '../components/anim/GeneratingScreen'
import { ChooseStage } from '../components/build/ChooseStage'
import { LiveStage } from '../components/live/LiveStage'
import { TalkPanel } from '../components/talk/TalkPanel'

const wide = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 1280px)').matches

/** Mock "AI": every generate returns the same builds in a shuffled order. */
function mockGenerate(): string[] {
  const ids = BUILDS.map((b) => b.id)
  const k = Math.floor(Math.random() * ids.length)
  return [...ids.slice(k), ...ids.slice(0, k)]
}

export function Workspace() {
  const { upsert } = useProjects()
  const [stage, setStage] = useState<Stage>('sketch')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [name, setName] = useState('Untitled sketch')
  const [strokes, setStrokes] = useState<Stroke[]>([])
  const [prompt, setPrompt] = useState('')
  const [buildIds, setBuildIds] = useState<string[]>([])
  const [buildIdx, setBuildIdx] = useState(0)
  const [drawer, setDrawer] = useState(wide)
  const [talk, setTalk] = useState(false)
  const [labs, setLabs] = useState(false)

  const builds = useMemo(() => buildIds.map(buildById), [buildIds])

  const persist = (patch: Partial<Project>) => {
    const p = upsert({ id: projectId ?? undefined, name, strokes, prompt, buildIds, selectedBuild: buildIdx, ...patch })
    setProjectId(p.id)
    return p
  }

  const generate = () => {
    const ids = mockGenerate()
    setBuildIds(ids)
    setBuildIdx(0)
    persist({ buildIds: ids, selectedBuild: 0, status: 'generated' })
    setStage('generating')
  }

  const doneGenerating = useCallback(() => setStage('choose'), [])
  const doneBuilding = useCallback(() => {
    if (projectId) upsert({ id: projectId, status: 'built' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const load = (p: Project) => {
    setProjectId(p.id)
    setName(p.name)
    setStrokes(p.strokes)
    setPrompt(p.prompt)
    setBuildIds(p.buildIds)
    setBuildIdx(p.selectedBuild)
  }

  const onProject = (p: Project, a: ProjectAction) => {
    load(p)
    if (!wide()) setDrawer(false)
    if (a === 'edit') setStage('sketch')
    else if (a === 'open') setStage(p.buildIds.length ? 'choose' : 'sketch')
    else {
      const ids = mockGenerate()
      setBuildIds(ids)
      setBuildIdx(0)
      upsert({ id: p.id, buildIds: ids, selectedBuild: 0, status: 'generated' })
      setStage('generating')
    }
  }

  const newProject = () => {
    setProjectId(null)
    setName('Untitled sketch')
    setStrokes([])
    setPrompt('')
    setBuildIds([])
    setBuildIdx(0)
    setStage('sketch')
    if (!wide()) setDrawer(false)
  }

  const onNav = (t: NavTarget) => {
    if (t === 'talk') setTalk((x) => !x)
    else if (t === 'labs') setLabs(true)
    else setStage(t)
  }

  return (
    <div className="flex h-full overflow-hidden">
      <LeftRail stage={stage} hasBuilds={builds.length > 0} onNav={onNav} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line px-4 lg:px-6">
          <Stepper stage={stage} />
          <div className="flex items-center gap-2">
            <button
              onClick={() => setDrawer((d) => !d)}
              className={`btn-ghost py-2 ${drawer ? '!border-pink/60 !text-pink-soft' : ''}`}
              aria-pressed={drawer}
            >
              <FolderClock size={16} />
              <span className="hidden sm:inline">Projects</span>
            </button>
            <div className="md:hidden">
              <ProfileMenu placement="below" />
            </div>
          </div>
        </header>

        <main className="relative min-h-0 flex-1 pb-16 md:pb-0">
          <AnimatePresence mode="wait">
            <motion.div
              key={stage}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6, transition: { duration: 0.12 } }}
              transition={{ type: 'spring', duration: 0.4, bounce: 0 }}
              className="h-full"
            >
              {stage === 'sketch' && (
                <SketchStage
                  strokes={strokes}
                  prompt={prompt}
                  projectName={name}
                  onRename={(n) => {
                    setName(n)
                    if (projectId) upsert({ id: projectId, name: n })
                  }}
                  onStrokes={(s) => {
                    setStrokes(s)
                    if (projectId) upsert({ id: projectId, strokes: s })
                  }}
                  onPrompt={setPrompt}
                  onGenerate={generate}
                />
              )}
              {stage === 'generating' && <GeneratingScreen strokes={strokes} onDone={doneGenerating} />}
              {stage === 'choose' && builds.length > 0 && (
                <ChooseStage
                  builds={builds}
                  index={buildIdx}
                  onIndex={(i) => {
                    setBuildIdx(i)
                    if (projectId) upsert({ id: projectId, selectedBuild: i })
                  }}
                  strokes={strokes}
                  prompt={prompt}
                  projectId={projectId ?? 'draft'}
                  onEditSketch={() => setStage('sketch')}
                  onRegenerate={generate}
                  onBuild={() => setStage('live')}
                />
              )}
              {stage === 'live' && builds.length > 0 && <LiveStage build={builds[buildIdx]} onBack={() => setStage('choose')} onDone={doneBuilding} />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <ProjectsDrawer open={drawer} onClose={() => setDrawer(false)} activeId={projectId} onAction={onProject} onNew={newProject} />
      <BottomNav stage={stage} hasBuilds={builds.length > 0} onNav={onNav} />
      <TalkPanel open={talk} onOpenChange={setTalk} />
      <LabsModal open={labs} onClose={() => setLabs(false)} />
    </div>
  )
}
