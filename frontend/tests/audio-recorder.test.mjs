import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { encodeWav } from '../src/audioRecorder.ts'

test('WAV encoder writes mono PCM16 headers and clips safely', async () => {
  const wav = encodeWav([new Float32Array([-2, -1, 0]), new Float32Array([1, 2])], 48000)
  const bytes = await wav.arrayBuffer()
  const view = new DataView(bytes)
  assert.equal(new TextDecoder().decode(bytes.slice(0, 4)), 'RIFF')
  assert.equal(view.getUint16(22, true), 1)
  assert.equal(view.getUint32(24, true), 48000)
  assert.equal(view.getUint16(34, true), 16)
  assert.equal(view.getUint32(40, true), 10)
  assert.deepEqual(Array.from({ length: 5 }, (_, i) => view.getInt16(44 + i * 2, true)), [-32768, -32768, 0, 32767, 32767])
})

function processor() {
  let Constructor
  const messages = []
  vm.runInNewContext(readFileSync(new URL('../public/pcm-recorder.js', import.meta.url), 'utf8'), {
    sampleRate: 16000,
    AudioWorkletProcessor: class { port = { postMessage: (message) => messages.push(message) } },
    registerProcessor: (_, implementation) => { Constructor = implementation },
  })
  return { recorder: new Constructor(), messages }
}

test('worklet flushes the short tail before acknowledging stop', () => {
  const { recorder, messages } = processor()
  recorder.process([[new Float32Array(128).fill(0.5)]])
  assert.equal(messages.length, 0)
  recorder.port.onmessage({ data: 'stop' })
  assert.equal(messages[0].pcm.length, 128)
  assert.equal(messages[1].finished, true)
  recorder.process([[new Float32Array(128)]])
  assert.equal(messages.length, 2)
})

test('worklet limits recordings to exactly 60 seconds even without a UI timer', () => {
  const { recorder, messages } = processor()
  for (let i = 0; i < 8000; i++) recorder.process([[new Float32Array(128)]])
  assert.equal(messages.reduce((frames, message) => frames + (message.pcm?.length || 0), 0), 60 * 16000)
  assert.equal(messages.filter((message) => message.finished).length, 1)
})
