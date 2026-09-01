export function encodeWav(chunks: Float32Array[], sampleRate: number): Blob {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0)
  const buffer = new ArrayBuffer(44 + length * 2)
  const view = new DataView(buffer)
  const write = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i))
  }
  write(0, 'RIFF')
  view.setUint32(4, 36 + length * 2, true)
  write(8, 'WAVE')
  write(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, length * 2, true)
  let offset = 44
  for (const chunk of chunks) {
    for (const sample of chunk) {
      const clamped = Math.max(-1, Math.min(1, sample))
      view.setInt16(offset, Math.round(clamped * (clamped < 0 ? 32768 : 32767)), true)
      offset += 2
    }
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

export class AudioRecorder {
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private node: AudioWorkletNode | null = null
  private chunks: Float32Array[] = []
  private rate = 16000
  private disposed = false
  private finishRequested = false
  private finished: (() => void) | null = null
  private frames = 0

  async start(onSeconds: (seconds: number) => void, onLimit: () => void) {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
      throw new Error('录音需要支持麦克风的浏览器，请用Chrome/Edge打开 localhost 或HTTPS页面。')
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    if (this.disposed) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }
    this.stream = stream
    this.context = new AudioContext()
    this.rate = this.context.sampleRate
    await this.context.audioWorklet.addModule('/pcm-recorder.js')
    if (this.disposed) return
    this.node = new AudioWorkletNode(this.context, 'pcm-recorder')
    this.node.port.onmessage = (event: MessageEvent<{ pcm?: Float32Array; finished?: boolean }>) => {
      if (this.disposed) return
      if (event.data.pcm) {
        this.chunks.push(event.data.pcm)
        this.frames += event.data.pcm.length
        onSeconds(Math.floor(this.frames / this.rate))
      }
      if (event.data.finished) {
        if (this.finishRequested) this.finished?.()
        else {
          this.finishRequested = true
          onLimit()
        }
      }
    }
    this.source = this.context.createMediaStreamSource(stream)
    this.source.connect(this.node)
    this.node.connect(this.context.destination)
    await this.context.resume()
  }

  async stop(): Promise<Blob> {
    if (!this.finishRequested && this.node) {
      this.finishRequested = true
      // The acknowledgement follows the last PCM message, so no tail is lost.
      await new Promise<void>((resolve) => {
        const timeout = window.setTimeout(resolve, 1000)
        this.finished = () => { window.clearTimeout(timeout); resolve() }
        this.node?.port.postMessage('stop')
      })
    }
    const blob = encodeWav(this.chunks, this.rate)
    this.dispose()
    return blob
  }

  dispose() {
    this.disposed = true
    this.finished?.()
    this.stream?.getTracks().forEach((track) => track.stop())
    this.source?.disconnect()
    this.node?.disconnect()
    if (this.node) this.node.port.onmessage = null
    if (this.context && this.context.state !== 'closed') void this.context.close().catch(() => {})
    this.chunks = []
  }
}
