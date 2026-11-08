import { useCallback, useEffect, useRef, useState } from 'react'

/*
 * Live speech recognition on the browser's Web Speech API: words stream in as
 * you talk instead of being uploaded after the fact. Chrome and Edge support it;
 * Safari partly; Firefox not at all, so `supported` decides whether the caller
 * uses this or the record-and-upload path.
 *
 * Nothing here acts on what it hears. It hands finished sentences to `onFinal`
 * and the caller decides - the confirm step for build changes stays where it is.
 */

// The Web Speech API is not in TypeScript's DOM lib, so declare the little we touch.
type SpeechAlt = { transcript: string }
type SpeechResult = { isFinal: boolean; 0: SpeechAlt }
type SpeechEvent = { resultIndex: number; results: { length: number } & Record<number, SpeechResult> }
type SpeechFail = { error: string }
type Recognizer = {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((e: SpeechEvent) => void) | null
  onerror: ((e: SpeechFail) => void) | null
  onend: (() => void) | null
}
// A cast, not a `declare global`: newer TS libs ship their own SpeechRecognition
// and a global augmentation would collide with it.
const recognizerCtor = () => {
  const w = window as unknown as { SpeechRecognition?: new () => Recognizer; webkitSpeechRecognition?: new () => Recognizer }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition
}

export type SpeechOptions = {
  /** One settled utterance. Called after a short quiet gap so one sentence arrives once. */
  onFinal?: (text: string) => void
  /** Five 0..1 mic bands every frame while listening, to keep the orb and bars moving. */
  onLevels?: (bands: number[]) => void
  /** Each time new words are heard (orb kick / haptic tap). */
  onWord?: () => void
  lang?: string
  /** Quiet after a final result before the utterance is handed over. */
  settleMs?: number
}

export type Speech = {
  /** False on Firefox and anywhere the API is missing: use the upload fallback. */
  supported: boolean
  listening: boolean
  /** Live partial text, cleared when the utterance settles. */
  interim: string
  /** Something the user can act on ("permission blocked"), else null. */
  error: string | null
  start: () => void
  /** Stops listening and hands over whatever was heard but not yet settled. */
  stop: () => void
}

const SILENT = [0, 0, 0, 0, 0]

/** Error codes the user can do nothing about, or that we caused ourselves. */
function reason(code: string): string | null {
  if (code === 'no-speech' || code === 'aborted') return null // normal: silence, or our own stop()
  if (code === 'not-allowed' || code === 'service-not-allowed')
    return 'Microphone access is blocked. Allow it in the browser, then try again.'
  if (code === 'audio-capture') return 'No microphone found.'
  if (code === 'network') return 'Speech recognition lost its connection.'
  return `Speech recognition failed (${code}).`
}

export function useSpeech(opts: SpeechOptions = {}): Speech {
  const supported = useRef(!!recognizerCtor()).current
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState<string | null>(null)

  const cb = useRef(opts)
  cb.current = opts
  const rec = useRef<Recognizer | null>(null)
  /** Whether the user still means to be listening: tells a session end from a stop. */
  const want = useRef(false)
  /** Final text heard since the last hand-over, plus the timer that hands it over. */
  const said = useRef('')
  const settle = useRef<number | null>(null)
  const retry = useRef<number | null>(null)
  /** When the current session started, and how many ended at once: stops a restart loop. */
  const began = useRef(0)
  const fast = useRef(0)
  // Mic meter, separate from recognition: the API gives words, not levels.
  const stream = useRef<MediaStream | null>(null)
  const audio = useRef<AudioContext | null>(null)
  const raf = useRef<number | null>(null)

  const clearTimers = () => {
    if (settle.current) window.clearTimeout(settle.current)
    if (retry.current) window.clearTimeout(retry.current)
    settle.current = null
    retry.current = null
  }

  const flush = useCallback(() => {
    const text = said.current.trim()
    said.current = ''
    setInterim('')
    if (text) cb.current.onFinal?.(text)
  }, [])

  const stopMeter = useCallback(() => {
    if (raf.current) cancelAnimationFrame(raf.current)
    raf.current = null
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    audio.current?.close()
    audio.current = null
    cb.current.onLevels?.(SILENT)
  }, [])

  /** Best effort: no levels is a duller orb, not a broken mic. */
  const startMeter = useCallback(async () => {
    if (!cb.current.onLevels || !navigator.mediaDevices?.getUserMedia) return
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!want.current) return s.getTracks().forEach((t) => t.stop())
      stream.current = s
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctx()
      audio.current = ctx
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 64
      ctx.createMediaStreamSource(s).connect(analyser)
      const data = new Uint8Array(analyser.frequencyBinCount)
      const step = Math.floor(data.length / 5)
      const tick = () => {
        analyser.getByteFrequencyData(data)
        cb.current.onLevels?.(
          Array.from({ length: 5 }, (_, b) => {
            let sum = 0
            for (let j = 0; j < step; j++) sum += data[b * step + j]
            return sum / step / 255
          }),
        )
        raf.current = requestAnimationFrame(tick)
      }
      tick()
    } catch {
      /* denied or busy: recognition will report it if it matters */
    }
  }, [])

  /** The one way listening ends well: release the mic, then hand over what was heard. */
  const finish = useCallback(() => {
    clearTimers()
    rec.current = null
    stopMeter()
    setListening(false)
    flush()
  }, [flush, stopMeter])

  const teardown = useCallback(() => {
    want.current = false
    clearTimers()
    const r = rec.current
    rec.current = null
    if (r) {
      r.onend = null // our own abort must not look like a silence timeout
      r.onresult = null
      r.onerror = null
      r.abort()
    }
    stopMeter()
    setListening(false)
    setInterim('')
  }, [stopMeter])

  const start = useCallback(() => {
    const Ctor = recognizerCtor()
    if (!Ctor || want.current) return
    want.current = true
    said.current = ''
    fast.current = 0
    setError(null)
    setInterim('')

    const r = new Ctor()
    r.continuous = true
    r.interimResults = true
    r.lang = cb.current.lang ?? 'en-US'

    r.onresult = (e) => {
      let live = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) said.current += (said.current ? ' ' : '') + res[0].transcript.trim()
        else live += res[0].transcript
      }
      cb.current.onWord?.()
      setInterim((said.current ? said.current + ' ' : '') + live.trim())
      // Chrome splits one sentence into several finals; wait for a gap so the
      // caller gets the whole utterance rather than three half commands.
      if (settle.current) window.clearTimeout(settle.current)
      if (said.current && !live.trim()) settle.current = window.setTimeout(flush, cb.current.settleMs ?? 900)
    }

    r.onerror = (e) => {
      const why = reason(e.error)
      if (!why) return // no-speech / aborted: onend decides whether to carry on
      setError(why)
      teardown()
    }

    r.onend = () => {
      if (!want.current) return finish()
      // Chrome ends the session after a few seconds of silence; restart it so the
      // user can keep talking. Sessions that end at once are a real fault
      // (no mic, background tab) and would spin forever, so give up on those.
      fast.current = Date.now() - began.current < 1000 ? fast.current + 1 : 0
      if (fast.current > 4) {
        setError('Speech recognition keeps dropping out. Try the mic button to record instead.')
        return teardown()
      }
      retry.current = window.setTimeout(() => {
        try {
          began.current = Date.now()
          r.start()
        } catch {
          /* already starting: the next onend will retry */
        }
      }, 250)
    }

    rec.current = r
    try {
      began.current = Date.now()
      r.start()
    } catch {
      // start() on a live recognizer throws; treat it as already listening.
    }
    setListening(true)
    void startMeter()
  }, [finish, startMeter, teardown])

  const stop = useCallback(() => {
    if (!want.current) return
    clearTimers()
    want.current = false
    // stop(), not abort(): Chrome still delivers the last words, so the hand-over
    // waits for onend. The timer is there in case onend never comes.
    rec.current?.stop()
    retry.current = window.setTimeout(finish, 600)
  }, [finish])

  useEffect(() => teardown, [teardown])

  return { supported, listening, interim, error, start, stop }
}
