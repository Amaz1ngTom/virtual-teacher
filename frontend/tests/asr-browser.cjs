// Optional browser acceptance: npm install is NOT needed in the runtime app.
// Supply Playwright via NODE_PATH, ASR_TEST_URL and ASR_TEST_WAV. No paid requests.
const assert = require('node:assert/strict')
const path = require('node:path')
const { chromium } = require('playwright')

async function main() {
  const base = process.env.ASR_TEST_URL || 'http://127.0.0.1:8002'
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Local test server only')
  const wav = path.resolve(process.env.ASR_TEST_WAV || '../../models/sensevoice-small-int8/test_wavs/zh.wav')
  const browser = await chromium.launch({
    channel: process.env.ASR_TEST_BROWSER || 'msedge', headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', `--use-file-for-fake-audio-capture=${wav}`],
  })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
  let paidRequests = 0
  await context.route('**/*', async (route) => {
    const request = route.request()
    if (request.method() === 'POST' && !request.url().endsWith('/v1/asr/transcribe')) {
      paidRequests++
      return route.abort()
    }
    if (request.url().endsWith('/health/float')) return route.fulfill({ status: 503, json: { detail: 'Not needed for ASR' } })
    return route.continue()
  })
  // Observe tracks, while still exercising real browser getUserMedia/AudioWorklet.
  await context.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    window.__asrTracks = []
    navigator.mediaDevices.getUserMedia = async (...args) => {
      const stream = await original(...args)
      window.__asrTracks.push(...stream.getTracks())
      return stream
    }
  })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.setDefaultTimeout(15000)
  const mic = () => page.getByRole('button', { name: '开始语音输入', exact: true })
  const idle = async () => {
    await mic().waitFor()
    await page.waitForFunction(() => !document.querySelector('.microphone-button')?.disabled)
  }
  const tracksStopped = async () => {
    await page.waitForFunction(() => window.__asrTracks.every((track) => track.readyState === 'ended'))
  }
  try {
    await page.goto(base)
    await idle()
    const input = page.locator('textarea').first()
    await input.fill('已有文字')
    await mic().click()
    await page.getByRole('button', { name: '停止录音并识别' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '发送', exact: true }).isEnabled(), false)
    await page.waitForTimeout(6500)
    const responsePromise = page.waitForResponse((response) => response.url().endsWith('/v1/asr/transcribe'))
    await page.getByRole('button', { name: '停止录音并识别' }).click()
    await tracksStopped()
    const response = await responsePromise
    assert.equal(response.status(), 200)
    const result = await response.json()
    assert.ok(result.text.length > 0, 'Actual model must recognize the sample')
    await idle()
    assert.equal(await input.inputValue(), `已有文字 ${result.text}`)
    assert.equal(paidRequests, 0)
    console.log('PASS real WAV capture -> CPU ASR -> append without sending:', JSON.stringify(result))
    await page.screenshot({ path: path.resolve('../outputs/asr-browser.png'), fullPage: true })

    const previous = await input.inputValue()
    let requests = 0
    page.on('request', (request) => { if (request.url().endsWith('/v1/asr/transcribe')) requests++ })
    await mic().click()
    await page.getByRole('button', { name: '停止录音并识别' }).waitFor()
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await tracksStopped()
    await idle()
    assert.equal(await input.inputValue(), previous)
    assert.equal(requests, 0)
    console.log('PASS cancel recording releases microphone and never uploads')

    // Cancellation after upload must discard a late result.
    await page.route('**/v1/asr/transcribe', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 700))
      await route.fulfill({ json: { text: '不应出现的迟到结果', elapsed_ms: 1 } }).catch(() => {})
    })
    await mic().click()
    await page.getByRole('button', { name: '停止录音并识别' }).waitFor()
    await page.waitForTimeout(400)
    await page.getByRole('button', { name: '停止录音并识别' }).click()
    await page.waitForFunction(() => document.querySelector('.microphone-button')?.textContent.includes('识别中'))
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await page.waitForTimeout(1000)
    assert.equal(await input.inputValue(), previous)
    await tracksStopped()
    console.log('PASS cancel recognition discards stale results')
    await page.unroute('**/v1/asr/transcribe')

    await page.route('**/v1/asr/transcribe', (route) => route.fulfill({ json: { text: '', elapsed_ms: 1 } }))
    await mic().click()
    await page.getByRole('button', { name: '停止录音并识别' }).waitFor()
    await page.waitForTimeout(400)
    await page.getByRole('button', { name: '停止录音并识别' }).click()
    await page.getByText('没有识别到语音，请靠近麦克风后重试。', { exact: true }).waitFor()
    assert.equal(await input.inputValue(), previous)
    await tracksStopped()
    console.log('PASS empty recognition preserves the existing draft')
    await page.unroute('**/v1/asr/transcribe')

    // Cancelling while the permission dialog is pending must stop a late stream.
    await page.evaluate(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
      window.__originalGetUserMedia = original
      navigator.mediaDevices.getUserMedia = (...args) => new Promise((resolve, reject) => {
        window.__grantLatePermission = () => original(...args).then(resolve, reject)
      })
    })
    await mic().click()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await page.evaluate(() => window.__grantLatePermission())
    await tracksStopped()
    assert.equal(await input.inputValue(), previous)
    await idle()
    console.log('PASS cancelling pending permission releases a late microphone stream')

    await page.evaluate(() => {
      navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') }
    })
    await mic().click()
    await page.getByText('麦克风权限被拒绝，请在浏览器地址栏允许此网站使用麦克风。', { exact: true }).waitFor()
    await idle()
    assert.equal(await input.inputValue(), previous)
    console.log('PASS denied microphone permission preserves keyboard input')
    assert.equal(paidRequests, 0)
    assert.deepEqual(errors, [])
    console.log('All browser ASR checks passed; LLM/TTS/FLOAT POST calls: 0')
  } finally {
    await browser.close()
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
