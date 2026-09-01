// AudioWorklet: capture mono PCM without playing microphone audio to speakers.
class PCMRecorder extends AudioWorkletProcessor {
  constructor() {
    super()
    this.active = true
    this.frames = 0
    this.buffer = new Float32Array(2048)
    this.used = 0
    this.port.onmessage = (event) => {
      if (event.data === 'stop') this.finish()
    }
  }

  finish() {
    if (!this.active) return
    this.flush()
    this.active = false
    this.port.postMessage({ finished: true })
  }

  flush() {
    if (!this.used) return
    const pcm = this.buffer.slice(0, this.used)
    this.port.postMessage({ pcm }, [pcm.buffer])
    this.used = 0
  }

  process(inputs) {
    const channel = inputs[0]?.[0]
    if (this.active && channel) {
      const count = Math.min(channel.length, 60 * sampleRate - this.frames)
      if (count > 0) {
        for (let i = 0; i < count; i++) {
          this.buffer[this.used++] = channel[i]
          if (this.used === this.buffer.length) this.flush()
        }
        this.frames += count
      }
      if (this.frames >= 60 * sampleRate) this.finish()
    }
    // Output buffers remain zero; a connected output keeps the worklet scheduled.
    return true
  }
}

registerProcessor('pcm-recorder', PCMRecorder)
