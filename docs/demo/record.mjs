// Records the demo scenes as frames by driving a real Chrome at real time, so the lightning plays as it does for a user.
// Usage: node docs/demo/record.mjs <baseUrl> <outDir> [stillsDir]   (needs: cd docs/demo && npm install)
// Scenes a to c: guardrail, human gate, attack lab. Scenes d to f: live run on a claim with a photo, observability tab, architecture tab.
// Run it against the deployed site while the agents are live, so every frame is a real run.
import puppeteer from 'puppeteer-core'
import fs from 'node:fs'

const [base = 'http://localhost:5173', out = 'frames', stills = 'stills'] = process.argv.slice(2)
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
fs.mkdirSync(out, { recursive: true })
fs.mkdirSync(stills, { recursive: true })

const only = process.env.ONLY || ''
const on = (s) => !only || only.includes(s)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
// At this window size the page itself scrolls, not an inner container.
const scrollMain = (page, dy) => page.evaluate((dy) => window.scrollBy({ top: dy, behavior: 'smooth' }), dy)

let n = 0
let scene = 'a'

async function snap(page) {
  const f = `${out}/${scene}_${String(n++).padStart(4, '0')}.png`
  await page.screenshot({ path: f, type: 'png' })  // lossless: JPEG noise differs on every frame and ruins a GIF
}

async function still(page, name) {
  await page.screenshot({ path: `${stills}/${name}.png`, type: 'png' })
}

// Capture frames continuously until the condition is true (or timeout), then hold for a moment.
async function film(page, until, { timeout = 90000, hold = 1500 } = {}) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    await snap(page)
    if (await until().catch(() => false)) break
  }
  const t1 = Date.now()
  while (Date.now() - t1 < hold) await snap(page)
}

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', defaultViewport: { width: 1180, height: 900, deviceScaleFactor: 1 }, args: ['--disable-gpu', '--hide-scrollbars'] })
const page = await browser.newPage()
const has = (sel) => () => page.$(sel).then(Boolean)

if (on('a')) {
// Scene A: a prompt injection attack is caught, and the claim is denied.
scene = 'a'
await page.goto(`${base}/?claim=CLM-2026044`, { waitUntil: 'networkidle0' })
await sleep(600)
await film(page, async () => false, { timeout: 1200, hold: 0 })
await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Run agents'))?.click())
await film(page, has('.verdict'), { hold: 3200 })

}
if (on('b')) {
// Scene B: a high value claim needs a senior adjuster (four eyes), the human decides, the decision is logged.
scene = 'b'
await page.goto(`${base}/?claim=${process.env.HV_CLAIM || 'CLM-2026043'}`, { waitUntil: 'networkidle0' })
await sleep(500)
await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Run agents'))?.click())
await film(page, has('.verdict'), { hold: 2400 })
await page.evaluate(() => document.querySelector('.hitl')?.scrollIntoView({ block: 'center' }))
await film(page, async () => false, { timeout: 1500, hold: 0 })
await page.type('.hitl textarea', 'Reviewed estimate and photos, repairs are consistent.', { delay: 12 })
await film(page, async () => false, { timeout: 1200, hold: 0 })
await page.select('select[aria-label="Role"]', 'senior')
await film(page, async () => false, { timeout: 1500, hold: 0 })
await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Accept recommendation'))?.click())
await film(page, has('.outcome'), { hold: 3000 })

}
if (on('c')) {
// Scene C: the attack lab.
scene = 'c'
await page.goto(`${base}/?tab=security`, { waitUntil: 'networkidle0' })
await sleep(700)
await film(page, async () => false, { timeout: 1500, hold: 0 })
await page.select('select[aria-label="Sample attacks"]', 'HID-05')
await film(page, async () => false, { timeout: 1500, hold: 0 })
await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Scan with guardrail'))?.click())
await film(page, has('.scan'), { hold: 3200 })

}
if (on('d')) {
// Scene D: a live run on a claim with a real photo. Bedrock Data Automation read the photo, the agents use memory and MCP tools, and risk signals appear.
scene = 'd'
await page.goto(`${base}/?claim=CLM-2026016`, { waitUntil: 'networkidle0' })
await sleep(700)
await still(page, 'workbench_before_run')
await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Run agents'))?.click())
await film(page, async () => false, { timeout: 9000, hold: 0 })
await still(page, 'workbench_live_run')
await film(page, has('.verdict'), { hold: 2200 })
await still(page, 'decision_panel')
await page.evaluate(() => document.querySelector('.packet')?.scrollIntoView({ block: 'start' }))
await film(page, async () => false, { timeout: 2500, hold: 0 })
await still(page, 'claim_packet_photo')
await page.evaluate(() => document.querySelector('.signals')?.scrollIntoView({ block: 'center' }))
await film(page, async () => false, { timeout: 2800, hold: 0 })
await still(page, 'risk_signals')
await page.evaluate(() => document.querySelector('.hitl')?.scrollIntoView({ block: 'center' }))
await film(page, async () => false, { timeout: 2500, hold: 0 })
await still(page, 'human_gate')

}
if (on('e')) {
// Scene E: the observability tab, with cost, latency, alerts and review statistics from the recorded runs. The scroll is stepped so every position is captured.
scene = 'e'
await page.goto(`${base}/?tab=observability`, { waitUntil: 'networkidle0' })
await sleep(900)
await film(page, async () => false, { timeout: 1800, hold: 0 })
await still(page, 'observability_top')
for (let i = 0; i < 20; i++) { await page.evaluate(() => window.scrollBy(0, 60)); await sleep(90); await snap(page) }
await still(page, 'observability_cost')
await film(page, async () => false, { timeout: 1500, hold: 0 })
}
if (on('f')) {
// Scene F: the architecture tab.
scene = 'f'
await page.goto(`${base}/?tab=architecture`, { waitUntil: 'networkidle0' })
await sleep(900)
await film(page, async () => false, { timeout: 3500, hold: 600 })
await still(page, 'architecture_tab')

await page.goto(`${base}/?tab=security`, { waitUntil: 'networkidle0' })
await sleep(900)
await still(page, 'security_tab')

}
await browser.close()
console.log('frames:', n)
