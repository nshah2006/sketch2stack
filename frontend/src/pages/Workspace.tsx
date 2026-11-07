import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FolderClock } from 'lucide-react'
import type { Build, Project, Run, Stage, Stroke } from '../types'
import { useProjects } from '../store/projects'
import { load as loadStored, save as saveStored } from '../store/storage'
import { api, ApiError } from '../api'
import { useBackend } from '../backend'
import { useAuth } from '../auth/AuthContext'
import { useToast } from '../components/Toast'
import { BottomNav, LeftRail, Stepper, type NavTarget } from '../components/layout/Nav'
import { ProjectsDrawer, type ProjectAction } from '../components/layout/ProjectsDrawer'
import { ProfileMenu } from '../components/layout/ProfileMenu'
import { LabsModal } from '../components/layout/LabsModal'
import { SketchStage } from '../components/sketch/SketchStage'
import { GeneratingScreen } from '../components/anim/GeneratingScreen'
import { ChooseStage } from '../components/build/ChooseStage'
import { LiveStage } from '../components/live/LiveStage'

const wide = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 1280px)').matches
const RUN_KEY = 's2s.run'

export function Workspace() {
  const { upsert } = useProjects()
  const { serverId } = useBackend()
  const { user } = useAuth()
  // A run is "mine" if I started it (older servers send no owner: treat as shared).
  const isMine = (owner?: string | null) => !owner || owner === user?.email
  const toast = useToast()
  const [stage, setStageRaw] = useState<Stage>('sketch')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [name, setName] = useState('Untitled sketch')
  const [strokes, setStrokes] = useState<Stroke[]>([])
  const [fitStrip, setFitStrip] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [builds, setBuilds] = useState<Build[]>([])
  const [buildIdx, setBuildIdx] = useState(0)
  const [animDone, setAnimDone] = useState(false)
  const [run, setRunRaw] = useState<Run | null>(() => loadStored<Run | null>(RUN_KEY, null))
  const [starting, setStarting] = useState(false)
  const [drawer, setDrawer] = useState(wide)
  const [talk, setTalk] = useState(false)
  const [labs, setLabs] = useState(false)

  // Refs hold the latest values for async work, so a late answer never writes
  // into the wrong project or jumps to a stage the user already left.
  const pid = useRef<string | null>(null)
  const genSeq = useRef(0)
  const stageRef = useRef<Stage>('sketch')

  const setStage = (s: Stage) => {
    if (stageRef.current === 'generating' && s !== 'generating') genSeq.current++ // cancel pending generation
    stageRef.current = s
    setStageRaw(s)
  }
  const setRun = (r: Run | null) => {
    setRunRaw(r)
    saveStored(RUN_KEY, r)
  }

  // Sync with the server whenever we (re)connect: forget runs from an older server,
  // and adopt the build the arm is running right now (e.g. started from another tab).
  const adoptServerRun = async () => {
    try {
      const cur = await api.currentRun()
      if (cur.busy && cur.build && isMine(cur.owner)) {
        setRun({ runId: cur.run_id, serverId: cur.server_id, build: cur.build, startedAt: Date.now(), projectId: null })
        return true
      }
    } catch {
      /* offline: keep what we have */
    }
    return false
  }
  useEffect(() => {
    if (!serverId) return
    if (run && run.serverId !== serverId) setRun(null)
    api
      .currentRun()
      .then((cur) => {
        if (!cur.busy || !cur.build || !isMine(cur.owner)) return
        if (!run || run.runId !== cur.run_id || run.serverId !== cur.server_id)
          setRun({ runId: cur.run_id, serverId: cur.server_id, build: cur.build, startedAt: Date.now(), projectId: null })
        if (stageRef.current === 'sketch') setStage('live') // page reloaded mid-build: go straight back to it
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId])

  // Existing project: write only the given fields (render-time name/strokes may be stale here).
  const persist = (patch: Partial<Project>) => {
    const p = pid.current ? upsert({ id: pid.current, ...patch }) : upsert({ name, strokes, prompt, ...patch })
    pid.current = p.id
    setProjectId(p.id)
    return p.id
  }

  const generate = async (src: { strokes: Stroke[]; prompt: string } = { strokes, prompt }) => {
    if (!src.strokes.length && !src.prompt.trim()) {
      toast('Draw something (or describe it) first.')
      return
    }
    const mine = ++genSeq.current
    setBuilds([])
    setBuildIdx(0)
    setAnimDone(false)
    persist({ strokes: src.strokes, prompt: src.prompt })
    stageRef.current = 'generating'
    setStageRaw('generating')
    try {
      const res = await api.generate(src.strokes, src.prompt, mine, fitStrip)
      if (mine !== genSeq.current || res.request_id !== mine) return // a newer request or the user moved on
      if (!res.builds.length) {
        toast("Couldn't turn that sketch into blocks. Try bolder, closed shapes.")
        setStage('sketch')
        return
      }
      setBuilds(res.builds)
      persist({ builds: res.builds, buildIds: res.builds.map((b) => b.id), selectedBuild: 0, status: 'generated' })
    } catch (e) {
      if (mine !== genSeq.current) return
      toast((e as Error).message)
      setStage('sketch')
    }
  }

  // Typed (later spoken) request -> a build on the choose screen. Never starts the robot.
  // Shares genSeq with generate(), so only the newest request of either kind is applied.
  const dictate = async (text: string): Promise<string> => {
    if (stageRef.current === 'live') return 'The arm is building right now. Stop it or wait until it finishes first.'
    const mine = ++genSeq.current
    try {
      const cur = stageRef.current === 'choose' ? (builds[buildIdx] ?? null) : null
      const res = await api.dictate(text, cur, mine)
      if (mine !== genSeq.current || res.request_id !== mine) return ''
      if (res.builds.length) {
        setBuilds(res.builds)
        setBuildIdx(0)
        setAnimDone(true)
        persist({ prompt: text, builds: res.builds, buildIds: res.builds.map((b) => b.id), selectedBuild: 0, status: 'generated' })
        setStage('choose')
      }
      return res.reply
    } catch (e) {
      return (e as Error).message
    }
  }

  // Leave the generating screen when the animation finished AND the builds arrived
  // (or 6 s after they arrived, so a slow/stalled animation can't trap the user).
  useEffect(() => {
    if (stage !== 'generating' || !builds.length) return
    if (animDone) {
      setStage('choose')
      return
    }
    const t = setTimeout(() => stageRef.current === 'generating' && setStage('choose'), 6000)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage, animDone, builds.length])

  const doneAnim = useCallback(() => setAnimDone(true), [])

  const startingRef = useRef(false) // a ref, so a fast double-click can't slip past before re-render
  const startBuild = async (build: Build) => {
    if (startingRef.current) return
    startingRef.current = true
    setStarting(true)
    try {
      const res = await api.build(build, user?.email)
      setRun({ runId: res.run_id, serverId: res.server_id, build, startedAt: Date.now(), projectId: pid.current })
      setStage('live')
      setTalk(true) // the arm agent opens at the bottom of Build live
    } catch (e) {
      const err = e as ApiError
      if (err.status === 409 && /already building/.test(err.message)) {
        if (await adoptServerRun()) {
          toast('The arm is still working on another build. Showing it.')
          setStage('live')
        } else toast('The arm is busy with someone else’s build. Try again when it finishes.')
      } else toast(err.message)
    } finally {
      startingRef.current = false
      setStarting(false)
    }
  }

  const doneBuilding = useCallback(
    (r: Run) => {
      if (r.projectId) upsert({ id: r.projectId, status: 'built' })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  const load = (p: Project) => {
    genSeq.current++
    pid.current = p.id
    setProjectId(p.id)
    setName(p.name)
    setStrokes(p.strokes)
    setPrompt(p.prompt)
    setBuilds(p.builds ?? [])
    setBuildIdx(Math.min(p.selectedBuild, Math.max(0, (p.builds?.length ?? 1) - 1)))
  }

  const onProject = (p: Project, a: ProjectAction) => {
    load(p)
    if (!wide()) setDrawer(false)
    if (a === 'edit') setStage('sketch')
    else if (a === 'open') setStage(p.builds?.length ? 'choose' : 'sketch')
    else generate({ strokes: p.strokes, prompt: p.prompt })
  }

  const newProject = () => {
    genSeq.current++
    pid.current = null
    setProjectId(null)
    setName('Untitled sketch')
    setStrokes([])
    setPrompt('')
    setBuilds([])
    setBuildIdx(0)
    setStage('sketch')
    if (!wide()) setDrawer(false)
  }

  const onNav = (t: NavTarget) => {
    if (t === 'talk') {
      // The agent drives the arm, so it lives in the build phase.
      if (!run) return toast('Talk is for the build phase. Start a build first.')
      if (stage !== 'live') {
        setStage('live')
        setTalk(true)
      } else setTalk((x) => !x)
    }
    else if (t === 'labs') setLabs(true)
    else setStage(t)
  }

  const preview = useMemo(() => builds[0]?.blocks, [builds])

  return (
    <div className="flex h-full overflow-hidden">
      <LeftRail canTalk={!!run} talkOpen={talk && stage === 'live'} stage={stage} hasBuilds={builds.length > 0 || !!run} onNav={onNav} />

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
                    if (pid.current) upsert({ id: pid.current, name: n })
                  }}
                  onStrokes={(s) => {
                    setStrokes(s)
                    if (pid.current) upsert({ id: pid.current, strokes: s })
                  }}
                  onPrompt={setPrompt}
                  onGenerate={() => {
                    // Empty board + a description: let the dictation backend build it from words.
                    if (!strokes.some((st) => !st.erase) && prompt.trim()) dictate(prompt).then((r) => r && toast(r))
                    else generate()
                  }}
                  fitStrip={fitStrip}
                  onFitStrip={setFitStrip}
                />
              )}
              {stage === 'generating' && (
                <GeneratingScreen strokes={strokes} preview={preview} ready={builds.length > 0} onDone={doneAnim} />
              )}
              {stage === 'choose' && builds.length > 0 && (
                <ChooseStage
                  builds={builds}
                  index={Math.min(buildIdx, builds.length - 1)}
                  onIndex={(i) => {
                    setBuildIdx(i)
                    if (pid.current) upsert({ id: pid.current, selectedBuild: i })
                  }}
                  strokes={strokes}
                  prompt={prompt}
                  projectId={projectId ?? 'draft'}
                  onEditSketch={() => setStage('sketch')}
                  onRegenerate={() => generate()}
                  onBuild={() => startBuild(builds[Math.min(buildIdx, builds.length - 1)])}
                  starting={starting}
                />
              )}
              {stage === 'choose' && builds.length === 0 && (
                <div className="flex h-full flex-col items-center justify-center gap-3 text-muted">
                  No builds yet.
                  <button className="btn-pink" onClick={() => setStage('sketch')}>Back to sketch</button>
                </div>
              )}
              {stage === 'live' && (
                <LiveStage
                  run={run}
                  onBack={() => setStage(builds.length ? 'choose' : 'sketch')}
                  onDone={doneBuilding}
                  onRestart={(b) => startBuild(b)}
                  starting={starting}
                  agentOpen={talk}
                  onAgentOpen={setTalk}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <ProjectsDrawer open={drawer} onClose={() => setDrawer(false)} activeId={projectId} onAction={onProject} onNew={newProject} />
      <BottomNav canTalk={!!run} talkOpen={talk && stage === 'live'} stage={stage} hasBuilds={builds.length > 0 || !!run} onNav={onNav} />
      <LabsModal open={labs} onClose={() => setLabs(false)} />
    </div>
  )
}
