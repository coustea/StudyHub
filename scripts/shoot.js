// 设计自检截图：真实浏览器渲染，覆盖浅色/深色与桌面/移动。
// 用法：node scripts/shoot.js [baseUrl]
const path = require('node:path')
const fs = require('node:fs')
const { chromium } = require('playwright-core')

const CHROME = path.join(
  process.env.LOCALAPPDATA,
  'ms-playwright', 'chromium-1243', 'chrome-win64', 'chrome.exe',
)
const baseUrl = process.argv[2] || 'http://127.0.0.1:3021'
const outDir = path.join(__dirname, '..', '.shots')
fs.mkdirSync(outDir, { recursive: true })

const shots = [
  { name: 'home-light', url: '/', theme: 'light', w: 1440, h: 1100, full: true },
  { name: 'home-dark', url: '/', theme: 'dark', w: 1440, h: 1100, full: true },
  { name: 'home-mobile', url: '/', theme: 'light', w: 390, h: 844, full: true },
  { name: 'home-mobile-dark', url: '/', theme: 'dark', w: 390, h: 844, full: true },
  { name: 'home-auth-light', url: '/', theme: 'light', w: 1440, h: 1100, full: true, auth: true },
  { name: 'home-auth-dark', url: '/', theme: 'dark', w: 1440, h: 1100, full: true, auth: true },
  { name: 'home-auth-mobile', url: '/', theme: 'light', w: 390, h: 844, full: true, auth: true },
  { name: 'reader-light', url: '/p/1', theme: 'light', w: 1440, h: 1200, full: true },
  { name: 'reader-dark', url: '/p/1', theme: 'dark', w: 1440, h: 1200, full: true },
  { name: 'reader-mobile', url: '/p/1', theme: 'light', w: 390, h: 844, full: true },
  { name: 'login-dark', url: '/login', theme: 'dark', w: 1440, h: 900, full: false },
  { name: 'search-light', url: '/search?q=Go', theme: 'light', w: 1440, h: 900, full: true },
  { name: 'daily-light', url: '/daily', theme: 'light', w: 1440, h: 1100, full: true, auth: true },
  { name: 'daily-dark', url: '/daily', theme: 'dark', w: 1440, h: 1100, full: true, auth: true },
  { name: 'daily-mobile', url: '/daily', theme: 'light', w: 390, h: 844, full: true, auth: true },
  { name: 'trash-light', url: '/trash', theme: 'light', w: 1440, h: 900, full: true, auth: true },
  { name: 'editor-light', url: '/edit', theme: 'light', w: 1440, h: 1100, full: true, auth: true },
  { name: 'settings-light', url: '/settings', theme: 'light', w: 1440, h: 900, full: true, auth: true },
  { name: 'settings-dark', url: '/settings', theme: 'dark', w: 1440, h: 900, full: true, auth: true },
  { name: 'settings-mobile', url: '/settings', theme: 'light', w: 390, h: 844, full: true, auth: true },
]

async function login(base) {
  const username = process.env.SHOOT_USER || 'coustea'
  const password = process.env.SHOOT_PASS || 'coustea'
  const res = await fetch(`${base}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(`截图登录失败（${res.status}），可用 SHOOT_USER / SHOOT_PASS 覆盖`)
  const data = await res.json()
  return data.token
}

;(async () => {
  const browser = await chromium.launch({ executablePath: CHROME })
  let token = ''
  if (shots.some((shot) => shot.auth)) token = await login(baseUrl)
  let failures = 0
  for (const shot of shots) {
    const context = await browser.newContext({
      viewport: { width: shot.w, height: shot.h },
      deviceScaleFactor: 1,
      colorScheme: shot.theme,
    })
    await context.addInitScript(({ theme, token }) => {
      try {
        localStorage.setItem('notes_theme', theme)
        if (token) localStorage.setItem('notes_token', token)
      } catch (e) { /* ignore */ }
    }, { theme: shot.theme, token: shot.auth ? token : '' })
    const page = await context.newPage()
    const errors = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    page.on('pageerror', (error) => errors.push(String(error)))
    try {
      const response = await page.goto(baseUrl + shot.url, { waitUntil: 'networkidle', timeout: 30000 })
      await page.waitForTimeout(700)
      await page.screenshot({
        path: path.join(outDir, `${shot.name}.png`),
        fullPage: shot.full,
      })
      const status = response ? response.status() : 'n/a'
      console.log(`OK   ${shot.name} [${status}] errors=${errors.length}`)
      if (errors.length) {
        failures += 1
        console.log('   ' + errors.slice(0, 3).join('\n   '))
      }
    } catch (error) {
      failures += 1
      console.log(`FAIL ${shot.name}: ${error.message}`)
    }
    await context.close()
  }
  await browser.close()
  console.log(failures ? `\n${failures} 个页面有控制台错误` : '\n没有控制台错误')
})()
