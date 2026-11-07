import * as React from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Sparkles, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AgentOrb } from '@/components/voice/VoiceKit'

/*
 * Expanding prompt input with voice (Web Speech API + mic visualizer), image attachments,
 * an option picker and a 3-step level toggle. Adapted from a shadcn-style component to the
 * Sketch2Stack tokens (black + hot pink) and Tailwind 3 (tailwindcss-animate).
 */

// ----------------------------------------------------------------------
// Transition physics
// ----------------------------------------------------------------------
const SPRING = 'cubic-bezier(0.175, 0.885, 0.32, 1.275)'
const SPRING_TRANSITION = `max-width 0.4s ${SPRING}, height 0.4s ${SPRING}`
const SMOOTH_HEIGHT_TRANSITION = `max-width 0.4s ${SPRING}, height 0.15s ease-out`

// ----------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------
interface Attachment {
  id: string
  file: File
  url: string
  name: string
  width?: number
  height?: number
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type SpeechRecognitionLike = any

// ----------------------------------------------------------------------
// Sub-components
// ----------------------------------------------------------------------
function MorphingText({ text }: { text: string }) {
  const [width, setWidth] = useState<number | 'auto'>('auto')
  const spanRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (spanRef.current) setWidth(spanRef.current.offsetWidth)
  }, [text])

  return (
    <span
      className="relative inline-flex items-center justify-center overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]"
      style={{ width }}
    >
      <span ref={spanRef} className="invisible whitespace-nowrap px-1">
        {text}
      </span>
      <span key={text} className="absolute inset-0 flex items-center justify-center whitespace-nowrap duration-300 animate-in fade-in zoom-in-95">
        {text}
      </span>
    </span>
  )
}

function ArrowUpIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M7 12V2M7 2L2.5 6.5M7 2L11.5 6.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function MicIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <rect x="5" y="1" width="4" height="7" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M2.75 6.5V7a4.25 4.25 0 0 0 8.5 0v-.5M7 11.25V13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" fill="currentColor" />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M7 2.5V11.5M2.5 7H11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="9" height="9" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2.5 2.5L11.5 11.5M11.5 2.5L2.5 11.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/** Three bars; how many are lit follows the level's position in the list. */
function DynamicBarsIcon({ index, count }: { index: number; count: number }) {
  const lit = Math.round(((index + 1) / count) * 3)
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <rect x="1.5" y="8" width="2.5" height="4.5" rx="1" fill="currentColor" className="transition-opacity duration-300" opacity={1} />
      <rect x="5.75" y="5" width="2.5" height="7.5" rx="1" fill="currentColor" className="transition-opacity duration-300" opacity={lit >= 2 ? 1 : 0.3} />
      <rect x="10" y="2" width="2.5" height="10.5" rx="1" fill="currentColor" className="transition-opacity duration-300" opacity={lit >= 3 ? 1 : 0.3} />
    </svg>
  )
}

// ----------------------------------------------------------------------
// Attachment thumbnail
// ----------------------------------------------------------------------
function AttachmentThumb({
  attachment,
  index,
  onRemove,
  onOpen,
}: {
  attachment: Attachment
  index: number
  onRemove: (id: string) => void
  onOpen: (attachment: Attachment, rect: DOMRect) => void
}) {
  const [isHovered, setIsHovered] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)

  return (
    <button
      ref={btnRef}
      type="button"
      onMouseDown={(e) => e.preventDefault()}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={(e) => {
        e.stopPropagation()
        if (btnRef.current) onOpen(attachment, btnRef.current.getBoundingClientRect())
      }}
      style={{ animationDelay: `${index * 35}ms`, animationFillMode: 'backwards' }}
      className={cn(
        'group relative size-12 shrink-0 overflow-hidden rounded-xl border border-line bg-surface outline-none',
        'transition-transform duration-200 ease-[cubic-bezier(0.175,0.885,0.32,1.275)] hover:scale-[1.04] active:scale-[0.96]',
        'duration-400 animate-in fade-in slide-in-from-top-3 zoom-in-90',
      )}
      aria-label={`Open preview of ${attachment.name}`}
    >
      <img src={attachment.url} alt={attachment.name} className="size-full object-cover" draggable={false} />
      <span className={cn('absolute inset-0 flex items-start justify-end bg-black/0 transition-colors duration-200', isHovered && 'bg-black/25')}>
        <span
          role="button"
          tabIndex={-1}
          onMouseDown={(e) => {
            e.preventDefault()
            e.stopPropagation()
          }}
          onClick={(e) => {
            e.stopPropagation()
            onRemove(attachment.id)
          }}
          className={cn(
            'm-1 flex size-4 items-center justify-center rounded-full bg-ink/90 text-fg/70 shadow-sm transition-all duration-200 ease-[cubic-bezier(0.175,0.885,0.32,1.275)] hover:scale-110 hover:bg-ink hover:text-fg',
            isHovered ? 'scale-100 opacity-100' : 'pointer-events-none scale-50 opacity-0',
          )}
          aria-label={`Remove ${attachment.name}`}
        >
          <CloseIcon />
        </span>
      </span>
    </button>
  )
}

// ----------------------------------------------------------------------
// Shared-element gallery modal
// ----------------------------------------------------------------------
function AttachmentGalleryModal({ attachment, originRect, onClose }: { attachment: Attachment; originRect: DOMRect; onClose: () => void }) {
  const [phase, setPhase] = useState<'opening' | 'open' | 'closing'>('opening')
  const [targetRect, setTargetRect] = useState<{ top: number; left: number; width: number; height: number; radius: number } | null>(null)

  useEffect(() => {
    const maxW = Math.min(window.innerWidth * 0.86, 560)
    const maxH = Math.min(window.innerHeight * 0.78, 720)
    const naturalW = attachment.width || 800
    const naturalH = attachment.height || 600
    const scale = Math.min(maxW / naturalW, maxH / naturalH, 1.6)
    const width = naturalW * scale
    const height = naturalH * scale
    setTargetRect({ top: (window.innerHeight - height) / 2, left: (window.innerWidth - width) / 2, width, height, radius: 20 })
    const raf = requestAnimationFrame(() => setPhase('open'))
    return () => cancelAnimationFrame(raf)
  }, [attachment])

  const handleClose = useCallback(() => setPhase('closing'), [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [handleClose])

  const isOpen = phase === 'open'
  const isClosing = phase === 'closing'
  const geometry =
    isOpen && targetRect ? targetRect : { top: originRect.top, left: originRect.left, width: originRect.width, height: originRect.height, radius: 12 }
  const easing = isClosing ? 'ease-out' : SPRING
  const dur = isClosing ? '0.3s' : '0.45s'
  const flip = ['top', 'left', 'width', 'height', 'border-radius'].map((p) => `${p} ${dur} ${easing}`).join(', ')

  return (
    <div className="fixed inset-0 z-[100]" onClick={handleClose} role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-ink/70 backdrop-blur-md transition-opacity duration-400" style={{ opacity: isOpen ? 1 : 0 }} />
      <div
        style={{
          position: 'fixed',
          top: geometry.top,
          left: geometry.left,
          width: geometry.width,
          height: geometry.height,
          borderRadius: geometry.radius,
          transition: flip,
          overflow: 'hidden',
          boxShadow: isOpen ? '0 24px 60px -12px rgb(0 0 0 / 0.5)' : 'none',
        }}
        className="bg-surface"
        onTransitionEnd={() => {
          if (phase === 'closing') onClose()
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <img src={attachment.url} alt={attachment.name} className="size-full object-cover" draggable={false} />
      </div>
      <button
        type="button"
        onClick={handleClose}
        style={{ opacity: isOpen ? 1 : 0, transform: isOpen ? 'scale(1)' : 'scale(0.7)' }}
        className={cn(
          'fixed right-4 top-4 flex size-9 items-center justify-center rounded-full bg-raised/90 text-fg/70 shadow-md backdrop-blur-sm',
          'transition-all duration-300 ease-[cubic-bezier(0.175,0.885,0.32,1.275)] hover:bg-raised hover:text-fg',
          !isOpen && 'pointer-events-none',
        )}
        aria-label="Close preview"
      >
        <span className="scale-150">
          <CloseIcon />
        </span>
      </button>
    </div>
  )
}

// ----------------------------------------------------------------------
// Main component
// ----------------------------------------------------------------------
export interface PromptInputProps {
  onSubmit?: (value: string, meta: { model: string; effort: string; attachments: File[] }) => void
  placeholder?: string
  className?: string
  /** Options for the left picker. Pass [] to hide it. */
  models?: string[]
  modelIcons?: Record<string, LucideIcon>
  /** Levels for the bars toggle. Pass [] to hide it. */
  efforts?: string[]
  defaultEffortIndex?: number
  defaultValue?: string
  value?: string
  onChange?: (value: string) => void
  maxAttachments?: number
  /** Allow image attachments (the + button). */
  allowAttachments?: boolean
  /** Clear the text after submit (off when the text is kept as a project field). */
  clearOnSubmit?: boolean
  /** Width when collapsed / expanded (px or any CSS length). */
  collapsedWidth?: number | string
  expandedWidth?: number | string
  /** Start expanded and never collapse (e.g. inside a chat panel). */
  alwaysExpanded?: boolean
  /** Text typed out when the mic or Speech API isn't available. */
  simulatedTranscript?: string
  /** Fires when voice recording starts/stops. */
  onRecordingChange?: (recording: boolean) => void
  /** Five 0..1 mic bands, every frame while recording. Write to a ref; don't set state. */
  onLevels?: (bands: number[]) => void
  /** Fires when the input opens or closes (e.g. to size a wrapper in step). */
  onExpandedChange?: (expanded: boolean) => void
  /** Show the small built-in level dots while recording. Off when a VoiceBars row is shown. */
  showLevels?: boolean
  /** Fires each time speech recognition hears a new word. */
  onWord?: () => void
  /** Bump this number to start voice input from outside (e.g. a launcher button). */
  startVoiceSignal?: number
}

export const PromptInput = React.forwardRef<HTMLDivElement, PromptInputProps>(
  (
    {
      onSubmit,
      placeholder = 'Ask anything',
      className,
      models = [],
      modelIcons = {},
      efforts = [],
      defaultEffortIndex = 1,
      defaultValue = '',
      value: controlledValue,
      onChange,
      maxAttachments = 6,
      allowAttachments = true,
      clearOnSubmit = true,
      collapsedWidth = 320,
      expandedWidth = 480,
      alwaysExpanded = false,
      simulatedTranscript = 'A small red house with a tall pink roof and an open doorway',
      onRecordingChange,
      onLevels,
      onExpandedChange,
      showLevels = true,
      onWord,
      startVoiceSignal = 0,
    },
    ref,
  ) => {
    const [expandedState, setExpanded] = useState(alwaysExpanded)
    const expanded = alwaysExpanded || expandedState
    const [isSmoothResize, setIsSmoothResize] = useState(false)
    const [localValue, setLocalValue] = useState(defaultValue)
    const [selectedModel, setSelectedModel] = useState(models[0] ?? '')
    const [effortIndex, setEffortIndex] = useState(Math.min(defaultEffortIndex, Math.max(efforts.length - 1, 0)))
    const [isModelSelectOpen, setIsModelSelectOpen] = useState(false)

    const [attachments, setAttachments] = useState<Attachment[]>([])
    const [activeAttachment, setActiveAttachment] = useState<{ attachment: Attachment; rect: DOMRect } | null>(null)

    // Voice
    const [isRecording, setIsRecording] = useState(false)
    const [audioData, setAudioData] = useState<number[]>(new Array(5).fill(0))
    const valueRef = useRef(controlledValue !== undefined ? controlledValue : localValue)
    const streamRef = useRef<MediaStream | null>(null)
    const audioContextRef = useRef<AudioContext | null>(null)
    const rafRef = useRef<number | null>(null)
    const recognitionRef = useRef<SpeechRecognitionLike>(null)
    const demoIntervalRef = useRef<number | null>(null)
    const demoTextIntervalRef = useRef<number | null>(null)

    const [hoverStyle, setHoverStyle] = useState({ opacity: 0, transform: 'translateY(0px) scale(0.95)', transition: 'none' })
    const [containerHeight, setContainerHeight] = useState(116)
    const [textareaHeight, setTextareaHeight] = useState(68)
    const [isScrolling, setIsScrolling] = useState(false)

    const isControlled = controlledValue !== undefined
    const value = isControlled ? controlledValue : localValue
    const hasValue = value.trim() !== '' || attachments.length > 0
    const hasAttachments = attachments.length > 0

    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const internalContainerRef = useRef<HTMLDivElement | null>(null)
    const topFadeRef = useRef<HTMLDivElement>(null)
    const bottomFadeRef = useRef<HTMLDivElement>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const cbRef = useRef({ onRecordingChange, onLevels, onExpandedChange, onWord })
    cbRef.current = { onRecordingChange, onLevels, onExpandedChange, onWord }
    // Drive the mini sphere inside the mic button.
    const micLevelRef = useRef(0)
    const micKickRef = useRef(0)
    const emitLevels = (bands: number[]) => {
      const avg = bands.reduce((a, x) => a + Math.max(0, x - 0.07), 0) / bands.length
      micLevelRef.current = Math.min(1, avg * 2.4)
      cbRef.current.onLevels?.(bands)
    }
    const emitWord = () => {
      micKickRef.current = 1
      cbRef.current.onWord?.()
    }

    // Stay clipped to the rounded shape while the spring runs; only let the
    // style menu overflow once the card has settled open.
    const [settled, setSettled] = useState(alwaysExpanded)
    useEffect(() => {
      cbRef.current.onExpandedChange?.(expanded)
      setSettled(false)
      if (!expanded) return
      const t = setTimeout(() => setSettled(true), 450)
      return () => clearTimeout(t)
    }, [expanded])
    const attachmentsRef = useRef<Attachment[]>([])
    attachmentsRef.current = attachments

    useEffect(() => {
      valueRef.current = value
    }, [value])

    const updateFades = () => {
      const el = textareaRef.current
      if (!el) return
      const { scrollTop, scrollHeight, clientHeight } = el
      if (topFadeRef.current) topFadeRef.current.style.opacity = Math.min(scrollTop / 20, 1).toString()
      if (bottomFadeRef.current) {
        const bottomScroll = scrollHeight - clientHeight - scrollTop
        bottomFadeRef.current.style.opacity = Math.min(Math.max(bottomScroll - 16, 0) / 10, 1).toString()
      }
    }

    const handleValueChange = useCallback(
      (val: string) => {
        setIsSmoothResize(true)
        if (!isControlled) setLocalValue(val)
        onChange?.(val)
      },
      [isControlled, onChange],
    )

    const expand = () => {
      setIsSmoothResize(false)
      setExpanded(true)
      textareaRef.current?.focus({ preventScroll: true })
    }

    // --- Voice recording ---
    const stopRecording = useCallback(() => {
      if (recognitionRef.current) {
        recognitionRef.current.onend = null
        recognitionRef.current.stop()
        recognitionRef.current = null
      }
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
      audioContextRef.current?.close()
      audioContextRef.current = null
      if (demoIntervalRef.current) window.clearInterval(demoIntervalRef.current)
      if (demoTextIntervalRef.current) window.clearInterval(demoTextIntervalRef.current)
      demoIntervalRef.current = null
      demoTextIntervalRef.current = null
      setIsRecording(false)
      setAudioData(new Array(5).fill(0))
      emitLevels(new Array(5).fill(0))
      cbRef.current.onRecordingChange?.(false)
    }, [])

    const startRecording = useCallback(async () => {
      setIsSmoothResize(false)
      setExpanded(true)

      let stream: MediaStream | null = null
      try {
        if (navigator.mediaDevices?.getUserMedia) stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch {
        console.warn('Microphone unavailable; using simulated voice input.')
      }

      setIsRecording(true)
      cbRef.current.onRecordingChange?.(true)

      const simulateText = () => {
        const words = simulatedTranscript.split(' ')
        let i = 0
        let current = valueRef.current
        demoTextIntervalRef.current = window.setInterval(() => {
          if (i < words.length) {
            current = (current ? current + ' ' : '') + words[i]
            handleValueChange(current)
            emitWord()
            i++
          } else {
            stopRecording()
          }
        }, 260)
      }

      if (stream) {
        streamRef.current = stream
        const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
        const audioCtx: AudioContext = new AudioCtx()
        audioContextRef.current = audioCtx
        const analyser = audioCtx.createAnalyser()
        analyser.fftSize = 64
        audioCtx.createMediaStreamSource(stream).connect(analyser)
        const data = new Uint8Array(analyser.frequencyBinCount)

        const tick = () => {
          analyser.getByteFrequencyData(data)
          const step = Math.floor(data.length / 5)
          const bands = Array.from({ length: 5 }, (_, b) => {
            let sum = 0
            for (let j = 0; j < step; j++) sum += data[b * step + j]
            return sum / step / 255
          })
          setAudioData(bands)
          emitLevels(bands)
          rafRef.current = requestAnimationFrame(tick)
        }
        tick()

        const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
        if (SR) {
          const recognition = new SR()
          recognition.continuous = true
          recognition.interimResults = true
          let baseline = valueRef.current
          let heardWords = 0
          recognition.onresult = (event: any) => {
            let interim = ''
            let final = ''
            for (let i = event.resultIndex; i < event.results.length; ++i) {
              if (event.results[i].isFinal) final += event.results[i][0].transcript
              else interim += event.results[i][0].transcript
            }
            if (final) baseline += (baseline ? ' ' : '') + final
            const text = (baseline + (interim ? ' ' + interim : '')).trim()
            const words = text ? text.split(/\s+/).length : 0
            if (words > heardWords) emitWord()
            heardWords = words
            handleValueChange(text)
          }
          recognition.onerror = (e: any) => {
            console.error('Speech recognition error', e)
            stopRecording()
          }
          recognition.onend = () => stopRecording()
          recognitionRef.current = recognition
          recognition.start()
        } else {
          simulateText()
        }
      } else {
        demoIntervalRef.current = window.setInterval(() => {
          const bands = Array.from({ length: 5 }, () => Math.random() * 0.8 + 0.1)
          setAudioData(bands)
          emitLevels(bands)
        }, 100)
        simulateText()
      }
    }, [handleValueChange, stopRecording, simulatedTranscript])

    const lastSignal = useRef(0)
    useEffect(() => {
      if (!startVoiceSignal || startVoiceSignal === lastSignal.current) return
      lastSignal.current = startVoiceSignal
      if (!isRecording) startRecording()
    }, [startVoiceSignal, isRecording, startRecording])

    useEffect(() => {
      if (isRecording && textareaRef.current) textareaRef.current.scrollTop = textareaRef.current.scrollHeight
    }, [value, isRecording])

    // Release the mic and object URLs on unmount only.
    useEffect(
      () => () => {
        stopRecording()
        attachmentsRef.current.forEach((a) => URL.revokeObjectURL(a.url))
      },
      [stopRecording],
    )

    useEffect(() => {
      if ((value.trim() !== '' || hasAttachments) && !expanded) {
        setIsSmoothResize(false)
        setExpanded(true)
      }
    }, [value, expanded, hasAttachments])

    useEffect(() => {
      if (expandedState && !isRecording) {
        const timer = setTimeout(() => {
          const el = textareaRef.current
          if (el) {
            el.focus()
            el.setSelectionRange(el.value.length, el.value.length)
          }
        }, 50)
        return () => clearTimeout(timer)
      }
    }, [expandedState, isRecording])

    // Textarea height follows the text only.
    useEffect(() => {
      const el = textareaRef.current
      if (!el) return
      const current = el.style.height
      el.style.transition = 'none'
      el.style.height = '0px'
      const scrollHeight = el.scrollHeight
      el.style.height = current
      void el.offsetHeight
      el.style.transition = ''
      const next = Math.max(68, Math.min(scrollHeight, 160))
      el.style.height = `${next}px`
      setTextareaHeight(next)
      setIsScrolling(scrollHeight > 160)
      setTimeout(updateFades, 0)
    }, [value, expanded])

    useEffect(() => {
      setContainerHeight(Math.max(116, textareaHeight + 48))
      setTimeout(updateFades, 0)
    }, [textareaHeight])

    useEffect(() => {
      if (!isModelSelectOpen) return
      const outside = (e: MouseEvent) => {
        if (internalContainerRef.current && !internalContainerRef.current.contains(e.target as Node)) setIsModelSelectOpen(false)
      }
      document.addEventListener('mousedown', outside)
      return () => document.removeEventListener('mousedown', outside)
    }, [isModelSelectOpen])

    const collapse = () => {
      setIsSmoothResize(false)
      setExpanded(false)
      setIsModelSelectOpen(false)
    }

    const handleBlur = (e: React.FocusEvent<HTMLDivElement>) => {
      if (internalContainerRef.current?.contains(e.relatedTarget as Node)) return
      if (value.trim() === '' && !hasAttachments && !isRecording) collapse()
    }

    const handleSubmit = () => {
      if (value.trim() === '' && !hasAttachments) return
      setIsSmoothResize(false)
      onSubmit?.(value, { model: selectedModel, effort: efforts[effortIndex] ?? '', attachments: attachments.map((a) => a.file) })
      if (clearOnSubmit) handleValueChange('')
      attachments.forEach((a) => URL.revokeObjectURL(a.url))
      setAttachments([])
      if (clearOnSubmit) setExpanded(false)
      setIsModelSelectOpen(false)
    }

    const cycleEffort = (e: React.MouseEvent) => {
      e.stopPropagation()
      setEffortIndex((p) => (p + 1) % efforts.length)
    }

    const openFileChooser = (e: React.MouseEvent) => {
      e.stopPropagation()
      fileInputRef.current?.click()
    }

    const addAttachment = (file: File, url: string, width: number, height: number) => {
      const id = `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`
      setAttachments((prev) => [...prev, { id, file, url, name: file.name, width, height }])
    }

    const handleFilesChosen = (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []).filter((f) => f.type.startsWith('image/'))
      e.target.value = ''
      if (!files.length) return
      const accepted = files.slice(0, Math.max(0, maxAttachments - attachments.length))
      if (!expanded) {
        setIsSmoothResize(false)
        setExpanded(true)
      } else setIsSmoothResize(true)
      for (const file of accepted) {
        const url = URL.createObjectURL(file)
        const img = new Image()
        img.onload = () => addAttachment(file, url, img.naturalWidth, img.naturalHeight)
        img.onerror = () => addAttachment(file, url, 800, 600)
        img.src = url
      }
    }

    const removeAttachment = (id: string) => {
      setIsSmoothResize(true)
      setAttachments((prev) => {
        const target = prev.find((a) => a.id === id)
        if (target) URL.revokeObjectURL(target.url)
        return prev.filter((a) => a.id !== id)
      })
    }

    const showArrow = hasValue && !isRecording
    const showStop = isRecording
    const showMic = !hasValue && !isRecording

    const onActionButtonClick = (e: React.MouseEvent) => {
      e.preventDefault()
      if (isRecording) stopRecording()
      else if (hasValue) handleSubmit()
      else startRecording()
    }

    const ModelGlyph = modelIcons[selectedModel] ?? Sparkles
    const len = (v: number | string) => (typeof v === 'number' ? `${v}px` : v)

    return (
      <>
        <div
          ref={(node) => {
            internalContainerRef.current = node
            if (typeof ref === 'function') ref(node)
            else if (ref) ref.current = node
          }}
          onBlur={handleBlur}
          className={cn('relative flex w-full flex-col', className)}
          style={{
            maxWidth: len(expanded ? expandedWidth : collapsedWidth),
            transition: isSmoothResize ? 'max-width 0.15s ease-out' : `max-width 0.4s ${SPRING}`,
          }}
        >
          <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFilesChosen} className="hidden" tabIndex={-1} aria-hidden="true" />

          {/* Attachment tab, slides up from behind the input */}
          <div
            aria-hidden={!hasAttachments}
            style={{
              height: hasAttachments && expanded ? 68 : 0,
              transition: isSmoothResize ? 'height 0.15s ease-out' : `height 0.4s ${SPRING}`,
            }}
            className="relative z-0 w-full overflow-hidden"
          >
            <div
              style={{
                position: 'absolute',
                bottom: -8,
                left: 20,
                right: 20,
                height: 68,
                transform: hasAttachments && expanded ? 'translateY(0)' : 'translateY(100%)',
                opacity: hasAttachments && expanded ? 1 : 0,
                transition: isSmoothResize ? 'transform 0.15s ease-out, opacity 0.15s ease-out' : `transform 0.4s ${SPRING}, opacity 0.3s ease-out`,
              }}
              className="prompt-scrollbar flex items-start gap-2 overflow-x-auto rounded-t-2xl border border-b-0 border-line bg-surface px-2 pb-1 pt-2"
            >
              {attachments.map((a, i) => (
                <AttachmentThumb key={a.id} attachment={a} index={i} onRemove={removeAttachment} onOpen={(att, rect) => setActiveAttachment({ attachment: att, rect })} />
              ))}
            </div>
          </div>

          {/* Main card */}
          <div
            onMouseDown={(e) => {
              if (expanded && e.target !== textareaRef.current && !isRecording) {
                e.preventDefault()
                textareaRef.current?.focus()
              }
            }}
            style={{
              borderRadius: 24,
              height: expanded ? containerHeight : 48,
              transition: isSmoothResize ? SMOOTH_HEIGHT_TRANSITION : SPRING_TRANSITION,
              overflow: expanded && settled ? 'visible' : 'hidden',
              // keeps children clipped to the curve on every engine during the spring
              clipPath: expanded && settled ? undefined : 'inset(0 round 24px)',
            }}
            className={cn(
              'ring-host relative z-10 w-full border border-line bg-raised shadow-sm transition-[border-color,box-shadow] hover:border-pink/30 focus-within:border-pink/20 focus-within:shadow-[0_0_24px_rgba(255,46,147,0.12)]',
              expanded ? 'cursor-text' : 'cursor-default',
            )}
          >
            {/* pink arc that travels around the edge on focus, faster while recording */}
            <span className="ring-travel z-[11]" data-on={isRecording} aria-hidden />
            <style
              dangerouslySetInnerHTML={{
                __html: `
              .prompt-scrollbar::-webkit-scrollbar { width: 4px; height: 4px; background: transparent; }
              .prompt-scrollbar::-webkit-scrollbar-track { background: transparent; }
              .prompt-scrollbar::-webkit-scrollbar-thumb { background: transparent; border-radius: 4px; }
              .prompt-scrollbar:hover::-webkit-scrollbar-thumb { background: rgb(var(--muted-rgb) / 0.3); }
            `,
              }}
            />

            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => handleValueChange(e.target.value)}
              onScroll={updateFades}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSubmit()
                }
                if (e.key === 'Escape' && value.trim() === '' && !hasAttachments && !alwaysExpanded) {
                  e.stopPropagation()
                  collapse()
                }
              }}
              placeholder={placeholder}
              aria-label="Prompt"
              disabled={isRecording}
              style={{
                transition: isSmoothResize ? 'height 0.15s ease-out' : `opacity 0.3s ease-out, transform 0.3s ease-out, height 0.4s ${SPRING}`,
              }}
              className={cn(
                'prompt-scrollbar absolute inset-x-0 top-0 z-[1] w-full cursor-text resize-none bg-transparent py-3.5 pl-4 pr-12 text-sm leading-[22px] text-fg outline-none placeholder:font-medium placeholder:text-muted/80',
                expanded ? 'translate-y-0 scale-100 opacity-100' : 'pointer-events-none -translate-y-1 scale-95 opacity-0',
                isScrolling ? 'overflow-y-auto' : 'overflow-y-hidden',
                isRecording && 'pointer-events-none',
              )}
            />

            <div ref={topFadeRef} className="pointer-events-none absolute left-4 right-12 top-0 z-[2] h-8 bg-gradient-to-b from-raised via-raised/90 to-transparent" style={{ opacity: 0 }} />
            <div
              ref={bottomFadeRef}
              className="pointer-events-none absolute left-4 right-12 z-[2] h-8 bg-gradient-to-t from-raised via-raised/90 to-transparent"
              style={{ opacity: 0, top: `${textareaHeight - 32}px`, transition: isSmoothResize ? 'top 0.15s ease-out' : `top 0.4s ${SPRING}` }}
            />

            {/* Collapsed face */}
            <button
              type="button"
              onClick={expand}
              style={{ transition: isSmoothResize ? 'none' : `all 0.4s ${SPRING}` }}
              className={cn(
                'absolute inset-x-0 top-0 z-[1] cursor-text truncate py-[15px] pl-4 pr-12 text-left text-sm font-medium leading-[17px] text-muted/80 outline-none',
                !expanded ? 'translate-y-0 scale-100 opacity-100' : 'pointer-events-none translate-y-1 scale-105 opacity-0',
              )}
              aria-label="Open prompt input"
              tabIndex={expanded ? -1 : 0}
            >
              {placeholder}
            </button>

            {/* Bottom controls (hidden while recording) */}
            <div
              className={cn(
                'absolute bottom-2 left-3 right-12 z-[10] flex items-center gap-0 transition-all duration-300 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]',
                expanded && !isRecording ? 'pointer-events-auto translate-y-0 opacity-100 blur-none' : 'pointer-events-none translate-y-2 opacity-0 blur-sm',
              )}
            >
              {models.length > 0 && (
                <div className="relative">
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.stopPropagation()
                      setIsModelSelectOpen((p) => !p)
                    }}
                    className={cn(
                      'group flex cursor-default items-center gap-1 rounded-full px-2 py-1 text-fg/50 outline-none transition-all duration-200 hover:bg-pink-dim hover:text-fg',
                      isModelSelectOpen && 'bg-pink-dim text-fg',
                    )}
                    aria-label={`Select style. Current: ${selectedModel}`}
                  >
                    <ModelGlyph size={14} className="text-pink opacity-80 transition-opacity group-hover:opacity-100" />
                    <span className="select-none text-xs font-semibold transition-colors">
                      <MorphingText text={selectedModel} />
                    </span>
                  </button>

                  <div
                    style={{ transformOrigin: 'bottom left' }}
                    onMouseLeave={() =>
                      setHoverStyle((p) => ({ ...p, opacity: 0, transform: p.transform.replace('scale(1)', 'scale(0.95)'), transition: 'opacity 0.2s ease-in, transform 0.2s ease-out' }))
                    }
                    className={cn(
                      'absolute bottom-full left-0 z-50 mb-2.5 flex w-44 cursor-default flex-col gap-0.5 rounded-2xl border border-line bg-raised/95 p-1 shadow-xl backdrop-blur-md transition-all duration-400',
                      isModelSelectOpen
                        ? 'pointer-events-auto translate-y-0 scale-100 opacity-100 ease-[cubic-bezier(0.34,1.56,0.64,1)]'
                        : 'pointer-events-none translate-y-3 scale-95 opacity-0 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]',
                    )}
                  >
                    <div className="relative flex flex-col gap-0.5">
                      <div style={hoverStyle} className="pointer-events-none absolute left-0 right-0 top-0 -z-10 h-8 rounded-xl bg-pink-dim" />
                      {models.map((m, idx) => {
                        const Icon = modelIcons[m] ?? Sparkles
                        return (
                          <button
                            key={m}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onMouseEnter={() =>
                              setHoverStyle((p) => ({
                                opacity: 1,
                                transform: `translateY(${idx * 34}px) scale(1)`,
                                transition: p.opacity === 0 ? 'opacity 0.15s ease-out' : `transform 0.3s ${SPRING}, opacity 0.15s ease`,
                              }))
                            }
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedModel(m)
                              setIsModelSelectOpen(false)
                            }}
                            className={cn(
                              'group relative flex h-8 w-full cursor-default items-center justify-between rounded-xl px-2.5 py-1.5 text-left text-xs font-medium outline-none active:scale-[0.98]',
                              m === selectedModel ? 'text-pink-soft' : 'text-fg/80',
                            )}
                          >
                            <span className="flex items-center gap-2">
                              <Icon size={14} className="opacity-85 transition-opacity group-hover:opacity-100" />
                              {m}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}

              {efforts.length > 0 && (
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={cycleEffort}
                  className="group flex cursor-default items-center gap-1 rounded-full px-2 py-1 text-fg/50 outline-none transition-all duration-200 hover:bg-pink-dim hover:text-fg"
                  aria-label={`Detail: ${efforts[effortIndex]}. Click to change.`}
                >
                  <DynamicBarsIcon index={effortIndex} count={efforts.length} />
                  <span className="select-none text-xs font-semibold transition-colors">
                    <MorphingText text={efforts[effortIndex]} />
                  </span>
                </button>
              )}

              {allowAttachments && (
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={openFileChooser}
                  disabled={attachments.length >= maxAttachments}
                  className="ml-auto flex size-7 cursor-default items-center justify-center rounded-full text-fg/50 outline-none transition-all duration-200 hover:bg-pink-dim hover:text-fg disabled:pointer-events-none disabled:opacity-40"
                  aria-label="Attach an image"
                  title="Attach a photo of a drawing"
                >
                  <PlusIcon />
                </button>
              )}
            </div>

            {/* Mic level bars, left of the action button */}
            <div
              className={cn(
                'absolute bottom-2 right-12 z-[10] flex h-8 items-center justify-end gap-[3px] transition-all duration-400 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]',
                isRecording && showLevels ? 'w-16 translate-x-0 opacity-100' : 'pointer-events-none w-0 translate-x-4 opacity-0',
              )}
            >
              {audioData.map((v, i) => (
                <div key={i} className="w-1 rounded-full bg-pink transition-[height] duration-75 ease-out" style={{ height: `${Math.max(4, v * 24)}px` }} />
              ))}
            </div>

            {/* Action: mic / send / stop. Outlined so it never reads as the pink Generate button. */}
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              onClick={onActionButtonClick}
              aria-label={showArrow ? 'Send' : showStop ? 'Stop recording' : 'Use voice input'}
              title={showArrow ? 'Send' : showStop ? 'Stop' : 'Speak'}
              style={{ borderRadius: 9999 }}
              className={cn(
                'absolute bottom-2 right-2 z-[10] flex h-8 w-8 cursor-default items-center justify-center border outline-none transition-all duration-300 focus-visible:ring-2 focus-visible:ring-pink',
                showStop ? 'border-pink bg-pink-dim text-pink shadow-glow' : 'border-pink/50 bg-ink text-pink hover:border-pink hover:bg-pink-dim',
              )}
            >
              <span className="relative flex h-full w-full items-center justify-center">

                <span className={cn('absolute inset-0 flex items-center justify-center transition-all duration-300 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]', showArrow ? 'rotate-0 scale-100 opacity-100 blur-none' : 'pointer-events-none rotate-45 scale-50 opacity-0 blur-[1px]')}>
                  <ArrowUpIcon />
                </span>
                <span className={cn('absolute inset-0 flex items-center justify-center transition-all duration-300 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]', showMic ? 'rotate-0 scale-100 opacity-100 blur-none' : 'pointer-events-none -rotate-45 scale-50 opacity-0 blur-[1px]')}>
                  <MicIcon />
                </span>
                <span className={cn('group/stop absolute inset-0 flex items-center justify-center transition-all duration-300 ease-[cubic-bezier(0.175,0.885,0.32,1.275)]', showStop ? 'rotate-0 scale-100 opacity-100 blur-none' : 'pointer-events-none rotate-45 scale-50 opacity-0 blur-[1px]')}>
                  {showStop && <AgentOrb levelRef={micLevelRef} kickRef={micKickRef} listening glow={false} className="h-7 w-7 transition-opacity group-hover/stop:opacity-30" />}
                  <span className="absolute opacity-0 transition-opacity group-hover/stop:opacity-100">
                    <StopIcon />
                  </span>
                </span>
              </span>
            </button>
          </div>
        </div>

        {activeAttachment && <AttachmentGalleryModal attachment={activeAttachment.attachment} originRect={activeAttachment.rect} onClose={() => setActiveAttachment(null)} />}
      </>
    )
  },
)

PromptInput.displayName = 'PromptInput'
