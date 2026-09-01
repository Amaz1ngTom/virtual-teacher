import { useEffect, useRef, useState } from 'react'
import { AudioRecorder } from './audioRecorder'

type Phase = 'idle' | 'permission' | 'recording' | 'recognizing'
type ASRStatus = { available: boolean; loaded: boolean; message: string }

export function SpeechInput({ disabled, onText, onActiveChange }: {
  disabled: boolean
  onText: (text: string) => void
  onActiveChange: (active: boolean) => void
}) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [seconds, setSeconds] = useState(0)
  const [status, setStatus] = useState<ASRStatus | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const callbacks = useRef({ onText, onActiveChange })
  useEffect(() => { callbacks.current = { onText, onActiveChange } }, [onText, onActiveChange])
  const recorder = useRef<AudioRecorder | null>(null)
  const controller = useRef<AbortController | null>(null)
  const version = useRef(0)
  const phaseRef = useRef<Phase>('idle')

  const updatePhase = (next: Phase) => {
    phaseRef.current = next
    setPhase(next)
    callbacks.current.onActiveChange(next !== 'idle')
  }

  useEffect(() => {
    const abort = new AbortController()
    void fetch('/v1/asr/status', { signal: abort.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('ASR接口不可用，请重启更新后的教学服务。')
        const result = await response.json() as ASRStatus
        if (!abort.signal.aborted) setStatus(result)
      })
      .catch((caught) => {
        if (!abort.signal.aborted) setStatus({ available: false, loaded: false, message: String(caught.message) })
      })
    return () => abort.abort()
  }, [])

  useEffect(() => {
    const cleanup = () => {
      version.current++
      controller.current?.abort()
      recorder.current?.dispose()
      recorder.current = null
      phaseRef.current = 'idle'
      callbacks.current.onActiveChange(false)
    }
    return cleanup
  }, [])

  const cancel = () => {
    version.current++
    controller.current?.abort()
    recorder.current?.dispose()
    recorder.current = null
    updatePhase('idle')
    setError('')
    setNotice('已取消，输入框内容未改变。')
  }

  useEffect(() => {
    const onPageHide = () => {
      version.current++
      recorder.current?.dispose()
      controller.current?.abort()
      recorder.current = null
      phaseRef.current = 'idle'
      callbacks.current.onActiveChange(false)
      setPhase('idle')
    }
    window.addEventListener('pagehide', onPageHide)
    return () => window.removeEventListener('pagehide', onPageHide)
  }, [])

  const stop = async () => {
    if (phaseRef.current !== 'recording' || !recorder.current) return
    const current = version.current
    const capture = recorder.current
    updatePhase('recognizing')
    const abort = new AbortController()
    controller.current = abort
    const timeout = window.setTimeout(() => abort.abort(), 120000)
    try {
      const wav = await capture.stop()
      if (current !== version.current) return
      recorder.current = null
      const response = await fetch('/v1/asr/transcribe', {
        method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav, signal: abort.signal,
      })
      const result = await response.json() as { text?: string; detail?: string; elapsed_ms?: number }
      if (!response.ok) throw new Error(result.detail || '语音识别失败，请重试。')
      if (current !== version.current) return
      if (result.text?.trim()) {
        callbacks.current.onText(result.text.trim())
        setNotice(`已填入输入框，请检查后发送 · 本地识别 ${((result.elapsed_ms || 0) / 1000).toFixed(1)} 秒`)
      } else setNotice('没有识别到语音，请靠近麦克风后重试。')
    } catch (caught) {
      if (current === version.current) {
        setError(abort.signal.aborted ? '识别等待超时，请稍后重试较短录音。' : caught instanceof Error ? caught.message : '语音识别失败。')
      }
    } finally {
      window.clearTimeout(timeout)
      if (current === version.current) updatePhase('idle')
    }
  }

  const start = async () => {
    if (disabled || !status?.available || phaseRef.current !== 'idle') return
    const current = ++version.current
    updatePhase('permission')
    setNotice('')
    setError('')
    setSeconds(0)
    const capture = new AudioRecorder()
    recorder.current = capture
    try {
      await capture.start(setSeconds, () => void stop())
      if (current === version.current) updatePhase('recording')
    } catch (caught) {
      capture.dispose()
      if (current !== version.current) return
      const name = caught instanceof Error ? caught.name : ''
      setError(name === 'NotAllowedError'
        ? '麦克风权限被拒绝，请在浏览器地址栏允许此网站使用麦克风。'
        : name === 'NotFoundError' ? '没有找到麦克风，请连接设备后重试。'
        : name === 'NotReadableError' ? '麦克风无法使用，请检查设备是否被其他程序占用。'
        : caught instanceof Error ? caught.message : '录音启动失败。')
      updatePhase('idle')
    }
  }

  const active = phase !== 'idle'
  return (
    <div className="speech-input">
      <div className="speech-actions">
        <button
          type="button"
          className={`microphone-button ${phase === 'recording' ? 'recording' : ''}`}
          disabled={phase === 'permission' || phase === 'recognizing' || (!active && (disabled || !status?.available))}
          onClick={() => void (phase === 'recording' ? stop() : start())}
          aria-label={phase === 'recording' ? '停止录音并识别' : '开始语音输入'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <rect x="9" y="2" width="6" height="13" rx="3" />
            <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" />
          </svg>
          {phase === 'recording' ? `停止并识别 · ${seconds}/60秒`
            : phase === 'permission' ? '等待麦克风授权…'
            : phase === 'recognizing' ? '本地识别中…' : '语音输入'}
        </button>
        {active && <button type="button" className="speech-cancel" onClick={cancel}>取消</button>}
      </div>
      <p className={error ? 'speech-status speech-error' : 'speech-status'} role="status" aria-live="polite">
        {error || (phase === 'recording' ? '请讲话，停止后转文字；播放视频时录音建议佩戴耳机。'
          : phase === 'recognizing' ? '麦克风已关闭 · 首次加载稍慢 · 不调用云端API'
          : phase === 'permission' ? '只在录音期间使用麦克风，可以随时取消。'
          : notice || status?.message || '正在检查本地语音输入…')}
      </p>
    </div>
  )
}
