import { useEffect, useRef, useState } from 'react'
import './App.css'
import { SpeechInput } from './SpeechInput'

type ServiceState = 'checking' | 'online' | 'offline'
type Stage = 'idle' | 'thinking' | 'rendering' | 'ready' | 'speaking' | 'error'
type Role = 'user' | 'assistant'

interface Message {
  id: string
  role: Role
  text: string
  time: string
  emotion?: string
  sources?: RAGSource[]
}

interface RAGSource {
  page_number: number
  chapter_title: string
  score: number
  snippet: string
}

interface RAGStatus {
  import_id: string
  indexed: boolean
  backend: string
  embedding_model?: string | null
  embedding_dimension?: number | null
  embedding_error?: string
  embedding_configured?: boolean
  semantic_indexed?: boolean
  embedding_stale?: boolean
  total_pages?: number
  text_pages?: number
  chunk_count?: number
  indexed_at?: string
}

interface ConversationSummary {
  thread_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

interface ConversationDetail {
  thread_id: string
  title: string
  lesson_id: string
  created_at: string
  updated_at: string
  teaching_state: TeachingState | null
  messages: Array<{
    id: number
    role: Role
    text: string
    emotion?: string | null
    created_at: string
  }>
}

interface CourseOption {
  lesson_id: string
  title: string
  mode: 'guided' | 'interactive'
  built_in: boolean
  section_total: number
  published_at?: string
}

interface TeachingState {
  lesson_phase: string
  concept_index: number
  attempt_count: number
  score: number
  current_question: string
  lesson_mode: 'chat' | 'interactive' | 'guided' | 'dynamic'
  section_total: number
  checkpoint_choices: string[]
  dynamic_topic?: string
  dynamic_section_index?: number
}

type LessonAction = 'user' | 'start' | 'advance' | 'answer' | 'question'
  | 'dynamic_start' | 'dynamic_advance' | 'dynamic_stop'
type PendingTurnKind = 'user' | 'auto'
type CourseBuilderView = 'library' | 'editor'

interface VideoJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  video_url: string | null
  elapsed_seconds: number
  queue_wait_seconds?: number | null
  total_elapsed_seconds?: number | null
  error: string
}

interface ChatResult {
  thread_id: string
  reply_text: string
  emotion: string
  speech_rate: number
  teaching_state: TeachingState | null
  video_job: VideoJob | null
  media_segments: MediaSegment[]
  timings?: PipelineTimings
  media_error?: string | null
  sources?: RAGSource[]
  retrieval?: {
    used: boolean
    indexed: boolean
    backend: string
    import_id: string
  } | null
}

interface MediaSegment {
  index: number
  text: string
  characters: number
  over_soft_limit: boolean
  video_job: VideoJob | null
  video_url?: string | null
  cache_hit?: boolean
  audio_duration_seconds?: number
}

interface PipelineTimings {
  graph_ms?: number
  tts_ms?: number
  float_submit_ms?: number
  request_ms?: number
  client_roundtrip_ms?: number
  audio_seconds?: number
  float_seconds?: number
  float_queue_seconds?: number
  float_total_seconds?: number
  browser_buffer_ms?: number
  segment_count?: number
  cache_hits?: number
}

interface MediaRetryPayload {
  text: string
  emotion: string
  speechRate: number
}

interface CourseImportPreview {
  filename: string
  file_size_bytes: number
  total_pages: number
  start_page: number
  end_page: number
  preview_page_count: number
  text_layer_pages: number
  skipped_pages: number[]
  ocr_used: boolean
  sections: Array<{ level: number; title: string; page_number: number }>
  pages: Array<{
    page_number: number
    character_count: number
    has_text_layer: boolean
    headings: Array<{ level: number; title: string; page_number: number }>
    text: string
  }>
  import_id?: string
  chapter?: CourseChapter
  generation_plan?: {
    batch_count: number
    page_counts: number[]
    character_counts: number[]
    lesson_counts: number[]
    effective_lesson_count: number
    recommended_lesson_count: number
    detected_sections: Array<{ level: number; title: string; page_number: number }>
    estimated_model_calls: number
  }
}

interface CourseChapter {
  chapter_index: number
  title: string
  start_page: number
  end_page: number
  page_count: number
  source: 'pdf_bookmark' | 'text_heading' | 'numbered_heading' | 'page_window' | 'manual' | 'whole_document_fallback'
}

interface CourseImportRecord {
  import_id: string
  filename: string
  file_size_bytes: number
  total_pages: number
  chapter_detection: 'pdf_bookmark' | 'text_heading' | 'numbered_heading' | 'page_window' | 'manual' | 'fallback'
  structure_warning?: string
  chapters: CourseChapter[]
  ocr_used: boolean
  requires_ocr?: boolean
  scanned_text_layer_pages?: number | null
  stored_locally: boolean
  chapter_drafts: Array<{
    chapter_index: number
    title: string
    lesson_count: number
    saved_at: string
    stale?: boolean
  }>
  chapter_publications: Array<{
    chapter_index: number
    lesson_id: string
    title: string
    published_at: string
  }>
}

interface CourseProject {
  import_id: string
  filename: string
  chapter_index: number
  chapter_title: string
  course_title: string
  lesson_count: number
  draft_saved_at: string
  draft_stale: boolean
  published: boolean
  lesson_id: string
  published_at: string
}

interface CourseBlueprint {
  course_title: string
  course_description: string
  audience: string
  total_minutes: number
  learning_objectives: string[]
  status: 'draft' | 'published'
  quality_status?: 'valid' | 'auto_fixed' | 'needs_fix'
  validation_issues?: Array<{
    path: string
    message: string
    lesson_index: number | null
    block_index: number | null
  }>
  auto_fixes?: string[]
  grounding: {
    source_page_count: number
    source_pages: number[]
    page_references_validated: boolean
    human_review_required: boolean
    covered_pages?: number[]
    uncovered_pages?: number[]
    coverage_ratio?: number
  }
  generator: {
    provider: string
    model: string
    model_calls?: number
    batch_count?: number
  }
  review_notes: string[]
  draft?: {
    import_id: string
    chapter_index: number
    saved_at: string
    stored_locally: boolean
  }
  lessons: Array<{
    title: string
    objective: string
    estimated_minutes: number
    source_pages: number[]
    teaching_blocks: Array<{
      title: string
      script: string
      source_pages: number[]
    }>
    checkpoint: {
      question: string
      choices: string[]
      correct_answer: string
      explanation: string
      source_pages: number[]
    }
  }>
}

const stageCopy: Record<Stage, { label: string; hint: string }> = {
  idle: { label: '随时可以开始', hint: '输入问题，虚拟教师会结合学习记录回答' },
  thinking: { label: '正在组织讲解', hint: 'LangGraph 正在调用教学模型' },
  rendering: { label: '正在生成教师视频', hint: '语音已生成，FLOAT 正在渲染画面' },
  ready: { label: '讲解视频已就绪', hint: '点击画面开始播放' },
  speaking: { label: '教师正在讲解', hint: '播放结束后将自动返回待机状态' },
  error: { label: '本次请求未完成', hint: '查看提示后可以重新发送' },
}

const chapterDetectionLabel = (value: CourseImportRecord['chapter_detection']) => ({
  pdf_bookmark: 'PDF书签识别',
  text_heading: '正文章标题推断',
  numbered_heading: '编号标题推断',
  page_window: '固定页数分组',
  manual: '人工校正',
  fallback: '旧版全文回退',
}[value] || '本地结构识别')

const defaultCourseOptions: CourseOption[] = [
  { lesson_id: 'python-lecture', title: 'Python 变量 · 课程讲授', mode: 'guided', built_in: true, section_total: 3 },
  { lesson_id: 'python-basics', title: 'Python 变量 · 互动练习', mode: 'interactive', built_in: true, section_total: 3 },
]

const createId = () =>
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`

const now = () =>
  new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date())

const welcomeMessage = (mode: string): Message => ({
  id: createId(),
  role: 'assistant',
  text: mode === 'python-lecture'
    ? '已切换到课程讲授模式。点击“开始连续讲授”，老师会自动讲课并在两个检查点暂停。'
    : mode === 'python-basics'
      ? '已切换到互动练习模式。点击“开始互动练习”进入固定课程；答题过程中也可以随时向老师提问。'
      : mode === 'default'
        ? '新的学习会话已经开始。今天想学习什么？'
        : '已进入发布课程。点击“开始连续讲授”，老师会按照审核后的固定内容进行讲解。',
  time: now(),
  emotion: 'happy',
})

const conversationIdFromHash = () => {
  const match = window.location.hash.match(/^#\/chat\/([^/]+)$/)
  return match ? decodeURIComponent(match[1]) : null
}

const messageTime = (timestamp: string) => {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

const conversationTime = (timestamp: string) => {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

const getOrCreateUserId = () => {
  const existing = localStorage.getItem('virtual-teacher-user-id')
  if (existing) return existing
  const created = `web-${createId()}`
  localStorage.setItem('virtual-teacher-user-id', created)
  return created
}

async function responseError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string }
    return payload.detail || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

function App() {
  const [backend, setBackend] = useState<ServiceState>('checking')
  const [worker, setWorker] = useState<ServiceState>('checking')
  const [workerLabel, setWorkerLabel] = useState('检查中')
  const [stage, setStage] = useState<Stage>('idle')
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [lessonId, setLessonId] = useState('default')
  const [renderVideo, setRenderVideo] = useState(true)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [talkVideoVisible, setTalkVideoVisible] = useState(false)
  const [videoSegments, setVideoSegments] = useState<MediaSegment[]>([])
  const [activeSegmentIndex, setActiveSegmentIndex] = useState(0)
  const [idleVideoAvailable, setIdleVideoAvailable] = useState(true)
  const [currentJob, setCurrentJob] = useState<VideoJob | null>(null)
  const [teachingState, setTeachingState] = useState<TeachingState | null>(null)
  const [error, setError] = useState('')
  const [thinkingHint, setThinkingHint] = useState(stageCopy.thinking.hint)
  const [pendingStatus, setPendingStatus] = useState<'idle' | 'generating' | 'ready'>('idle')
  const [pendingKind, setPendingKind] = useState<PendingTurnKind | null>(null)
  const [submissionLocked, setSubmissionLocked] = useState(false)
  const [dynamicAutoRun, setDynamicAutoRun] = useState(false)
  const [messages, setMessages] = useState<Message[]>([welcomeMessage('default')])
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [pipelineTimings, setPipelineTimings] = useState<PipelineTimings | null>(null)
  const [mediaError, setMediaError] = useState('')
  const [mediaRetry, setMediaRetry] = useState<MediaRetryPayload | null>(null)
  const [showPerformance, setShowPerformance] = useState(false)
  const [showCourseImport, setShowCourseImport] = useState(false)
  const [showCourseManager, setShowCourseManager] = useState(false)
  const [courseProjects, setCourseProjects] = useState<CourseProject[]>([])
  const [courseManagerLoading, setCourseManagerLoading] = useState(false)
  const [courseManagerError, setCourseManagerError] = useState('')
  const [courseBuilderView, setCourseBuilderView] = useState<CourseBuilderView>('library')
  const [coursePdf, setCoursePdf] = useState<File | null>(null)
  const [courseStartPage, setCourseStartPage] = useState('1')
  const [courseEndPage, setCourseEndPage] = useState('6')
  const [courseImportLoading, setCourseImportLoading] = useState(false)
  const [courseImportError, setCourseImportError] = useState('')
  const [coursePreview, setCoursePreview] = useState<CourseImportPreview | null>(null)
  const [courseImportRecord, setCourseImportRecord] = useState<CourseImportRecord | null>(null)
  const [selectedChapterIndex, setSelectedChapterIndex] = useState<number | null>(null)
  const [courseUploadLoading, setCourseUploadLoading] = useState(false)
  const [courseAudience, setCourseAudience] = useState('人工智能方向本科生或研究生')
  const [courseLessonCount, setCourseLessonCount] = useState('2')
  const [courseTargetMinutes, setCourseTargetMinutes] = useState('30')
  const [courseDesignLoading, setCourseDesignLoading] = useState(false)
  const [courseDesignError, setCourseDesignError] = useState('')
  const [courseDesignNotice, setCourseDesignNotice] = useState('')
  const [courseBlueprint, setCourseBlueprint] = useState<CourseBlueprint | null>(null)
  const [courseOptions, setCourseOptions] = useState<CourseOption[]>(defaultCourseOptions)
  const [chapterEditMode, setChapterEditMode] = useState(false)
  const [chapterEdits, setChapterEdits] = useState<CourseChapter[]>([])
  const [chapterSaveLoading, setChapterSaveLoading] = useState(false)
  const [coursePublishLoading, setCoursePublishLoading] = useState(false)
  const [courseUnpublishLoading, setCourseUnpublishLoading] = useState(false)
  const [coursePublishNotice, setCoursePublishNotice] = useState('')
  const [ragStatus, setRagStatus] = useState<RAGStatus | null>(null)
  const [ragIndexLoading, setRagIndexLoading] = useState(false)
  const [speechBusy, setSpeechBusy] = useState(false)
  const speechBusyRef = useRef(false)

  const videoRef = useRef<HTMLVideoElement>(null)
  const messageEndRef = useRef<HTMLDivElement>(null)
  const mountedRef = useRef(true)
  const readyVideoUrlsRef = useRef(new Map<number, string>())
  const videoPollsRef = useRef(new Map<number, Promise<string>>())
  const preloadedVideosRef = useRef(new Map<number, HTMLVideoElement>())
  const pendingPreloadedVideosRef = useRef(new Map<number, HTMLVideoElement>())
  const healthCheckRunningRef = useRef(false)
  const workerHealthFailuresRef = useRef(0)
  const teachingStateRef = useRef<TeachingState | null>(null)
  const threadIdRef = useRef<string | null>(threadId)
  const lessonIdRef = useRef(lessonId)
  const busyRef = useRef(false)
  const inputRef = useRef('')
  const pendingTurnPromiseRef = useRef<Promise<ChatResult> | null>(null)
  const pendingTurnKindRef = useRef<PendingTurnKind | null>(null)
  const dynamicAutoRunRef = useRef(false)
  const completedFloatJobsRef = useRef(new Set<string>())
  const [userId] = useState(getOrCreateUserId)
  const busy = !['idle', 'error'].includes(stage) || speechBusy
  const videoEnabled = renderVideo && worker === 'online'
  const selectedCourse = courseOptions.find((course) => course.lesson_id === lessonId)
  const blueprintCoveredPages = courseBlueprint
    ? Array.from(new Set(courseBlueprint.lessons.flatMap((lesson) => [
        ...lesson.source_pages,
        ...lesson.teaching_blocks.flatMap((block) => block.source_pages),
        ...lesson.checkpoint.source_pages,
      ]))).sort((left, right) => left - right)
    : []
  const blueprintCoveragePercent = courseBlueprint
    ? Math.round(
        (blueprintCoveredPages.length / Math.max(1, courseBlueprint.grounding.source_pages.length)) * 100,
      )
    : 0
  const guidedLecture = selectedCourse?.mode === 'guided'
  const interactivePractice = selectedCourse?.mode === 'interactive'
  const dynamicLecture = teachingState?.lesson_mode === 'dynamic'
  const canSendNow = (!busy || stage === 'speaking')
    && !speechBusy
    && !submissionLocked
    && pendingStatus === 'idle'

  useEffect(() => {
    teachingStateRef.current = teachingState
  }, [teachingState])

  useEffect(() => {
    threadIdRef.current = threadId
  }, [threadId])

  useEffect(() => {
    lessonIdRef.current = lessonId
  }, [lessonId])

  useEffect(() => {
    busyRef.current = busy
  }, [busy])

  useEffect(() => {
    inputRef.current = input
  }, [input])

  useEffect(() => {
    dynamicAutoRunRef.current = dynamicAutoRun
  }, [dynamicAutoRun])

  const clearPreparedVideos = () => {
    preloadedVideosRef.current.forEach((video) => {
      video.pause()
      video.removeAttribute('src')
      video.load()
    })
    preloadedVideosRef.current.clear()
    readyVideoUrlsRef.current.clear()
    videoPollsRef.current.clear()
  }

  const clearPendingPreloads = () => {
    pendingPreloadedVideosRef.current.forEach((video) => {
      video.pause()
      video.removeAttribute('src')
      video.load()
    })
    pendingPreloadedVideosRef.current.clear()
  }

  const preloadVideo = (
    url: string,
    index: number,
    target: 'current' | 'pending' = 'current',
  ) => new Promise<number>((resolve, reject) => {
    const started = performance.now()
    const preloader = document.createElement('video')
    let settled = false
    const targetMap = target === 'pending'
      ? pendingPreloadedVideosRef.current
      : preloadedVideosRef.current
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      window.clearTimeout(timeout)
      preloader.removeEventListener('canplay', handleReady)
      preloader.removeEventListener('error', handleError)
      if (error) reject(error)
      else resolve(Number((performance.now() - started).toFixed(2)))
    }
    const handleReady = () => finish()
    const handleError = () => finish(new Error('浏览器无法预加载教师视频'))
    const timeout = window.setTimeout(
      () => finish(new Error('教师视频缓冲超时，请检查远程连接')),
      30000,
    )
    preloader.preload = 'auto'
    preloader.muted = true
    preloader.playsInline = true
    preloader.addEventListener('canplay', handleReady)
    preloader.addEventListener('error', handleError)
    preloader.src = url
    targetMap.set(index, preloader)
    preloader.load()
  })

  useEffect(() => {
    mountedRef.current = true
    const checkServices = async () => {
      if (healthCheckRunningRef.current) return
      healthCheckRunningRef.current = true
      try {
        const backendResponse = await fetch('/health')
        if (!backendResponse.ok) throw new Error()
        setBackend('online')
      } catch {
        setBackend('offline')
        setWorker('offline')
        setWorkerLabel('教学服务未启动')
        workerHealthFailuresRef.current = 3
        healthCheckRunningRef.current = false
        return
      }

      try {
        const workerResponse = await fetch('/health/float')
        if (!workerResponse.ok) throw new Error()
        const payload = (await workerResponse.json()) as { status?: string }
        workerHealthFailuresRef.current = 0
        setWorker(payload.status === 'ready' ? 'online' : 'checking')
        setWorkerLabel(
          payload.status === 'ready'
            ? '就绪'
            : payload.status === 'loading' ? '模型加载中' : payload.status === 'error' ? '模型错误' : '检查中',
        )
      } catch {
        workerHealthFailuresRef.current += 1
        // A tunneled HTTP connection can be reset while the SSH session and
        // Worker remain healthy. Avoid flashing offline after one bad poll.
        if (workerHealthFailuresRef.current >= 3) {
          setWorker('offline')
          setWorkerLabel('连接中断')
        }
      } finally {
        healthCheckRunningRef.current = false
      }
    }
    void checkServices()
    const healthTimer = window.setInterval(() => void checkServices(), 5000)
    return () => {
      mountedRef.current = false
      window.clearInterval(healthTimer)
      clearPreparedVideos()
      clearPendingPreloads()
    }
  }, [])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const resetConversation = (mode = lessonId) => {
    threadIdRef.current = null
    setThreadId(null)
    setTeachingState(null)
    clearPreparedVideos()
    clearPendingPreloads()
    setVideoUrl(null)
    setTalkVideoVisible(false)
    setVideoSegments([])
    setActiveSegmentIndex(0)
    setCurrentJob(null)
    setError('')
    setMediaError('')
    setMediaRetry(null)
    setPipelineTimings(null)
    completedFloatJobsRef.current.clear()
    pendingTurnPromiseRef.current = null
    pendingTurnKindRef.current = null
    setPendingStatus('idle')
    setPendingKind(null)
    setSubmissionLocked(false)
    setDynamicAutoRun(false)
    dynamicAutoRunRef.current = false
    setStage('idle')
    setMessages([welcomeMessage(mode)])
  }

  const setConversationLocation = (conversationId: string | null, push = true) => {
    const url = conversationId
      ? `${window.location.pathname}${window.location.search}#/chat/${encodeURIComponent(conversationId)}`
      : `${window.location.pathname}${window.location.search}`
    if (push) window.history.pushState({}, '', url)
    else window.history.replaceState({}, '', url)
  }

  const refreshConversationList = async () => {
    try {
      const response = await fetch(`/v1/users/${encodeURIComponent(userId)}/conversations`)
      if (!response.ok) throw new Error(await responseError(response))
      setConversations((await response.json()) as ConversationSummary[])
      setHistoryError('')
    } catch (caught) {
      setHistoryError(caught instanceof Error ? caught.message : '历史问答加载失败')
    } finally {
      setHistoryLoading(false)
    }
  }

  const refreshCourseOptions = async () => {
    try {
      const response = await fetch('/v1/courses')
      if (!response.ok) throw new Error(await responseError(response))
      setCourseOptions((await response.json()) as CourseOption[])
    } catch {
      setCourseOptions(defaultCourseOptions)
    }
  }

  const loadConversation = async (conversationId: string, updateLocation = true) => {
    if (busyRef.current) return
    setHistoryLoading(true)
    setHistoryError('')
    try {
      if (lessonIdRef.current !== 'default' && threadIdRef.current) {
        await deleteThread(threadIdRef.current)
      }
      const response = await fetch(
        `/v1/conversations/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userId)}`,
      )
      if (!response.ok) throw new Error(await responseError(response))
      const detail = (await response.json()) as ConversationDetail
      setLessonId('default')
      lessonIdRef.current = 'default'
      resetConversation('default')
      setThreadId(detail.thread_id)
      threadIdRef.current = detail.thread_id
      setTeachingState(detail.teaching_state)
      teachingStateRef.current = detail.teaching_state
      setMessages(detail.messages.length > 0
        ? detail.messages.map((message) => ({
            id: `history-${message.id}`,
            role: message.role,
            text: message.text,
            time: messageTime(message.created_at),
            emotion: message.emotion || undefined,
          }))
        : [welcomeMessage('default')])
      setDynamicAutoRun(false)
      dynamicAutoRunRef.current = false
      if (updateLocation) setConversationLocation(detail.thread_id)
    } catch (caught) {
      setHistoryError(caught instanceof Error ? caught.message : '历史问答加载失败')
      if (!updateLocation) setConversationLocation(null, false)
    } finally {
      setHistoryLoading(false)
    }
  }

  const deleteThread = async (conversationId: string) => {
    const response = await fetch(
      `/v1/threads/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userId)}`,
      { method: 'DELETE' },
    )
    if (!response.ok && response.status !== 404) {
      throw new Error(await responseError(response))
    }
  }

  const startNewFreeConversation = async () => {
    if (busy) return
    if (lessonId !== 'default' && threadIdRef.current) {
      try {
        await deleteThread(threadIdRef.current)
      } catch (caught) {
        setHistoryError(caught instanceof Error ? caught.message : '临时课程清理失败')
      }
    }
    setLessonId('default')
    lessonIdRef.current = 'default'
    resetConversation('default')
    setConversationLocation(null)
  }

  const selectMode = async (selectedMode: string) => {
    if (busy || selectedMode === lessonId) return
    if (lessonId !== 'default' && threadIdRef.current) {
      try {
        await deleteThread(threadIdRef.current)
      } catch (caught) {
        setHistoryError(caught instanceof Error ? caught.message : '临时课程清理失败')
      }
    }
    setLessonId(selectedMode)
    lessonIdRef.current = selectedMode
    resetConversation(selectedMode)
    setConversationLocation(null)
  }

  const deleteConversation = async (conversationId: string) => {
    if (busy || !window.confirm('删除这段历史问答？此操作无法撤销。')) return
    try {
      await deleteThread(conversationId)
      if (threadIdRef.current === conversationId) {
        setLessonId('default')
        lessonIdRef.current = 'default'
        resetConversation('default')
        setConversationLocation(null, false)
      }
      await refreshConversationList()
    } catch (caught) {
      setHistoryError(caught instanceof Error ? caught.message : '删除历史问答失败')
    }
  }

  useEffect(() => {
    // Older versions silently restored this id while showing an empty UI.
    // Hash-based navigation now makes restoration explicit and visible.
    localStorage.removeItem('virtual-teacher-thread-id')

    const handleHistoryNavigation = () => {
      const conversationId = conversationIdFromHash()
      if (conversationId) {
        void loadConversation(conversationId, false)
      } else if (!busyRef.current) {
        setLessonId('default')
        lessonIdRef.current = 'default'
        resetConversation('default')
      }
    }
    window.addEventListener('popstate', handleHistoryNavigation)
    return () => window.removeEventListener('popstate', handleHistoryNavigation)
    // The navigation listener intentionally binds to the initial idle render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (backend !== 'online') return
    void refreshConversationList()
    void refreshCourseOptions()
    const initialConversationId = conversationIdFromHash()
    if (initialConversationId && threadIdRef.current !== initialConversationId) {
      void loadConversation(initialConversationId, false)
    }
    // The service transition is the retry trigger when the page opened early.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend])

  const pollVideo = (jobId: string, index: number, foreground: boolean) => {
    const readyUrl = readyVideoUrlsRef.current.get(index)
    if (readyUrl) return Promise.resolve(readyUrl)
    const existingPoll = videoPollsRef.current.get(index)
    if (existingPoll) return existingPoll

    const task = (async () => {
      while (mountedRef.current) {
        const response = await fetch(`/v1/video-jobs/${jobId}`)
        if (!response.ok) throw new Error(await responseError(response))
        const job = (await response.json()) as VideoJob
        if (!mountedRef.current) throw new Error('页面已经关闭')
        if (foreground) setCurrentJob(job)
        if (job.status === 'failed') {
          throw new Error(job.error || 'FLOAT 视频生成失败')
        }
        if (job.status === 'completed') {
          if (!completedFloatJobsRef.current.has(jobId)) {
            completedFloatJobsRef.current.add(jobId)
            setPipelineTimings((current) => ({
              ...(current || {}),
              float_seconds: Number(((current?.float_seconds || 0) + job.elapsed_seconds).toFixed(3)),
              ...(job.queue_wait_seconds != null ? {
                float_queue_seconds: Number(((current?.float_queue_seconds || 0) + job.queue_wait_seconds).toFixed(3)),
              } : {}),
              ...(job.total_elapsed_seconds != null ? {
                float_total_seconds: Number(((current?.float_total_seconds || 0) + job.total_elapsed_seconds).toFixed(3)),
              } : {}),
            }))
          }
          if (!job.video_url) throw new Error('任务完成但没有返回视频地址')
          const url = `${job.video_url}?v=${Date.now()}`
          readyVideoUrlsRef.current.set(index, url)
          const bufferMs = await preloadVideo(url, index)
          setPipelineTimings((current) => ({
            ...(current || {}),
            browser_buffer_ms: Number(((current?.browser_buffer_ms || 0) + bufferMs).toFixed(2)),
          }))
          return url
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1200))
      }
      throw new Error('页面已经关闭')
    })()
    videoPollsRef.current.set(index, task)
    void task.finally(() => videoPollsRef.current.delete(index)).catch(() => undefined)
    return task
  }

  const fetchChatResult = async (text: string, lessonAction: LessonAction) => {
    const requestStarted = performance.now()
    const response = await fetch('/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        // Automatic course advancement runs from a callback created by the
        // previous render. A ref guarantees it uses the thread returned by
        // the latest response instead of accidentally creating a new thread.
        thread_id: threadIdRef.current,
        lesson_id: lessonId,
        text,
        render_video: videoEnabled,
        lesson_action: lessonAction,
      }),
    })
    if (!response.ok) throw new Error(await responseError(response))
    const result = (await response.json()) as ChatResult
    result.timings = {
      ...(result.timings || {}),
      client_roundtrip_ms: Number((performance.now() - requestStarted).toFixed(2)),
    }
    return result
  }

  const preparePendingResult = async (result: ChatResult) => {
    let completedFloatSeconds = 0
    let completedFloatQueueSeconds = 0
    let completedFloatTotalSeconds = 0
    let hasFloatQueueMetrics = false
    let hasFloatTotalMetrics = false
    let browserBufferMs = 0
    const rendered = (result.media_segments || []).filter(
      (segment) => segment.video_job !== null || Boolean(segment.video_url),
    )
    const prepared = await Promise.all(rendered.map(async (segment, index) => {
      if (segment.video_url) {
        const separator = segment.video_url.includes('?') ? '&' : '?'
        const url = `${segment.video_url}${separator}v=${Date.now()}`
        const bufferMs = await preloadVideo(url, index, 'pending')
        browserBufferMs += bufferMs
        return { ...segment, video_url: url }
      }
      const jobId = segment.video_job?.job_id
      if (!jobId) return segment
      while (mountedRef.current) {
        const response = await fetch(`/v1/video-jobs/${jobId}`)
        if (!response.ok) throw new Error(await responseError(response))
        const job = (await response.json()) as VideoJob
        if (job.status === 'failed') throw new Error(job.error || 'FLOAT 视频生成失败')
        if (job.status === 'completed') {
          completedFloatSeconds += job.elapsed_seconds
          if (job.queue_wait_seconds != null) {
            completedFloatQueueSeconds += job.queue_wait_seconds
            hasFloatQueueMetrics = true
          }
          if (job.total_elapsed_seconds != null) {
            completedFloatTotalSeconds += job.total_elapsed_seconds
            hasFloatTotalMetrics = true
          }
          if (!job.video_url) throw new Error('任务完成但没有返回视频地址')
          const separator = job.video_url.includes('?') ? '&' : '?'
          const url = `${job.video_url}${separator}v=${Date.now()}`
          const bufferMs = await preloadVideo(url, index, 'pending')
          browserBufferMs += bufferMs
          return { ...segment, video_job: null, video_url: url }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1200))
      }
      throw new Error('页面已经关闭')
    }))
    return {
      ...result,
      media_segments: prepared,
      timings: {
        ...(result.timings || {}),
        float_seconds: Number(completedFloatSeconds.toFixed(3)),
        ...(hasFloatQueueMetrics ? {
          float_queue_seconds: Number(completedFloatQueueSeconds.toFixed(3)),
        } : {}),
        ...(hasFloatTotalMetrics ? {
          float_total_seconds: Number(completedFloatTotalSeconds.toFixed(3)),
        } : {}),
        browser_buffer_ms: Number(browserBufferMs.toFixed(2)),
      },
    }
  }

  const prepareVideoSegment = async (segments: MediaSegment[], index: number) => {
    const segment = segments[index]
    if (!segment || (!segment.video_job && !segment.video_url)) return
    setActiveSegmentIndex(index)
    setCurrentJob(segment.video_job || null)
    setTalkVideoVisible(false)
    let url = readyVideoUrlsRef.current.get(index)
    if (!url && segment.video_url) {
      url = `${segment.video_url}?v=${Date.now()}`
      readyVideoUrlsRef.current.set(index, url)
      const bufferMs = await preloadVideo(url, index)
      setPipelineTimings((current) => ({
        ...(current || {}),
        browser_buffer_ms: Number(((current?.browser_buffer_ms || 0) + bufferMs).toFixed(2)),
      }))
    } else if (!url && segment.video_job) {
      setStage('rendering')
      url = await pollVideo(segment.video_job.job_id, index, true)
    }
    if (!url) return
    if (!mountedRef.current) return
    setVideoUrl(url)
    setStage('ready')

    const next = segments[index + 1]
    if (next?.video_job) {
      void pollVideo(next.video_job.job_id, index + 1, false).catch(() => undefined)
    } else if (next?.video_url && !readyVideoUrlsRef.current.has(index + 1)) {
      const nextUrl = `${next.video_url}?v=${Date.now()}`
      readyVideoUrlsRef.current.set(index + 1, nextUrl)
      void preloadVideo(nextUrl, index + 1).then((bufferMs) => {
        setPipelineTimings((current) => ({
          ...(current || {}),
          browser_buffer_ms: Number(((current?.browser_buffer_ms || 0) + bufferMs).toFixed(2)),
        }))
      }).catch(() => undefined)
    }
  }

  const requestTurn = async ({
    text,
    lessonAction = 'user',
    displayUser = true,
    clearComposer = false,
    allowWhileBusy = false,
  }: {
    text: string
    lessonAction?: LessonAction
    displayUser?: boolean
    clearComposer?: boolean
    allowWhileBusy?: boolean
  }) => {
    const turnText = text.trim()
    if (!turnText || speechBusyRef.current || (busy && !allowWhileBusy)) return
    if (displayUser) {
      setMessages((items) => [
        ...items,
        { id: createId(), role: 'user', text: turnText, time: now() },
      ])
    }
    if (clearComposer) setInput('')
    setError('')
    setMediaError('')
    setMediaRetry(null)
    setPipelineTimings(null)
    completedFloatJobsRef.current.clear()
    clearPreparedVideos()
    setVideoUrl(null)
    setTalkVideoVisible(false)
    setVideoSegments([])
    setActiveSegmentIndex(0)
    setCurrentJob(null)
    const localOnly = ['start', 'advance', 'answer'].includes(lessonAction)
      && (guidedLecture || interactivePractice)
    setThinkingHint(localOnly ? '正在推进本地 LangGraph 课程状态，不调用语言模型' : '正在调用教学模型')
    setStage('thinking')

    try {
      const result = await fetchChatResult(turnText, lessonAction)
      if (!mountedRef.current) return

      setThreadId(result.thread_id)
      threadIdRef.current = result.thread_id
      if (lessonId === 'default') {
        setConversationLocation(result.thread_id, false)
        void refreshConversationList()
      }
      setTeachingState(result.teaching_state)
      teachingStateRef.current = result.teaching_state
      setPipelineTimings(result.timings || null)
      setMediaError(result.media_error || '')
      setMediaRetry(result.media_error ? {
        text: result.reply_text,
        emotion: result.emotion,
        speechRate: result.speech_rate,
      } : null)
      setMessages((items) => [
        ...items,
        {
          id: createId(),
          role: 'assistant',
          text: result.reply_text,
          time: now(),
          emotion: result.emotion,
          sources: result.sources || [],
        },
      ])

      const renderedSegments = (result.media_segments || []).filter(
        (segment) => segment.video_job !== null || Boolean(segment.video_url),
      )
      if (renderedSegments.length > 0) {
        setVideoSegments(renderedSegments)
        await prepareVideoSegment(renderedSegments, 0)
      } else if (result.video_job) {
        // Compatibility with an older backend that returns one video_job.
        const fallbackSegment: MediaSegment = {
          index: 0,
          text: result.reply_text,
          characters: result.reply_text.length,
          over_soft_limit: false,
          video_job: result.video_job,
          video_url: null,
        }
        setVideoSegments([fallbackSegment])
        await prepareVideoSegment([fallbackSegment], 0)
      } else {
        setStage(result.media_error ? 'error' : 'idle')
        if (
          guidedLecture
          && result.teaching_state?.lesson_phase === 'lecture'
          && !inputRef.current.trim()
        ) {
          window.setTimeout(() => {
            void requestTurn({
              text: '自动进入下一讲',
              lessonAction: 'advance',
              displayUser: false,
              allowWhileBusy: true,
            })
          }, 700)
        } else if (result.teaching_state?.lesson_phase === 'dynamic_lecture' && dynamicAutoRunRef.current) {
          window.setTimeout(() => {
            void requestTurn({
              text: '自动继续动态讲授',
              lessonAction: 'dynamic_advance',
              displayUser: false,
              allowWhileBusy: true,
            })
          }, 700)
        }
      }
    } catch (caught) {
      if (!mountedRef.current) return
      setError(caught instanceof Error ? caught.message : '请求失败，请稍后重试')
      if (clearComposer) setInput(turnText)
      setStage('error')
    }
  }

  const looksLikeQuestion = (text: string) => {
    const normalized = text.trim()
    return /[?？]$/.test(normalized)
      || /[吗么呢][。.!！]*$/.test(normalized)
      || /(请问|为什么|为何|是什么|怎么|怎样|如何|能不能|能否|可不可以|可以吗|是不是|是否|有没有|多少|哪里|哪个|哪种|几)/.test(normalized)
  }

  const queueTurn = async (
    text: string,
    lessonAction: LessonAction,
    options: { displayUser?: boolean; kind?: PendingTurnKind } = {},
  ) => {
    const turnText = text.trim()
    const kind = options.kind || 'user'
    if (!turnText || speechBusyRef.current || pendingTurnPromiseRef.current) return
    if (kind === 'user' && submissionLocked) return
    if (options.displayUser !== false) {
      setMessages((items) => [
        ...items,
        { id: createId(), role: 'user', text: turnText, time: now() },
      ])
      setInput('')
      setSubmissionLocked(true)
    }
    setError('')
    setPendingStatus('generating')
    setPendingKind(kind)
    pendingTurnKindRef.current = kind
    clearPendingPreloads()
    const promise = fetchChatResult(turnText, lessonAction)
      .then(preparePendingResult)
      .then((result) => {
        if (mountedRef.current) setPendingStatus('ready')
        return result
      })
    pendingTurnPromiseRef.current = promise
    void promise.catch(() => undefined)
  }

  const sendMessage = async (explicitAction?: LessonAction) => {
    if (speechBusyRef.current) return
    let lessonAction: LessonAction = explicitAction || 'user'
    if (guidedLecture) {
      lessonAction = 'question'
    } else if (interactivePractice && !explicitAction) {
      lessonAction = teachingState?.lesson_phase === 'await_answer'
        ? looksLikeQuestion(input) ? 'question' : 'answer'
        : 'question'
    }
    if (stage === 'speaking') {
      await queueTurn(input, lessonAction)
      return
    }
    await requestTurn({
      text: input,
      lessonAction,
      displayUser: true,
      clearComposer: true,
    })
  }

  const retryCurrentMedia = async () => {
    if (!mediaRetry || busy || worker !== 'online') return
    setError('')
    setMediaError('')
    setThinkingHint('只重新生成语音和视频，不调用语言模型')
    setStage('thinking')
    completedFloatJobsRef.current.clear()
    const requestStarted = performance.now()
    try {
      const response = await fetch('/v1/media', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: mediaRetry.text,
          emotion: mediaRetry.emotion,
          speech_rate: mediaRetry.speechRate,
          render_video: videoEnabled,
        }),
      })
      if (!response.ok) throw new Error(await responseError(response))
      const result = (await response.json()) as Pick<ChatResult, 'media_segments' | 'timings' | 'media_error'>
      const timings = {
        ...(result.timings || {}),
        client_roundtrip_ms: Number((performance.now() - requestStarted).toFixed(2)),
      }
      setPipelineTimings(timings)
      if (result.media_error) {
        setMediaError(result.media_error)
        setStage('error')
        return
      }
      setMediaRetry(null)
      const rendered = (result.media_segments || []).filter(
        (segment) => segment.video_job !== null || Boolean(segment.video_url),
      )
      if (rendered.length === 0) {
        setStage('idle')
        return
      }
      clearPreparedVideos()
      setVideoSegments(rendered)
      setActiveSegmentIndex(0)
      await prepareVideoSegment(rendered, 0)
    } catch (caught) {
      setMediaError(caught instanceof Error ? caught.message : '媒体重试失败')
      setStage('error')
    }
  }

  const previewCoursePdf = async () => {
    if (!coursePdf || courseImportLoading) return
    const startPage = Number.parseInt(courseStartPage, 10)
    const endPage = Number.parseInt(courseEndPage, 10)
    if (!Number.isInteger(startPage) || !Number.isInteger(endPage) || startPage < 1 || endPage < startPage) {
      setCourseImportError('请输入正确的起止页码')
      return
    }
    setCourseImportLoading(true)
    setCourseImportError('')
    setCoursePreview(null)
    setCourseBlueprint(null)
    setCourseDesignError('')
    setCourseDesignNotice('')
    try {
      const params = new URLSearchParams({
        filename: coursePdf.name,
        start_page: String(startPage),
        end_page: String(endPage),
      })
      const response = await fetch(`/v1/course-imports/preview?${params.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/pdf' },
        body: coursePdf,
      })
      if (!response.ok) throw new Error(await responseError(response))
      const preview = (await response.json()) as CourseImportPreview
      setCoursePreview(preview)
      const recommended = preview.generation_plan?.recommended_lesson_count
      if (recommended) {
        setCourseLessonCount(String(recommended))
        setCourseTargetMinutes(String(Math.max(30, recommended * 10)))
      }
      setCourseBuilderView('editor')
    } catch (caught) {
      setCourseImportError(caught instanceof Error ? caught.message : 'PDF解析失败')
    } finally {
      setCourseImportLoading(false)
    }
  }

  const uploadFullCoursePdf = async () => {
    if (!coursePdf || courseUploadLoading) return
    setCourseUploadLoading(true)
    setCourseImportError('')
    setCourseImportRecord(null)
    setSelectedChapterIndex(null)
    setCoursePreview(null)
    setCourseBlueprint(null)
    setCourseDesignNotice('')
    setChapterEditMode(false)
    setChapterEdits([])
    setCoursePublishNotice('')
    setRagStatus(null)
    setCourseBuilderView('library')
    try {
      const params = new URLSearchParams({ filename: coursePdf.name })
      const response = await fetch(`/v1/course-imports?${params.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/pdf' },
        body: coursePdf,
      })
      if (!response.ok) throw new Error(await responseError(response))
      const record = (await response.json()) as CourseImportRecord
      setCourseImportRecord(record)
      setChapterEdits(record.chapters.map((chapter) => ({ ...chapter })))
      const statusResponse = await fetch(`/v1/course-imports/${record.import_id}/rag/status`)
      if (statusResponse.ok) setRagStatus((await statusResponse.json()) as RAGStatus)
    } catch (caught) {
      setCourseImportError(caught instanceof Error ? caught.message : '整本教材上传失败')
    } finally {
      setCourseUploadLoading(false)
    }
  }

  const buildTextbookRagIndex = async () => {
    if (!courseImportRecord || ragIndexLoading) return
    setRagIndexLoading(true)
    setCourseImportError('')
    setCoursePublishNotice('')
    try {
      const response = await fetch(
        `/v1/course-imports/${courseImportRecord.import_id}/rag/index`,
        { method: 'POST' },
      )
      if (!response.ok) throw new Error(await responseError(response))
      const status = (await response.json()) as RAGStatus
      setRagStatus(status)
      setCoursePublishNotice(
        `教材问答索引已建立：${status.text_pages || 0}个文字页、${status.chunk_count || 0}个检索片段。此步骤没有调用语言模型。`,
      )
    } catch (caught) {
      setCourseImportError(caught instanceof Error ? caught.message : '教材问答索引建立失败')
    } finally {
      setRagIndexLoading(false)
    }
  }

  const saveChapterStructure = async () => {
    if (!courseImportRecord || chapterSaveLoading) return
    setChapterSaveLoading(true)
    setCourseImportError('')
    setCoursePublishNotice('')
    try {
      const response = await fetch(
        `/v1/course-imports/${courseImportRecord.import_id}/chapters`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chapters: chapterEdits.map((chapter) => ({
              chapter_index: chapter.chapter_index,
              title: chapter.title.trim(),
              start_page: Number(chapter.start_page),
              end_page: Number(chapter.end_page),
            })),
          }),
        },
      )
      if (!response.ok) throw new Error(await responseError(response))
      const record = (await response.json()) as CourseImportRecord
      setCourseImportRecord(record)
      setChapterEdits(record.chapters.map((chapter) => ({ ...chapter })))
      setChapterEditMode(false)
      setSelectedChapterIndex(null)
      setCoursePreview(null)
      setCourseBlueprint(null)
      setCourseDesignNotice('')
      setCoursePublishNotice('章节结构已保存。页码范围发生变化的旧草稿会标记为需要重新生成。')
    } catch (caught) {
      setCourseImportError(caught instanceof Error ? caught.message : '章节结构保存失败')
    } finally {
      setChapterSaveLoading(false)
    }
  }

  const previewImportedChapter = async (chapter: CourseChapter) => {
    if (!courseImportRecord || courseImportLoading) return
    setSelectedChapterIndex(chapter.chapter_index)
    setCourseStartPage(String(chapter.start_page))
    setCourseEndPage(String(chapter.end_page))
    setCourseImportLoading(true)
    setCourseImportError('')
    setCourseDesignError('')
    setCourseDesignNotice('')
    setCoursePreview(null)
    setCourseBlueprint(null)
    setCoursePublishNotice('')
    try {
      const params = new URLSearchParams({ lesson_count: courseLessonCount })
      const response = await fetch(
        `/v1/course-imports/${courseImportRecord.import_id}/chapters/${chapter.chapter_index}/preview?${params.toString()}`,
        { method: 'POST' },
      )
      if (!response.ok) throw new Error(await responseError(response))
      const preview = (await response.json()) as CourseImportPreview
      setCoursePreview(preview)
      const recommended = preview.generation_plan?.recommended_lesson_count
      if (recommended) {
        setCourseLessonCount(String(recommended))
        setCourseTargetMinutes(String(Math.max(30, recommended * 10)))
      }
      const draft = courseImportRecord.chapter_drafts.find((item) => item.chapter_index === chapter.chapter_index)
      if (draft && !draft.stale) {
        const draftResponse = await fetch(
          `/v1/course-imports/${courseImportRecord.import_id}/chapters/${chapter.chapter_index}/draft`,
        )
        if (draftResponse.ok) {
          setCourseBlueprint((await draftResponse.json()) as CourseBlueprint)
          setCoursePublishNotice('已载入本机保存的课程草稿，可以继续修改或发布，不会重新调用千问。')
        }
      }
      setCourseBuilderView('editor')
    } catch (caught) {
      setCourseImportError(caught instanceof Error ? caught.message : '章节提取失败')
    } finally {
      setCourseImportLoading(false)
    }
  }

  const designCourseBlueprint = async () => {
    if (!coursePreview || courseDesignLoading) return
    const lessonCount = Number.parseInt(courseLessonCount, 10)
    const targetMinutes = Number.parseInt(courseTargetMinutes, 10)
    if (!courseAudience.trim()) {
      setCourseDesignError('请填写目标学习者')
      return
    }
    if (!Number.isInteger(lessonCount) || lessonCount < 1 || lessonCount > 12) {
      setCourseDesignError('课时数需要在1到12之间')
      return
    }
    if (!Number.isInteger(targetMinutes) || targetMinutes < 10 || targetMinutes > 360) {
      setCourseDesignError('总时长需要在10到360分钟之间')
      return
    }
    setCourseDesignLoading(true)
    setCourseDesignError('')
    setCourseDesignNotice('')
    try {
      const chapterMode = Boolean(courseImportRecord && selectedChapterIndex)
      const endpoint = chapterMode
        ? `/v1/course-imports/${courseImportRecord?.import_id}/chapters/${selectedChapterIndex}/design`
        : '/v1/course-imports/design'
      const body = chapterMode
        ? {
            audience: courseAudience.trim(),
            lesson_count: lessonCount,
            target_minutes: targetMinutes,
          }
        : {
            filename: coursePreview.filename,
            audience: courseAudience.trim(),
            lesson_count: lessonCount,
            target_minutes: targetMinutes,
            pages: coursePreview.pages
              .filter((page) => page.has_text_layer && page.text.trim())
              .map((page) => ({
                page_number: page.page_number,
                has_text_layer: page.has_text_layer,
                text: page.text,
              })),
          }
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error(await responseError(response))
      const blueprint = (await response.json()) as CourseBlueprint
      setCourseBlueprint(blueprint)
      setCourseDesignNotice(
        blueprint.validation_issues?.length
          ? `千问内容已保留为待修复草稿，共发现 ${blueprint.validation_issues.length} 处需要手动修改；不需要重新生成。`
          : blueprint.auto_fixes?.length
            ? `草稿已保存；系统自动修复了 ${blueprint.auto_fixes.length} 处安全的格式问题。`
            : '课程草稿已生成并保存在本机。请审核后再发布。',
      )
      if (blueprint.draft && courseImportRecord) {
        const savedDraft = blueprint.draft
        setCourseImportRecord((current) => current ? {
          ...current,
          chapter_drafts: [
            ...current.chapter_drafts.filter((draft) => draft.chapter_index !== savedDraft.chapter_index),
            {
              chapter_index: savedDraft.chapter_index,
              title: blueprint.course_title,
              lesson_count: blueprint.lessons.length,
              saved_at: savedDraft.saved_at,
            },
          ],
        } : current)
      }
    } catch (caught) {
      const reason = caught instanceof Error ? caught.message : '课程蓝图生成失败'
      setCourseDesignError(
        `生成失败：${reason} ${courseBlueprint ? '下方仍保留上一次成功草稿。' : '本次没有可恢复的草稿。'}重试会再次调用千问。`,
      )
    } finally {
      setCourseDesignLoading(false)
    }
  }

  const updateBlueprintLesson = (
    lessonIndex: number,
    updater: (lesson: CourseBlueprint['lessons'][number]) => CourseBlueprint['lessons'][number],
  ) => {
    setCourseBlueprint((current) => current ? {
      ...current,
      lessons: current.lessons.map((lesson, index) => index === lessonIndex ? updater(lesson) : lesson),
    } : current)
    setCoursePublishNotice('')
  }

  const publishCourseBlueprint = async () => {
    if (!courseImportRecord || !selectedChapterIndex || !courseBlueprint || coursePublishLoading) return
    setCoursePublishLoading(true)
    setCourseDesignError('')
    setCoursePublishNotice('')
    try {
      const response = await fetch(
        `/v1/course-imports/${courseImportRecord.import_id}/chapters/${selectedChapterIndex}/publish`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ blueprint: courseBlueprint }),
        },
      )
      if (!response.ok) throw new Error(await responseError(response))
      const result = (await response.json()) as { course: CourseOption; blueprint: CourseBlueprint }
      setCourseBlueprint(result.blueprint)
      setCourseOptions((current) => [
        ...current.filter((course) => course.lesson_id !== result.course.lesson_id),
        result.course,
      ])
      setCourseImportRecord((current) => current ? {
        ...current,
        chapter_publications: [
          ...(current.chapter_publications || []).filter(
            (item) => item.chapter_index !== selectedChapterIndex,
          ),
          {
            chapter_index: selectedChapterIndex,
            lesson_id: result.course.lesson_id,
            title: result.course.title,
            published_at: result.course.published_at || new Date().toISOString(),
          },
        ],
      } : current)
      setCoursePublishNotice(`“${result.course.title}”已发布到教学模式列表。固定讲稿和题目不会再次调用语言模型。`)
    } catch (caught) {
      setCourseDesignError(caught instanceof Error ? caught.message : '课程发布失败')
    } finally {
      setCoursePublishLoading(false)
    }
  }

  const unpublishCourseBlueprint = async () => {
    if (!courseImportRecord || !selectedChapterIndex || courseUnpublishLoading) return
    const publication = (courseImportRecord.chapter_publications || []).find(
      (item) => item.chapter_index === selectedChapterIndex,
    )
    if (!publication) return
    if (!window.confirm(`下架“${publication.title}”？课程会从教学模式中移除，但审核草稿和教材仍会保留。`)) return
    setCourseUnpublishLoading(true)
    setCourseDesignError('')
    setCoursePublishNotice('')
    try {
      const response = await fetch(
        `/v1/course-imports/${courseImportRecord.import_id}/chapters/${selectedChapterIndex}/publish`,
        { method: 'DELETE' },
      )
      if (!response.ok) throw new Error(await responseError(response))
      setCourseOptions((current) => current.filter(
        (course) => course.lesson_id !== publication.lesson_id,
      ))
      setCourseImportRecord((current) => current ? {
        ...current,
        chapter_publications: (current.chapter_publications || []).filter(
          (item) => item.chapter_index !== selectedChapterIndex,
        ),
      } : current)
      setCourseBlueprint((current) => current ? {
        ...current,
        status: 'draft',
        grounding: { ...current.grounding, human_review_required: true },
      } : current)
      if (lessonIdRef.current === publication.lesson_id) {
        await selectMode('default')
      }
      setCoursePublishNotice(`“${publication.title}”已下架，审核草稿仍保留在本机，可以修改后重新发布。`)
    } catch (caught) {
      setCourseDesignError(caught instanceof Error ? caught.message : '课程下架失败')
    } finally {
      setCourseUnpublishLoading(false)
    }
  }

  const openCourseManager = async () => {
    setShowCourseImport(false)
    setShowCourseManager(true)
    setCourseManagerLoading(true)
    setCourseManagerError('')
    try {
      const response = await fetch('/v1/course-projects')
      if (!response.ok) throw new Error(await responseError(response))
      setCourseProjects((await response.json()) as CourseProject[])
    } catch (caught) {
      setCourseManagerError(caught instanceof Error ? caught.message : '课程列表读取失败')
    } finally {
      setCourseManagerLoading(false)
    }
  }

  const openManagedCourse = async (project: CourseProject) => {
    if (courseManagerLoading) return
    setCourseManagerLoading(true)
    setCourseManagerError('')
    try {
      const recordResponse = await fetch(`/v1/course-imports/${project.import_id}`)
      if (!recordResponse.ok) throw new Error(await responseError(recordResponse))
      const record = (await recordResponse.json()) as CourseImportRecord
      const chapter = record.chapters.find(
        (item) => item.chapter_index === project.chapter_index,
      )
      if (!chapter) throw new Error('原教材中的章节记录已经不存在')
      const params = new URLSearchParams({
        lesson_count: String(Math.max(1, project.lesson_count || 1)),
      })
      const previewResponse = await fetch(
        `/v1/course-imports/${project.import_id}/chapters/${project.chapter_index}/preview?${params.toString()}`,
        { method: 'POST' },
      )
      if (!previewResponse.ok) throw new Error(await responseError(previewResponse))
      const draftResponse = await fetch(
        `/v1/course-imports/${project.import_id}/chapters/${project.chapter_index}/draft`,
      )
      if (!draftResponse.ok) throw new Error(await responseError(draftResponse))
      const preview = (await previewResponse.json()) as CourseImportPreview
      const blueprint = (await draftResponse.json()) as CourseBlueprint
      setCoursePdf(null)
      setCourseImportRecord(record)
      setSelectedChapterIndex(project.chapter_index)
      setCourseStartPage(String(chapter.start_page))
      setCourseEndPage(String(chapter.end_page))
      setCoursePreview(preview)
      setCourseBlueprint(blueprint)
      setCourseLessonCount(String(Math.max(1, blueprint.lessons.length)))
      setCourseTargetMinutes(String(blueprint.total_minutes))
      setChapterEdits(record.chapters.map((item) => ({ ...item })))
      setCourseBuilderView('editor')
      setCoursePublishNotice('已从课程管理中载入本机草稿，不会重新调用千问。')
      setCourseImportError('')
      setCourseDesignError('')
      setShowCourseManager(false)
      setShowCourseImport(true)
    } catch (caught) {
      setCourseManagerError(caught instanceof Error ? caught.message : '课程草稿打开失败')
    } finally {
      setCourseManagerLoading(false)
    }
  }

  const unpublishManagedCourse = async (project: CourseProject) => {
    if (!project.published || courseManagerLoading || busy) return
    if (!window.confirm(`下架“${project.course_title}”？草稿和教材仍会保留。`)) return
    setCourseManagerLoading(true)
    setCourseManagerError('')
    try {
      const response = await fetch(
        `/v1/course-imports/${project.import_id}/chapters/${project.chapter_index}/publish`,
        { method: 'DELETE' },
      )
      if (!response.ok) throw new Error(await responseError(response))
      setCourseOptions((current) => current.filter(
        (course) => course.lesson_id !== project.lesson_id,
      ))
      setCourseProjects((current) => current.map((item) => (
        item.import_id === project.import_id && item.chapter_index === project.chapter_index
          ? { ...item, published: false, lesson_id: '', published_at: '' }
          : item
      )))
      if (lessonIdRef.current === project.lesson_id) await selectMode('default')
    } catch (caught) {
      setCourseManagerError(caught instanceof Error ? caught.message : '课程下架失败')
    } finally {
      setCourseManagerLoading(false)
    }
  }

  const deleteManagedCourse = async (project: CourseProject) => {
    if (courseManagerLoading || busy) return
    if (!window.confirm(
      `彻底删除“${project.course_title}”的发布记录和课程草稿？教材PDF和RAG索引会保留，但课程草稿无法恢复。`,
    )) return
    setCourseManagerLoading(true)
    setCourseManagerError('')
    try {
      const response = await fetch(
        `/v1/course-projects/${project.import_id}/chapters/${project.chapter_index}`,
        { method: 'DELETE' },
      )
      if (!response.ok) throw new Error(await responseError(response))
      setCourseProjects((current) => current.filter(
        (item) => item.import_id !== project.import_id || item.chapter_index !== project.chapter_index,
      ))
      if (project.lesson_id) {
        setCourseOptions((current) => current.filter(
          (course) => course.lesson_id !== project.lesson_id,
        ))
        if (lessonIdRef.current === project.lesson_id) await selectMode('default')
      }
    } catch (caught) {
      setCourseManagerError(caught instanceof Error ? caught.message : '课程删除失败')
    } finally {
      setCourseManagerLoading(false)
    }
  }

  const promotePendingTurn = async (result: ChatResult) => {
    pendingTurnPromiseRef.current = null
    pendingTurnKindRef.current = null
    setPendingStatus('idle')
    setPendingKind(null)
    // The single pre-generation slot is free as soon as its result is
    // promoted for playback. This permits one-turn lookahead on every video,
    // while still preventing two simultaneous background requests.
    setSubmissionLocked(false)
    setThreadId(result.thread_id)
    threadIdRef.current = result.thread_id
    if (lessonId === 'default') {
      setConversationLocation(result.thread_id, false)
      void refreshConversationList()
    }
    setTeachingState(result.teaching_state)
    teachingStateRef.current = result.teaching_state
    setPipelineTimings(result.timings || null)
    setMediaError(result.media_error || '')
    setMediaRetry(result.media_error ? {
      text: result.reply_text,
      emotion: result.emotion,
      speechRate: result.speech_rate,
    } : null)
    setMessages((items) => [
      ...items,
      {
        id: createId(),
        role: 'assistant',
        text: result.reply_text,
        time: now(),
        emotion: result.emotion,
        sources: result.sources || [],
      },
    ])
    clearPreparedVideos()
    const rendered = (result.media_segments || []).filter(
      (segment) => segment.video_job !== null || Boolean(segment.video_url),
    )
    if (rendered.length > 0) {
      pendingPreloadedVideosRef.current.forEach((video, index) => {
        preloadedVideosRef.current.set(index, video)
      })
      pendingPreloadedVideosRef.current.clear()
      rendered.forEach((segment, index) => {
        if (segment.video_url) readyVideoUrlsRef.current.set(index, segment.video_url)
      })
      setVideoSegments(rendered)
      setActiveSegmentIndex(0)
      await prepareVideoSegment(rendered, 0)
    } else {
      setSubmissionLocked(false)
      setStage(result.media_error ? 'error' : 'idle')
    }
  }

  const startVideoPlayback = async () => {
    if (!videoRef.current) return
    try {
      await videoRef.current.play()
      setTalkVideoVisible(true)
      setStage('speaking')
      const lessonState = teachingStateRef.current
      const shouldPrefetchDynamic = lessonState?.lesson_phase === 'dynamic_lecture'
        && dynamicAutoRunRef.current
      const shouldPrefetchFixedLecture = guidedLecture
        && lessonState?.lesson_phase === 'lecture'
      if (
        (shouldPrefetchDynamic || shouldPrefetchFixedLecture)
        && !pendingTurnPromiseRef.current
      ) {
        void queueTurn(
          shouldPrefetchDynamic ? '自动继续动态讲授' : '自动进入下一讲',
          shouldPrefetchDynamic ? 'dynamic_advance' : 'advance',
          { displayUser: false, kind: 'auto' },
        )
      }
    } catch {
      setStage('ready')
    }
  }

  const finishVideoPlayback = (skipRemaining = false) => {
    setTalkVideoVisible(false)
    const nextIndex = activeSegmentIndex + 1
    if (!skipRemaining && nextIndex < videoSegments.length) {
      window.setTimeout(() => {
        void prepareVideoSegment(videoSegments, nextIndex).catch((caught) => {
          if (!mountedRef.current) return
          setError(caught instanceof Error ? caught.message : '下一段视频加载失败')
          setStage('error')
        })
      }, 140)
      return
    }
    const transitionDelay = pendingTurnPromiseRef.current ? 40 : 180
    window.setTimeout(() => {
      if (!mountedRef.current) return
      clearPreparedVideos()
      setVideoUrl(null)
      setVideoSegments([])
      setActiveSegmentIndex(0)
      setCurrentJob(null)
      const pending = pendingTurnPromiseRef.current
      if (pending) {
        setStage('rendering')
        void pending.then(promotePendingTurn).catch((caught) => {
          if (!mountedRef.current) return
          pendingTurnPromiseRef.current = null
          pendingTurnKindRef.current = null
          setPendingStatus('idle')
          setPendingKind(null)
          setSubmissionLocked(false)
          setError(caught instanceof Error ? caught.message : '预生成失败，请重新发送')
          setStage('error')
        })
        return
      }
      setStage('idle')
      const lessonState = teachingStateRef.current
      if (
        guidedLecture
        && lessonState?.lesson_phase === 'lecture'
        && !inputRef.current.trim()
      ) {
        void requestTurn({
          text: '自动进入下一讲',
          lessonAction: 'advance',
          displayUser: false,
          allowWhileBusy: true,
        })
      } else if (lessonState?.lesson_phase === 'dynamic_lecture' && dynamicAutoRunRef.current) {
        void requestTurn({
          text: '自动继续动态讲授',
          lessonAction: 'dynamic_advance',
          displayUser: false,
          allowWhileBusy: true,
        })
      }
    }, transitionDelay)
  }

  const skipCurrentVideo = () => {
    videoRef.current?.pause()
    finishVideoPlayback(true)
  }

  const resetCurrentMode = async () => {
    if (lessonId === 'default') {
      await startNewFreeConversation()
      return
    }
    if (threadIdRef.current) {
      try {
        await deleteThread(threadIdRef.current)
      } catch (caught) {
        setHistoryError(caught instanceof Error ? caught.message : '临时课程清理失败')
      }
    }
    resetConversation(lessonId)
    setConversationLocation(null)
  }

  const startFixedLesson = async () => {
    if (busy) return
    if (threadIdRef.current) {
      try {
        await deleteThread(threadIdRef.current)
      } catch (caught) {
        setHistoryError(caught instanceof Error ? caught.message : '旧课程状态清理失败')
      }
    }
    resetConversation(lessonId)
    await requestTurn({
      text: `开始${selectedCourse?.title || '固定课程'}`,
      lessonAction: 'start',
      displayUser: false,
    })
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  const modeLabel = lessonId === 'default'
    ? '自由问答'
    : selectedCourse?.title || '固定课程'
  const lessonStatus = !teachingState
    ? '尚未开始'
    : teachingState.lesson_phase === 'complete' || teachingState.lesson_phase === 'dynamic_complete'
      ? '课程完成'
      : teachingState.lesson_phase === 'dynamic_lecture'
        ? `动态讲授 · 第 ${(teachingState.dynamic_section_index || 0) + 1}/${teachingState.section_total} 节`
        : teachingState.lesson_phase === 'dynamic_paused'
          ? '动态讲授已暂停'
      : teachingState.lesson_phase === 'await_checkpoint'
        ? busy
          ? `正在讲授 · 第 ${teachingState.concept_index + 1}/${teachingState.section_total} 节`
          : `等待回答 · 第 ${teachingState.concept_index + 1} 节`
        : teachingState.lesson_phase === 'lecture'
          ? `正在讲授 · 第 ${teachingState.concept_index + 1}/${teachingState.section_total} 节`
          : teachingState.lesson_phase === 'await_answer'
            ? busy
              ? `正在讲解 · 第 ${teachingState.concept_index + 1}/${teachingState.section_total} 题`
              : `等待回答 · 第 ${teachingState.concept_index + 1}/${teachingState.section_total} 题`
            : `${teachingState.score} 分 · 第 ${teachingState.concept_index + 1} 节`
  const realtimeFactor = pipelineTimings?.audio_seconds && pipelineTimings?.float_seconds
    ? pipelineTimings.audio_seconds / pipelineTimings.float_seconds
    : 0
  const formatMilliseconds = (value?: number) => value === undefined
    ? '—'
    : value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${value.toFixed(0)}ms`

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">知</span>
          <div>
            <strong>知伴 · Virtual Teacher</strong>
            <span>LangGraph 长记忆虚拟教师</span>
          </div>
        </div>
        <div className="service-group" aria-label="服务状态">
          <span className={`service-pill ${backend}`}>
            <i /> 教学服务 {backend === 'online' ? '在线' : backend === 'checking' ? '检查中' : '离线'}
          </span>
          <span className={`service-pill ${worker}`}>
            <i /> FLOAT {workerLabel}
          </span>
        </div>
      </header>

      <section className="workspace">
        <nav className="history-panel" aria-label="自由问答历史">
          <div className="history-heading">
            <div>
              <span className="eyebrow">CHAT HISTORY</span>
              <strong>历史问答</strong>
            </div>
            <button
              className="new-chat-button"
              type="button"
              disabled={busy}
              onClick={() => void startNewFreeConversation()}
            >
              ＋ 新建问答
            </button>
          </div>
          <div className="course-tool-buttons">
            <button
              className="import-course-button"
              type="button"
              onClick={() => {
                setShowCourseManager(false)
                setShowCourseImport(true)
              }}
            >
              ⇧ 导入教材PDF
            </button>
            <button
              className="manage-course-button"
              type="button"
              onClick={() => void openCourseManager()}
            >
              ◫ 管理课程
            </button>
          </div>
          <div className="history-list">
            {historyLoading && conversations.length === 0 && (
              <p className="history-empty">正在读取历史问答…</p>
            )}
            {!historyLoading && conversations.length === 0 && !historyError && (
              <p className="history-empty">发送第一条问题后，会话会显示在这里。</p>
            )}
            {conversations.map((conversation) => (
              <div
                className={`history-item ${lessonId === 'default' && threadId === conversation.thread_id ? 'active' : ''}`}
                key={conversation.thread_id}
              >
                <button
                  className="history-open-button"
                  type="button"
                  disabled={busy}
                  onClick={() => void loadConversation(conversation.thread_id)}
                >
                  <strong>{conversation.title}</strong>
                  <span>{conversationTime(conversation.updated_at)}</span>
                </button>
                <button
                  className="history-delete-button"
                  type="button"
                  disabled={busy}
                  aria-label={`删除 ${conversation.title}`}
                  title="删除历史问答"
                  onClick={() => void deleteConversation(conversation.thread_id)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          {historyError && <p className="history-error">{historyError}</p>}
          <div className="history-note">
            <span>课程记录</span>
            <p>固定讲授和互动练习只保存学习进度，不进入问答历史。</p>
          </div>
        </nav>

        <section className="teacher-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">AI TEACHER</span>
              <h1>专注于你的学习节奏</h1>
            </div>
            {lessonId !== 'default' && (
              <button className="ghost-button" type="button" disabled={busy} onClick={() => void resetCurrentMode()}>
                清空本次课程
              </button>
            )}
          </div>

          <div className={`stage stage-${stage}`}>
            <div className="ambient ambient-one" />
            <div className="ambient ambient-two" />
            <div className="media-frame">
              <img
                className="media-backdrop"
                src="/v1/avatar/reference"
                alt=""
                aria-hidden="true"
              />
              {idleVideoAvailable ? (
                <video
                  className={`media-subject media-base ${talkVideoVisible ? 'media-base-hidden' : ''}`}
                  src="/v1/avatar/idle"
                  poster="/v1/avatar/reference"
                  autoPlay
                  loop
                  muted
                  playsInline
                  preload="auto"
                  aria-label="虚拟教师待机动画"
                  onError={() => setIdleVideoAvailable(false)}
                />
              ) : (
                <img
                  className={`media-subject media-base ${talkVideoVisible ? 'media-base-hidden' : ''}`}
                  src="/v1/avatar/reference"
                  alt="虚拟教师参考形象"
                />
              )}
              {videoUrl && (
                <video
                  className={`media-subject media-talk ${talkVideoVisible ? 'media-talk-visible' : ''}`}
                  ref={videoRef}
                  key={videoUrl}
                  src={videoUrl}
                  playsInline
                  preload="auto"
                  onCanPlay={() => void startVideoPlayback()}
                  onEnded={() => finishVideoPlayback()}
                  onError={() => {
                    setTalkVideoVisible(false)
                    setError('视频加载失败，请检查媒体接口。')
                    setStage('error')
                  }}
                />
              )}
              <div className="media-shade" />
              {stage === 'ready' && (
                <button className="play-button" type="button" onClick={() => void startVideoPlayback()}>
                  <span>▶</span> 播放讲解
                </button>
              )}
              {(stage === 'ready' || stage === 'speaking') && (
                <button className="skip-video-button" type="button" onClick={skipCurrentVideo}>
                  跳过视频
                </button>
              )}
              <div className="teacher-name">
                <span className="live-dot" />
                林老师
              </div>
            </div>
          </div>

          <div className="stage-caption">
            <div className={`stage-icon stage-icon-${stage}`}>
              {stage === 'speaking' ? '⌁' : stage === 'error' ? '!' : '✦'}
            </div>
            <div>
              <strong>{stageCopy[stage].label}</strong>
              <span>{error || (stage === 'thinking' ? thinkingHint : stageCopy[stage].hint)}</span>
            </div>
            {currentJob && (
              <span className="job-chip">
                {videoSegments.length > 1 && `第 ${activeSegmentIndex + 1}/${videoSegments.length} 段 · `}
                {currentJob.status === 'running' ? 'GPU 推理中' : currentJob.status}
                {currentJob.elapsed_seconds > 0 && ` · ${currentJob.elapsed_seconds.toFixed(1)}s`}
              </span>
            )}
            {pendingStatus !== 'idle' && (
              <span className="job-chip pending-chip">
                {pendingKind === 'auto'
                  ? pendingStatus === 'ready' ? '下一节已预加载' : '下一节正在预生成'
                  : pendingStatus === 'ready' ? '下一轮已预加载' : '下一轮正在预生成'}
              </span>
            )}
          </div>

          {mediaError && (
            <div className="media-recovery" role="alert">
              <span>{mediaError}</span>
              {mediaRetry && (
                <button type="button" disabled={busy || worker !== 'online'} onClick={() => void retryCurrentMedia()}>
                  只重试语音和视频
                </button>
              )}
            </div>
          )}

          <div className="lesson-strip">
            <div>
              <span>当前模式</span>
              <strong>{modeLabel}</strong>
            </div>
            <div>
              <span>学习进度</span>
              <strong>{lessonStatus}</strong>
            </div>
            <div>
              <span>对话记忆</span>
              <strong>{threadId
                ? lessonId === 'default' ? '历史问答已保存' : '临时课程状态'
                : lessonId === 'default' ? '发送后创建会话' : '等待开始课程'}</strong>
            </div>
          </div>
          {pipelineTimings && (
            <div className="performance-panel">
              <button
                type="button"
                className="performance-toggle"
                onClick={() => setShowPerformance((visible) => !visible)}
                aria-expanded={showPerformance}
              >
                <span>本轮链路性能</span>
                <strong>
                  {pipelineTimings.cache_hits
                    ? `课程缓存命中 ${pipelineTimings.cache_hits}/${pipelineTimings.segment_count || 0}`
                    : realtimeFactor > 0 ? `FLOAT ${realtimeFactor.toFixed(2)}× 实时` : '查看耗时'}
                </strong>
              </button>
              {showPerformance && (
                <div className="performance-grid">
                  <span>LangGraph / LLM<strong>{formatMilliseconds(pipelineTimings.graph_ms)}</strong></span>
                  <span>TTS<strong>{formatMilliseconds(pipelineTimings.tts_ms)}</strong></span>
                  <span>FLOAT 提交<strong>{formatMilliseconds(pipelineTimings.float_submit_ms)}</strong></span>
                  <span>FLOAT 推理<strong>{pipelineTimings.float_seconds ? `${pipelineTimings.float_seconds.toFixed(2)}s` : '等待完成'}</strong></span>
                  <span>GPU 排队<strong>{pipelineTimings.float_queue_seconds != null ? `${pipelineTimings.float_queue_seconds.toFixed(2)}s` : '暂不可用'}</strong></span>
                  <span>接口总耗时<strong>{formatMilliseconds(pipelineTimings.request_ms)}</strong></span>
                  <span>浏览器往返<strong>{formatMilliseconds(pipelineTimings.client_roundtrip_ms)}</strong></span>
                  <span>视频缓冲<strong>{formatMilliseconds(pipelineTimings.browser_buffer_ms)}</strong></span>
                </div>
              )}
            </div>
          )}
        </section>

        <aside className="conversation-panel">
          <div className="conversation-header">
            <div>
              <span className="eyebrow">LESSON DIALOGUE</span>
              <h2>课堂对话</h2>
            </div>
            <select
              value={lessonId}
              disabled={busy}
              onChange={(event) => {
                const selectedMode = event.target.value
                void selectMode(selectedMode)
              }}
              aria-label="选择教学模式"
            >
              <option value="default">自由问答</option>
              {courseOptions.map((course) => (
                <option key={course.lesson_id} value={course.lesson_id}>{course.title}</option>
              ))}
            </select>
          </div>

          <div className="messages" aria-live="polite">
            {messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <div className="message-meta">
                  <span>{message.role === 'assistant' ? '林老师' : '你'}</span>
                  <time>{message.time}</time>
                </div>
                <p>{message.text}</p>
                {message.sources && message.sources.length > 0 && (
                  <div className="message-sources" aria-label="教材来源">
                    {message.sources.map((source, index) => (
                      <span key={`${message.id}-source-${source.page_number}-${index}`} title={source.snippet}>
                        PDF第{source.page_number}页 · {source.chapter_title}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
            <div ref={messageEndRef} />
          </div>

          <div className="composer">
            {lessonId === 'default'
              && (!dynamicLecture || teachingState?.lesson_phase === 'dynamic_complete') && (
              <button
                className="lecture-start-button"
                type="button"
                disabled={busy || backend !== 'online' || !input.trim()}
                onClick={() => {
                  const topic = input.trim()
                  if (!topic) return
                  setDynamicAutoRun(true)
                  dynamicAutoRunRef.current = true
                  void requestTurn({
                    text: topic,
                    lessonAction: 'dynamic_start',
                    displayUser: true,
                    clearComposer: true,
                  })
                }}
              >
                {teachingState?.lesson_phase === 'dynamic_complete'
                  ? '输入新主题后开始讲授'
                  : '输入主题后开始动态讲授'}
              </button>
            )}
            {lessonId === 'default' && dynamicLecture && teachingState?.lesson_phase !== 'dynamic_complete' && (
              <button
                className="lecture-start-button secondary"
                type="button"
                onClick={() => {
                  if (dynamicAutoRun) {
                    setDynamicAutoRun(false)
                    dynamicAutoRunRef.current = false
                  } else {
                    setDynamicAutoRun(true)
                    dynamicAutoRunRef.current = true
                    if (!busy) void requestTurn({
                      text: '继续动态讲授',
                      lessonAction: 'dynamic_advance',
                      displayUser: false,
                    })
                  }
                }}
              >
                {dynamicAutoRun ? '讲完本段后暂停' : '继续动态讲授'}
              </button>
            )}
            {(guidedLecture || interactivePractice)
              && (!teachingState || teachingState.lesson_phase === 'complete') && (
              <button
                className="lecture-start-button"
                type="button"
                disabled={busy || backend !== 'online'}
                onClick={() => void startFixedLesson()}
              >
                {teachingState?.lesson_phase === 'complete'
                  ? '重新开始课程'
                  : guidedLecture ? '开始连续讲授' : '开始互动练习'}
              </button>
            )}
            {guidedLecture
              && teachingState?.lesson_phase === 'await_checkpoint'
              && !busy
              && teachingState.checkpoint_choices.length > 0 && (
                <div className="checkpoint-card">
                  <span>知识点检查</span>
                  <strong>{teachingState.current_question}</strong>
                  <div className="checkpoint-options">
                    {teachingState.checkpoint_choices.map((choice) => (
                      <button
                        type="button"
                        key={choice}
                        disabled={busy}
                        onClick={() => void requestTurn({
                          text: choice,
                          lessonAction: 'answer',
                          displayUser: true,
                        })}
                      >
                        {choice}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            {interactivePractice
              && teachingState?.lesson_phase === 'await_answer'
              && !busy && (
                <div className="checkpoint-card">
                  <span>当前练习题</span>
                  <strong>{teachingState.current_question}</strong>
                  {teachingState.checkpoint_choices.length > 0 && (
                    <div className="checkpoint-options">
                      {teachingState.checkpoint_choices.map((choice) => (
                        <button
                          type="button"
                          key={choice}
                          disabled={busy}
                          onClick={() => void requestTurn({
                            text: choice,
                            lessonAction: 'answer',
                            displayUser: true,
                          })}
                        >
                          {choice}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            <label className={`video-toggle ${worker !== 'online' || busy ? 'disabled' : ''}`}>
              <input
                type="checkbox"
                checked={videoEnabled}
                disabled={worker !== 'online' || busy}
                onChange={(event) => setRenderVideo(event.target.checked)}
              />
              <span className="toggle-track"><i /></span>
              生成说话视频
            </label>
            <div className="input-row">
              <textarea
                value={input}
                rows={2}
                maxLength={4000}
                disabled={backend !== 'online'}
                placeholder={
                  backend !== 'online'
                    ? '请先启动教学服务…'
                    : busy
                      ? '可以先输入下一问题，讲解结束后发送…'
                      : interactivePractice && teachingState?.lesson_phase === 'await_answer'
                        ? '输入答案，或输入课程相关问题…'
                        : interactivePractice && !teachingState
                          ? '请先点击“开始互动练习”，也可以直接向老师提问…'
                          : '输入你的问题，Enter 发送…'
                }
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
              />
              <button
                className="send-button"
                type="button"
                disabled={!input.trim() || !canSendNow || submissionLocked || backend !== 'online'}
                onClick={() => void sendMessage()}
                aria-label="发送"
              >
                ↑
              </button>
            </div>
            <SpeechInput
              key={`${lessonId}:${threadId || 'new'}`}
              disabled={backend !== 'online' || !['idle', 'error', 'speaking'].includes(stage)
                || submissionLocked || pendingStatus !== 'idle' || dynamicAutoRun}
              onActiveChange={(active) => {
                speechBusyRef.current = active
                setSpeechBusy(active)
              }}
              onText={(text) => {
                setInput((current) => {
                  const joined = current.trimEnd() ? `${current.trimEnd()} ${text}` : text
                  return joined.slice(0, 4000)
                })
              }}
            />
            {interactivePractice && teachingState?.lesson_phase === 'await_answer' && (
              <div className="intent-actions">
                <button
                  type="button"
                  disabled={!input.trim() || !canSendNow || submissionLocked || backend !== 'online'}
                  onClick={() => void sendMessage('answer')}
                >
                  提交答案
                </button>
                <button
                  type="button"
                  disabled={!input.trim() || !canSendNow || submissionLocked || backend !== 'online'}
                  onClick={() => void sendMessage('question')}
                >
                  向老师提问
                </button>
              </div>
            )}
            <p className="composer-hint">
              {pendingKind === 'auto'
                ? pendingStatus === 'ready' ? '下一节视频已准备好 · 当前视频结束后自动衔接' : '正在用当前播放时间预生成下一节'
                : submissionLocked
                ? pendingStatus === 'ready' ? '下一轮已准备好 · 当前回答视频结束后播放' : '已提交一个问题 · 正在后台生成下一轮'
                : stage === 'speaking'
                  ? '可提前提交一个问题 · 将在当前视频播放时后台生成'
                : busy
                  ? '可以先输入内容，当前处理完成后再发送'
                : interactivePractice && teachingState?.lesson_phase === 'await_answer'
                  ? 'Enter 会自动识别明显问句 · 也可以使用上方按钮明确选择'
                  : 'Enter 发送 · Shift + Enter 换行 · 视频生成会调用 TTS'}
            </p>
          </div>
        </aside>
      </section>
      {showCourseManager && (
        <div className="course-import-backdrop" role="presentation">
          <section className="course-import-dialog course-manager-dialog" role="dialog" aria-modal="true" aria-label="课程管理">
            <header>
              <div>
                <span className="eyebrow">COURSE LIBRARY</span>
                <h2>课程管理</h2>
              </div>
              <button type="button" aria-label="关闭" onClick={() => setShowCourseManager(false)}>×</button>
            </header>
            <p className="course-import-intro">
              这里汇总本机所有教材下保存的课程草稿和已发布课程，不需要重新上传PDF。下架会保留草稿；彻底删除只删除课程与草稿，教材PDF和RAG索引仍会保留。
            </p>
            {courseManagerError && <p className="course-import-error">{courseManagerError}</p>}
            {courseManagerLoading && courseProjects.length === 0 && (
              <p className="course-manager-empty">正在读取本机课程…</p>
            )}
            {!courseManagerLoading && courseProjects.length === 0 && !courseManagerError && (
              <p className="course-manager-empty">当前没有已保存的课程草稿。</p>
            )}
            <div className="course-project-list">
              {courseProjects.map((project) => (
                <article key={`${project.import_id}-${project.chapter_index}`}>
                  <header>
                    <div>
                      <span className={project.published ? 'published' : 'draft'}>
                        {project.published ? '已发布' : project.draft_stale ? '草稿已失效' : '本地草稿'}
                      </span>
                      <strong>{project.course_title}</strong>
                    </div>
                    <small>{project.lesson_count}课时</small>
                  </header>
                  <p>{project.filename} · {project.chapter_title}</p>
                  <time>
                    {project.published_at
                      ? `发布于 ${new Date(project.published_at).toLocaleString('zh-CN')}`
                      : `保存于 ${new Date(project.draft_saved_at).toLocaleString('zh-CN')}`}
                  </time>
                  <div className="course-project-actions">
                    <button
                      type="button"
                      disabled={courseManagerLoading || project.draft_stale}
                      onClick={() => void openManagedCourse(project)}
                    >
                      打开并编辑草稿
                    </button>
                    {project.published && (
                      <button
                        type="button"
                        disabled={courseManagerLoading || busy}
                        onClick={() => void unpublishManagedCourse(project)}
                      >
                        下架并保留草稿
                      </button>
                    )}
                    <button
                      className="danger"
                      type="button"
                      disabled={courseManagerLoading || busy}
                      onClick={() => void deleteManagedCourse(project)}
                    >
                      彻底删除课程与草稿
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
      {showCourseImport && (
        <div className="course-import-backdrop" role="presentation">
          <section className="course-import-dialog" role="dialog" aria-modal="true" aria-label="导入教材PDF">
            <header>
              <div>
                <span className="eyebrow">COURSE BUILDER</span>
                <h2>导入教材PDF</h2>
              </div>
              <button type="button" aria-label="关闭" onClick={() => setShowCourseImport(false)}>×</button>
            </header>
            <p className="course-import-intro">
              上传一次完整PDF后，系统会依次尝试书签、正文章标题和编号标题；仍无法识别时按固定页数分组。选择内容单元和生成课程是分开的：结构识别与正文预览不调用模型。
            </p>
            <nav className="course-builder-tabs" aria-label="教材课程工作台">
              <button
                type="button"
                className={courseBuilderView === 'library' ? 'active' : ''}
                onClick={() => setCourseBuilderView('library')}
              >
                1. 教材与章节
              </button>
              <button
                type="button"
                className={courseBuilderView === 'editor' ? 'active' : ''}
                disabled={!coursePreview}
                onClick={() => setCourseBuilderView('editor')}
              >
                2. 课程草稿编辑
              </button>
            </nav>
            {courseBuilderView === 'library' && (
              <>
            <label className="pdf-file-picker">
              <span>选择PDF</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(event) => {
                  setCoursePdf(event.target.files?.[0] || null)
                  setCourseImportRecord(null)
                  setSelectedChapterIndex(null)
                  setCoursePreview(null)
                  setCourseImportError('')
                  setCourseBlueprint(null)
                  setCourseDesignError('')
                  setCourseDesignNotice('')
                  setChapterEditMode(false)
                  setChapterEdits([])
                  setCoursePublishNotice('')
                  setRagStatus(null)
                  setCourseBuilderView('library')
                }}
              />
              <strong>{coursePdf ? `${coursePdf.name} · ${(coursePdf.size / 1024 / 1024).toFixed(1)}MB` : '尚未选择文件'}</strong>
            </label>
            <div className="full-book-actions">
              <button type="button" disabled={!coursePdf || courseUploadLoading} onClick={() => void uploadFullCoursePdf()}>
                {courseUploadLoading ? '正在上传并识别目录…' : '上传整本PDF并识别章节'}
              </button>
              <span>PDF保存在本机 data 目录，不上传到第三方；只有生成课程时才把所选章节正文发送给千问。</span>
            </div>
            {courseImportRecord && (
              <section className="chapter-library">
                <header>
                  <div>
                    <span>已保存整本教材</span>
                    <strong>{courseImportRecord.filename}</strong>
                  </div>
                  <div className="chapter-library-actions">
                    <small>{courseImportRecord.total_pages}页 · {courseImportRecord.chapters.length}个内容单元 · {chapterDetectionLabel(courseImportRecord.chapter_detection)}</small>
                    <button
                      type="button"
                      disabled={ragIndexLoading || Boolean(courseImportRecord.requires_ocr)}
                      onClick={() => void buildTextbookRagIndex()}
                    >
                      {ragIndexLoading
                        ? '正在建立索引…'
                        : ragStatus?.indexed ? '重新建立教材问答索引' : '建立教材问答索引'}
                    </button>
                    <button
                      type="button"
                      disabled={chapterSaveLoading || courseImportLoading}
                      onClick={() => {
                        if (chapterEditMode) {
                          setChapterEdits(courseImportRecord.chapters.map((chapter) => ({ ...chapter })))
                        }
                        setChapterEditMode((value) => !value)
                        setCourseImportError('')
                      }}
                    >
                      {chapterEditMode ? '取消调整' : '调整标题和页码'}
                    </button>
                  </div>
                </header>
                {courseImportRecord.structure_warning && <p>{courseImportRecord.structure_warning}</p>}
                {ragStatus?.indexed && (
                  <p className="rag-status">
                    教材问答已就绪 · {ragStatus.semantic_indexed
                      ? `BM25 + ${ragStatus.embedding_model}混合检索`
                      : ragStatus.embedding_configured ? 'BM25索引 · 重新建立后启用语义检索' : '本地BM25检索'}
                    {' '}· {ragStatus.text_pages || 0}个文字页 · {ragStatus.chunk_count || 0}个片段
                  </p>
                )}
                {ragStatus?.embedding_error && (
                  <p className="course-import-error">
                    语义向量建立失败，当前已自动使用BM25：{ragStatus.embedding_error}
                  </p>
                )}
                {courseImportRecord.requires_ocr && (
                  <p className="course-import-error">这份PDF没有检测到可用文字层，当前版本需要先完成OCR，暂时不能生成课程。</p>
                )}
                {chapterEditMode ? (
                  <div className="chapter-edit-panel">
                    <div className="chapter-edit-list">
                      {chapterEdits.map((chapter, index) => (
                        <div key={chapter.chapter_index}>
                          <span>{chapter.chapter_index}</span>
                          <input
                            aria-label={`第${chapter.chapter_index}个内容单元标题`}
                            value={chapter.title}
                            maxLength={100}
                            onChange={(event) => setChapterEdits((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, title: event.target.value } : item))}
                          />
                          <label>起<input type="number" min="1" max={courseImportRecord.total_pages} value={chapter.start_page} onChange={(event) => setChapterEdits((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, start_page: Number(event.target.value) } : item))} /></label>
                          <label>止<input type="number" min="1" max={courseImportRecord.total_pages} value={chapter.end_page} onChange={(event) => setChapterEdits((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, end_page: Number(event.target.value) } : item))} /></label>
                        </div>
                      ))}
                    </div>
                    <button type="button" disabled={chapterSaveLoading} onClick={() => void saveChapterStructure()}>
                      {chapterSaveLoading ? '正在保存…' : '保存全部章节结构'}
                    </button>
                    <p>页码使用PDF文件页码；内容单元必须按顺序排列且不能重叠。修改过范围的旧课程草稿会保留，但必须重新生成后才能发布。</p>
                  </div>
                ) : (
                  <>
                    <div className="chapter-grid">
                      {courseImportRecord.chapters.map((chapter) => {
                        const draft = courseImportRecord.chapter_drafts.find((item) => item.chapter_index === chapter.chapter_index)
                        const publication = (courseImportRecord.chapter_publications || []).find((item) => item.chapter_index === chapter.chapter_index)
                        return (
                          <button
                            type="button"
                            key={chapter.chapter_index}
                            className={`${selectedChapterIndex === chapter.chapter_index ? 'active' : ''} ${draft ? 'generated' : ''} ${draft?.stale ? 'stale' : ''}`}
                            disabled={courseImportLoading || courseImportRecord.requires_ocr}
                            onClick={() => void previewImportedChapter(chapter)}
                          >
                            <strong>{chapter.title}</strong>
                            <span>PDF第{chapter.start_page}–{chapter.end_page}页 · {chapter.page_count}页</span>
                            {publication
                              ? <em>已发布为固定课程</em>
                              : draft && <em>{draft.stale ? '范围已变更 · 需重新生成' : '已有本地草稿'}</em>}
                          </button>
                        )
                      })}
                    </div>
                    <p>点击一个内容单元只会在本机提取正文；预览确认后再单独触发课程生成。</p>
                  </>
                )}
              </section>
            )}
            <div className="page-range-row">
              <label>起始页<input type="number" min="1" value={courseStartPage} onChange={(event) => setCourseStartPage(event.target.value)} /></label>
              <label>结束页<input type="number" min="1" value={courseEndPage} onChange={(event) => setCourseEndPage(event.target.value)} /></label>
              <button type="button" disabled={!coursePdf || courseImportLoading} onClick={() => void previewCoursePdf()}>
                {courseImportLoading ? '正在提取…' : '按页码快速预览'}
              </button>
            </div>
              </>
            )}
            {courseImportError && <p className="course-import-error">{courseImportError}</p>}
            {coursePublishNotice && <p className="course-import-success">{coursePublishNotice}</p>}
            {courseBuilderView === 'editor' && coursePreview && (
              <div className="course-preview">
                <div className="course-preview-summary">
                  <span>总页数<strong>{coursePreview.total_pages}</strong></span>
                  <span>本次范围<strong>{coursePreview.start_page}–{coursePreview.end_page}</strong></span>
                  <span>文本页<strong>{coursePreview.text_layer_pages}/{coursePreview.preview_page_count}</strong></span>
                  <span>OCR<strong>未使用</strong></span>
                </div>
                <section className="detected-sections">
                  <h3>检测到的章节</h3>
                  {coursePreview.sections.length > 0 ? (
                    <ul>
                      {coursePreview.sections.map((section, index) => (
                        <li key={`${section.page_number}-${section.title}-${index}`} className={`level-${section.level}`}>
                          <span>第{section.page_number}页</span>{section.title}
                        </li>
                      ))}
                    </ul>
                  ) : <p>当前范围没有识别出明确章节标题，可查看逐页文本。</p>}
                </section>
                <section className="page-previews">
                  <h3>逐页文本预览</h3>
                  {coursePreview.pages.map((page) => (
                    <details key={page.page_number} open={page.page_number === coursePreview.start_page}>
                      <summary>
                        第{page.page_number}页 · {page.has_text_layer ? `${page.character_count}字` : '无文本层，已跳过'}
                      </summary>
                      {page.has_text_layer && <pre>{page.text}</pre>}
                    </details>
                  ))}
                </section>
                <section className="course-design-panel">
                  <div className="course-design-heading">
                    <div>
                      <span>AI COURSE DESIGN</span>
                      <h3>根据所选教材生成课程蓝图</h3>
                    </div>
                    <small>
                      识别 {coursePreview.generation_plan?.detected_sections?.length || 0} 个主要小节 ·
                      默认 {coursePreview.generation_plan?.recommended_lesson_count || courseLessonCount} 课时 ·
                      预计调用 {coursePreview.generation_plan?.estimated_model_calls || 1} 次 {courseBlueprint?.generator.model || '千问文本模型'}
                    </small>
                  </div>
                  <p>
                    {coursePreview.chapter
                      ? `当前选择“${coursePreview.chapter.title}”。章节过长时会自动分成${coursePreview.generation_plan?.batch_count || 1}批生成，再合并为一个课程草稿。`
                      : '模型会生成课时目标、可朗读讲稿、选择题和PDF页码出处。'}系统已按篇幅填写建议课时数；减少课时可能导致内容被过度压缩。结果必须人工确认，当前不会发布课程，也不会生成语音或视频。
                  </p>
                  <div className="course-design-controls">
                    <label>目标学习者<input value={courseAudience} maxLength={100} onChange={(event) => setCourseAudience(event.target.value)} /></label>
                    <label>课时数（按小节自动）<input type="number" min="1" max="12" value={courseLessonCount} onChange={(event) => setCourseLessonCount(event.target.value)} /></label>
                    <label>总时长（分钟）<input type="number" min="10" max="360" value={courseTargetMinutes} onChange={(event) => setCourseTargetMinutes(event.target.value)} /></label>
                    <button type="button" disabled={courseDesignLoading || coursePreview.text_layer_pages === 0} onClick={() => void designCourseBlueprint()}>
                      {courseDesignLoading ? '正在分批生成并校验，请勿重复点击…' : coursePreview.chapter ? '生成本章课程草稿' : '生成课程蓝图 Demo'}
                    </button>
                  </div>
                  {courseDesignError && <p className="course-import-error" role="alert">{courseDesignError}</p>}
                  {courseDesignNotice && <p className="course-import-success" role="status">{courseDesignNotice}</p>}
                </section>
                {courseBlueprint && (
                  <section className="course-blueprint">
                    <header>
                      <div>
                        <span>{courseBlueprint.status === 'published' ? '已发布 · 可继续修改并更新' : '可编辑草稿 · 待人工确认'}</span>
                        <input
                          className="blueprint-title-input"
                          value={courseBlueprint.course_title}
                          maxLength={100}
                          onChange={(event) => setCourseBlueprint((current) => current ? { ...current, course_title: event.target.value } : current)}
                        />
                        <textarea
                          className="blueprint-description-input"
                          value={courseBlueprint.course_description}
                          maxLength={500}
                          onChange={(event) => setCourseBlueprint((current) => current ? { ...current, course_description: event.target.value } : current)}
                        />
                      </div>
                      <strong>{courseBlueprint.lessons.length}课时 · 约{courseBlueprint.total_minutes}分钟</strong>
                    </header>
                    <div className="blueprint-objectives">
                      <h4>学习目标</h4>
                      <div className="blueprint-objective-inputs">
                        {courseBlueprint.learning_objectives.map((objective, objectiveIndex) => (
                          <input
                            key={objectiveIndex}
                            value={objective}
                            maxLength={160}
                            onChange={(event) => setCourseBlueprint((current) => current ? {
                              ...current,
                              learning_objectives: current.learning_objectives.map((item, index) => index === objectiveIndex ? event.target.value : item),
                            } : current)}
                          />
                        ))}
                      </div>
                    </div>
                    {Boolean(courseBlueprint.validation_issues?.length) && (
                      <div className="blueprint-validation-issues" role="alert">
                        <strong>这份草稿已保存，但发布前需要修复以下内容</strong>
                        {courseBlueprint.validation_issues?.map((issue, issueIndex) => (
                          <p key={`${issue.path}-${issueIndex}`}>
                            {issue.lesson_index === null ? '课程信息' : `第 ${issue.lesson_index + 1} 课时`}
                            {issue.block_index === null ? '' : ` · 第 ${issue.block_index + 1} 段`}：{issue.message}
                          </p>
                        ))}
                        <small>直接在下方标红区域修改即可。点击发布时会在本地重新校验，不会再次调用千问。</small>
                      </div>
                    )}
                    {courseBlueprint.review_notes.length > 0 && (
                      <div className="blueprint-review-notes">
                        <strong>需要人工确认</strong>
                        {courseBlueprint.review_notes.map((note) => <p key={note}>{note}</p>)}
                      </div>
                    )}
                    <div className="blueprint-lessons">
                      {courseBlueprint.lessons.map((lesson, lessonIndex) => (
                        <details
                          key={lessonIndex}
                          className={courseBlueprint.validation_issues?.some((issue) => issue.lesson_index === lessonIndex) ? 'has-validation-issue' : ''}
                          open={lessonIndex === 0 || courseBlueprint.validation_issues?.some((issue) => issue.lesson_index === lessonIndex)}
                        >
                          <summary>
                            <span>课时 {lessonIndex + 1}</span>
                            <strong>{lesson.title}</strong>
                            <small>第{lesson.source_pages.join('、')}页 · {lesson.estimated_minutes}分钟</small>
                          </summary>
                          <div className="blueprint-lesson-body">
                            <label>课时名称<input value={lesson.title} maxLength={100} onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({ ...current, title: event.target.value }))} /></label>
                            <label>课时目标<textarea value={lesson.objective} maxLength={240} onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({ ...current, objective: event.target.value }))} /></label>
                            {lesson.teaching_blocks.map((block, blockIndex) => (
                              <article
                                key={blockIndex}
                                className={courseBlueprint.validation_issues?.some(
                                  (issue) => issue.lesson_index === lessonIndex && issue.block_index === blockIndex,
                                ) ? 'has-validation-issue' : ''}
                              >
                                <div><strong>{blockIndex + 1}. 讲稿段落</strong><span>来源：第{block.source_pages.join('、')}页</span></div>
                                <input
                                  value={block.title}
                                  maxLength={80}
                                  onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({
                                    ...current,
                                    teaching_blocks: current.teaching_blocks.map((item, index) => index === blockIndex ? { ...item, title: event.target.value } : item),
                                  }))}
                                />
                                <textarea
                                  value={block.script}
                                  maxLength={800}
                                  onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({
                                    ...current,
                                    teaching_blocks: current.teaching_blocks.map((item, index) => index === blockIndex ? { ...item, script: event.target.value } : item),
                                  }))}
                                />
                              </article>
                            ))}
                            <div className={`blueprint-checkpoint ${courseBlueprint.validation_issues?.some(
                              (issue) => issue.lesson_index === lessonIndex && issue.path.includes('.checkpoint'),
                            ) ? 'has-validation-issue' : ''}`}>
                              <span>检查题 · 第{lesson.checkpoint.source_pages.join('、')}页</span>
                              <input value={lesson.checkpoint.question} maxLength={300} onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({ ...current, checkpoint: { ...current.checkpoint, question: event.target.value } }))} />
                              {lesson.checkpoint.choices.map((choice, choiceIndex) => (
                                <input
                                  key={choiceIndex}
                                  value={choice}
                                  maxLength={120}
                                  onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => {
                                    const choices = current.checkpoint.choices.map((item, index) => index === choiceIndex ? event.target.value : item)
                                    const correctAnswer = current.checkpoint.correct_answer === choice ? event.target.value : current.checkpoint.correct_answer
                                    return { ...current, checkpoint: { ...current.checkpoint, choices, correct_answer: correctAnswer } }
                                  })}
                                />
                              ))}
                              <label>正确答案<select value={lesson.checkpoint.correct_answer} onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({ ...current, checkpoint: { ...current.checkpoint, correct_answer: event.target.value } }))}>{lesson.checkpoint.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>
                              <label>答案说明<textarea value={lesson.checkpoint.explanation} maxLength={500} onChange={(event) => updateBlueprintLesson(lessonIndex, (current) => ({ ...current, checkpoint: { ...current.checkpoint, explanation: event.target.value } }))} /></label>
                            </div>
                          </div>
                        </details>
                      ))}
                    </div>
                    <p className="course-preview-note">
                      引用页码覆盖：{blueprintCoveredPages.length}/{courseBlueprint.grounding.source_pages.length}页（{blueprintCoveragePercent}%）。
                      已校验所有引用均位于本次所选的第{courseBlueprint.grounding.source_pages.join('、')}页；页码覆盖不等于知识点完整，低于65%时建议增加课时数重新生成。
                    </p>
                    {courseBlueprint.draft && (
                      <div className="course-publish-actions">
                        <button type="button" disabled={coursePublishLoading} onClick={() => void publishCourseBlueprint()}>
                          {coursePublishLoading
                            ? '正在校验并发布…'
                            : courseBlueprint.status === 'published'
                              ? '保存修改并更新固定课程'
                              : '确认审核并发布为固定课程'}
                        </button>
                        {(courseImportRecord?.chapter_publications || []).some(
                          (item) => item.chapter_index === selectedChapterIndex,
                        ) && (
                          <button
                            className="secondary"
                            type="button"
                            disabled={coursePublishLoading || courseUnpublishLoading}
                            onClick={() => void unpublishCourseBlueprint()}
                          >
                            {courseUnpublishLoading ? '正在下架…' : '下架课程并保留草稿'}
                          </button>
                        )}
                        <span>发布会再次校验全部必填字段、三选一答案和PDF页码，但不会调用千问、TTS或FLOAT。</span>
                      </div>
                    )}
                  </section>
                )}
                <p className="course-preview-note">PDF上传、章节识别和正文预览不调用模型；只有点击生成课程草稿才会按显示的批次数调用文本模型。</p>
              </div>
            )}
          </section>
        </div>
      )}
    </main>
  )
}

export default App
