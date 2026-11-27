const express = require('express')
const cors = require('cors')
const helmet = require('helmet')
const compression = require('compression')
const rateLimit = require('express-rate-limit')
const bcrypt = require('bcryptjs')
const jwt = require('jsonwebtoken')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const matter = require('gray-matter')
const OpenAI = require('openai')
const net = require('node:net')

// 极简 .env 加载器：不为了 20 行解析引入 dotenv 依赖。
// 必须在 require('./db') 之前执行，因为 db.js 的 DATA_DIR 也从环境变量来。
// 规则与 .env.example 的约定一致：不写行尾注释、值不加引号（除非含空格）。
const ROOT_DIR = path.join(__dirname, '..')
function loadEnvFile(file) {
  if (!fs.existsSync(file)) return
  for (const rawLine of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 1) continue
    const key = line.slice(0, eq).trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue
    // 真实环境变量优先，方便 `PORT=4000 node server/index.js` 临时覆盖
    if (process.env[key] !== undefined) continue
    let value = line.slice(eq + 1).trim()
    if (value.length > 1) {
      const first = value[0]
      if ((first === '"' || first === "'") && value.endsWith(first)) value = value.slice(1, -1)
    }
    process.env[key] = value
  }
}
loadEnvFile(process.env.ENV_FILE || path.join(ROOT_DIR, '.env'))

// .env 里写的 DATA_DIR 可能是相对路径（示例里就是 /opt/md-notes/data 这种绝对路径，
// 但本地开发常写 ./data）。统一按项目根目录解析，避免从别的目录启动时把库建到别处。
if (process.env.DATA_DIR && !path.isAbsolute(process.env.DATA_DIR)) {
  process.env.DATA_DIR = path.resolve(ROOT_DIR, process.env.DATA_DIR)
}

const { db, DATA_DIR, closeDatabase } = require('./db')

const UPLOAD_DIR = path.join(DATA_DIR, 'uploads')
fs.mkdirSync(UPLOAD_DIR, { recursive: true })

const MIME_EXT = {
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/gif': '.gif',
  'image/webp': '.webp',
  'application/pdf': '.pdf',
}

const SITE_NAME = process.env.SITE_NAME || '拾页 · Folio'
const SITE_DESCRIPTION = process.env.SITE_DESCRIPTION || '教程、笔记与代码示例，按项目归档。'
const SITE_OWNER = process.env.SITE_OWNER === undefined ? 'coustea' : process.env.SITE_OWNER
// 默认只信任一层反向代理（nginx / docker compose 的网关）。
// 直接对公网暴露时设为 false，避免客户端伪造 X-Forwarded-For 绕过限流。
const TRUST_PROXY = process.env.TRUST_PROXY === undefined ? '1' : process.env.TRUST_PROXY
const IS_PROD = process.env.NODE_ENV === 'production'

const app = express()
app.disable('x-powered-by')
app.set('trust proxy', TRUST_PROXY === 'false' ? false : (/^\d+$/.test(TRUST_PROXY) ? Number(TRUST_PROXY) : TRUST_PROXY))

const allowedOrigins = String(process.env.ALLOWED_ORIGINS || '')
  .split(',')
  .map((origin) => origin.trim())
  .filter(Boolean)

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      // Markdown 预览与编辑器会写入内联样式，图片允许 data:/blob: 以便粘贴预览
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", 'data:', 'blob:'],
      fontSrc: ["'self'", 'data:'],
      connectSrc: ["'self'"],
      objectSrc: ["'none'"],
      frameAncestors: ["'self'"],
      baseUri: ["'self'"],
      formAction: ["'self'"],
      upgradeInsecureRequests: null,
    },
  },
  crossOriginEmbedderPolicy: false,
  crossOriginResourcePolicy: { policy: 'same-site' },
  referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
  hsts: IS_PROD ? { maxAge: 15552000, includeSubDomains: true } : false,
}))
app.use(compression())
app.use(cors({
  origin(origin, callback) {
    if (!origin) return callback(null, true)
    if (!allowedOrigins.length) return callback(null, true)
    return callback(null, allowedOrigins.includes(origin))
  },
}))
app.use(express.json({ limit: '24mb' }))

const secretFile = path.join(DATA_DIR, '.jwt-secret')
if (!fs.existsSync(secretFile)) {
  fs.writeFileSync(secretFile, crypto.randomBytes(32).toString('hex'), { mode: 0o600 })
}
const JWT_SECRET = process.env.JWT_SECRET || fs.readFileSync(secretFile, 'utf8').trim()

const loginLimiter = rateLimit({
  windowMs: 10 * 60 * 1000,
  limit: 20,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: { error: '尝试次数过多，请稍后再试' },
  validate: false,
})

const uploadLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  limit: 120,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: { error: '上传过于频繁，请稍后再试' },
  validate: false,
})

const aiLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  limit: 30,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: { error: 'AI 请求过于频繁，请稍后再试' },
  validate: false,
})

// 记录本次启动是否真的用内置默认密码建了账号。
// 只有这种情况才需要在自检里提醒改密码；库已存在账号时
// DEFAULT_ADMIN_PASSWORD 根本不生效，报出来只会让人白改一遍配置。
let defaultAdminSeeded = false

function seedDefaultAdmin() {
  if (process.env.DISABLE_DEFAULT_ADMIN === '1') return
  const username = process.env.DEFAULT_ADMIN_USERNAME || 'coustea'
  const password = process.env.DEFAULT_ADMIN_PASSWORD || 'coustea'
  if (!username || !password) return

  const existing = db.prepare('SELECT id FROM users WHERE username = ?').get(username)
  if (existing) return

  db.prepare('INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)')
    .run(
      username,
      bcrypt.hashSync(password, 10),
      process.env.DEFAULT_ADMIN_DISPLAY_NAME || '站长',
    )
  if (!process.env.DEFAULT_ADMIN_PASSWORD) {
    defaultAdminSeeded = true
    console.warn('[安全提醒] 正在使用内置默认密码，部署到公网前请设置 DEFAULT_ADMIN_PASSWORD 或通过环境变量创建账号。')
  }
}

function slugify(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

function sign(user) {
  return jwt.sign({ id: user.id, username: user.username }, JWT_SECRET, { expiresIn: '30d' })
}

function auth(req, _res, next) {
  const header = req.headers.authorization || ''
  if (header.startsWith('Bearer ')) {
    try {
      req.user = jwt.verify(header.slice(7), JWT_SECRET)
    } catch {
      req.user = null
    }
  } else {
    req.user = null
  }
  next()
}

function requireAuth(req, res, next) {
  if (!req.user) return res.status(401).json({ error: '请先登录' })
  next()
}

// 站点所有者是唯一可以创建项目、导入内容的账号。
// SITE_OWNER 为空字符串时退化为“任意登录账号”，便于多作者部署。
function requireSiteOwner(req, res, next) {
  if (!req.user) return res.status(401).json({ error: '请先登录' })
  if (SITE_OWNER && req.user.username !== SITE_OWNER) {
    return res.status(403).json({ error: '只有站点所有者可以创建项目或导入内容' })
  }
  next()
}

function requireCoustea(req, res, next) {
  if (!req.user) return res.status(401).json({ error: '请先登录' })
  const account = db.prepare('SELECT username FROM users WHERE id = ?').get(req.user.id)
  if (account?.username !== 'coustea') {
    return res.status(403).json({ error: '只有 coustea 可以配置和使用 AI' })
  }
  next()
}

function uniqueProjectSlug(userId, name) {
  const base = slugify(name) || 'project'
  let slug = base
  let suffix = 1
  while (db.prepare('SELECT id FROM projects WHERE owner_id = ? AND slug = ?').get(userId, slug)) {
    slug = `${base}-${suffix++}`
  }
  return slug
}

function siteUrl(req) {
  if (process.env.SITE_URL) return process.env.SITE_URL.replace(/\/$/, '')
  const proto = String(req.headers['x-forwarded-proto'] || req.protocol || 'http')
    .split(',')[0].trim()
  const host = String(req.headers['x-forwarded-host'] || req.get('host') || 'localhost')
    .split(',')[0].trim()
  return `${proto}://${host}`
}

function escapeXml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function visible(row, user) {
  return row.status === 'published' || (user && row.owner_id === user.id)
}

function validParent(projectId, parentId) {
  if (!Number.isSafeInteger(parentId) || parentId < 0) return false
  if (parentId === 0) return true
  const parent = db.prepare('SELECT project_id, kind, deleted_at FROM nodes WHERE id = ?').get(parentId)
  return !!parent && parent.project_id === projectId && parent.kind === 'folder' && !parent.deleted_at
}

function visibleNode(row, user, project, nodeMap) {
  if (!visible(row, user) || row.deleted_at) return false
  const ownerProject = project || db.prepare('SELECT * FROM projects WHERE id = ?').get(row.project_id)
  if (!ownerProject || !visible(ownerProject, user)) return false
  let parentId = row.parent_id
  const seen = new Set([row.id])
  while (parentId) {
    if (seen.has(parentId)) return false
    seen.add(parentId)
    const parent = nodeMap
      ? nodeMap.get(parentId)
      : db.prepare('SELECT * FROM nodes WHERE id = ?').get(parentId)
    if (!parent || parent.project_id !== row.project_id || parent.deleted_at || !visible(parent, user)) return false
    parentId = parent.parent_id
  }
  return true
}

function readableNodes(project, user) {
  const nodes = db.prepare('SELECT * FROM nodes WHERE project_id = ? AND deleted_at IS NULL ORDER BY sort_order, id')
    .all(project.id)
  const nodeMap = new Map(nodes.map((node) => [node.id, node]))
  return nodes.filter((node) => visibleNode(node, user, project, nodeMap))
}

function projectSummary(project, user) {
  const nodes = readableNodes(project, user)
  const tags = [...new Set(nodes
    .filter((node) => node.kind === 'doc')
    .flatMap((node) => String(node.tags || '').split(',').map((tag) => tag.trim()).filter(Boolean)))]
  return {
    ...project,
    doc_count: nodes.filter((node) => node.kind === 'doc').length,
    folder_count: nodes.filter((node) => node.kind === 'folder').length,
    tags: tags.slice(0, 4),
  }
}

// 学习日按服务器本地时区算（容器里由 TZ 环境变量决定），避免 UTC 与本地日期错开一天
function today() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function normalizeDate(value) {
  const text = String(value || '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return ''
  const parsed = new Date(`${text}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return ''
  // 形如 2026-02-31 的日期会被 Date 顺延，回读一次确认是同一个日历日
  return parsed.toISOString().slice(0, 10) === text ? text : ''
}

function assertOwner(row, user, res) {
  if (!user || row.owner_id !== user.id) {
    res.status(403).json({ error: '无权修改他人的内容' })
    return false
  }
  return true
}

function touchProject(id) {
  db.prepare('UPDATE projects SET updated_at = datetime(\'now\') WHERE id = ?').run(id)
}

// 软删除整棵子树：文件夹连带其下所有内容进回收站，恢复时按 deleted_at 一起还原
function trashTree(rootId, deletedAt) {
  const children = db.prepare('SELECT id FROM nodes WHERE parent_id = ? AND deleted_at IS NULL').all(rootId)
  for (const child of children) trashTree(child.id, deletedAt)
  db.prepare('UPDATE nodes SET deleted_at = ? WHERE id = ?').run(deletedAt, rootId)
}

function restoreTree(rootId) {
  const children = db.prepare('SELECT id FROM nodes WHERE parent_id = ?').all(rootId)
  for (const child of children) restoreTree(child.id)
  db.prepare('UPDATE nodes SET deleted_at = NULL WHERE id = ?').run(rootId)
}

function purgeTree(rootId) {
  const children = db.prepare('SELECT id FROM nodes WHERE parent_id = ?').all(rootId)
  for (const child of children) purgeTree(child.id)
  db.prepare('DELETE FROM nodes WHERE id = ?').run(rootId)
}

function isDescendant(candidateParentId, nodeId) {
  let current = candidateParentId
  const seen = new Set()
  while (current && !seen.has(current)) {
    if (current === nodeId) return true
    seen.add(current)
    const row = db.prepare('SELECT parent_id FROM nodes WHERE id = ?').get(current)
    if (!row) return false
    current = row.parent_id
  }
  return false
}

// 搜索结果摘要：先把 Markdown 记号剥掉再截取。
// 否则列表里会出现「## 变量与常量 **声明** `go var`」这种原始语法，
// 既占地方又难读 —— 读者要的是句子，不是源码。
function plainText(markdown) {
  return String(markdown || '')
    // 代码块整体替换成占位，避免把里面的注释当成正文
    .replace(/```[\s\S]*?```/g, ' ')
    // 图片与链接只留文字
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    // 行首的标题 / 引用 / 列表记号
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    // 表格分隔行（|---|:--:|），必须在去掉竖线之前处理
    .replace(/^\s*\|?[\s:|-]{4,}\|?\s*$/gm, ' ')
    // 表格竖线换成分隔符，读起来比一串 | 顺
    .replace(/^\s*\|(.+)\|\s*$/gm, (_all, cells) => ` ${cells.replace(/\s*\|\s*/g, ' / ')} `)
    // 成对记号只剥掉记号本身。
    // 注意不能无差别删所有 * _ `：那样 snake_case 会变成 snakecase、some_var 变成 somevar。
    .replace(/(\*\*|__)(.+?)\1/g, '$2')
    .replace(/\*([^*\n]+)\*/g, '$1')
    // 下划线斜体只在两侧不是单词字符时才算强调，避免误伤变量名
    .replace(/(^|[^\w])_([^_\n]+)_(?=[^\w]|$)/g, '$1$2')
    .replace(/~~(.+?)~~/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    // 水平线
    .replace(/^\s*([-*_])\1{2,}\s*$/gm, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function stripLeadingTitle(markdown, title) {
  const raw = String(markdown || '').replace(/^\s+/, '')
  if (!title) return raw
  const lines = raw.split('\n')
  const match = /^#\s+(.*)$/.exec((lines[0] || '').trim())
  if (!match) return raw
  const norm = (v) => v.replace(/[*_`~]/g, '').replace(/\s+/g, '').toLowerCase()
  if (norm(match[1]) !== norm(title)) return raw
  let i = 1
  while (i < lines.length && !lines[i].trim()) i += 1
  return lines.slice(i).join('\n')
}

function leadExcerpt(markdown, title, maxLen = 140) {
  const clean = plainText(stripLeadingTitle(markdown, title))
  if (clean.length <= maxLen) return clean
  const slice = clean.slice(0, maxLen)
  const lastBreak = Math.max(
    slice.lastIndexOf('。'), slice.lastIndexOf('；'), slice.lastIndexOf('，'),
    slice.lastIndexOf('、'), slice.lastIndexOf(' '),
  )
  const cut = lastBreak > Math.floor(maxLen * 0.55) ? slice.slice(0, lastBreak) : slice
  return cut.replace(/[，、；：,\s]+$/, '') + '…'
}

function excerpt(text, query, title = '') {
  const clean = plainText(stripLeadingTitle(text, title))
  const at = clean.toLowerCase().indexOf(query.toLowerCase())
  if (at < 0) return leadExcerpt(text, title, 140)
  let start = Math.max(0, at - 50)
  let end = Math.min(clean.length, at + query.length + 80)
  // 按固定字数截断会切在词中间，出现「…与 defer switch 让」这种半截开头。
  // 保留至少 20 个字符的上下文，再往后找第一个分隔符（空格或中文标点）重新开头。
  const SEPARATOR = /[\s，。；：！？、,.;:!?]/
  if (start > 0) {
    const lead = Math.min(20, at - start)
    const boundary = clean.slice(start + lead, at).search(SEPARATOR)
    if (boundary >= 0) start = start + lead + boundary + 1
  }
  // 结尾同理：不要停在半截词上，往回找一个分隔符
  if (end < clean.length) {
    const tail = clean.slice(at + query.length, end)
    const lastBreak = Math.max(
      tail.lastIndexOf(' '),
      tail.lastIndexOf('，'), tail.lastIndexOf('。'), tail.lastIndexOf('；'),
    )
    if (lastBreak > 20) end = at + query.length + lastBreak + 1
  }
  return (start > 0 ? '…' : '') + clean.slice(start, end).trim() + (end < clean.length ? '…' : '')
}

function visibility(user) {
  return user ? user.id : 0
}

app.use(auth)

app.get('/api/healthz', (_req, res) => {
  try {
    db.prepare('SELECT 1').get()
    res.json({ ok: true, uptime: Math.round(process.uptime()) })
  } catch (error) {
    res.status(503).json({ ok: false, error: String(error && error.message) })
  }
})

app.post('/api/auth/register', (_req, res) => {
  res.status(403).json({ error: '本站不开放注册' })
})

app.post('/api/auth/login', loginLimiter, (req, res) => {
  const username = String(req.body.username || '').trim()
  const password = String(req.body.password || '')
  const row = db.prepare('SELECT * FROM users WHERE username = ?').get(username)
  if (!row || !bcrypt.compareSync(password, row.password_hash)) {
    return res.status(401).json({ error: '用户名或密码错误' })
  }
  const user = { id: row.id, username: row.username, display_name: row.display_name }
  res.json({ token: sign(user), user })
})

app.get('/api/auth/me', requireAuth, (req, res) => {
  const row = db.prepare('SELECT id, username, display_name FROM users WHERE id = ?').get(req.user.id)
  if (!row) return res.status(401).json({ error: '账号不存在' })
  res.json({ user: row })
})

app.post('/api/auth/change-password', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM users WHERE id = ?').get(req.user.id)
  if (!row) return res.status(401).json({ error: '账号不存在' })
  if (!bcrypt.compareSync(String(req.body.oldPassword || ''), row.password_hash)) {
    return res.status(400).json({ error: '原密码不正确' })
  }
  const next = String(req.body.newPassword || '')
  if (next.length < 6) return res.status(400).json({ error: '新密码至少 6 位' })
  db.prepare('UPDATE users SET password_hash = ? WHERE id = ?')
    .run(bcrypt.hashSync(next, 10), req.user.id)
  res.json({ ok: true })
})

// 各家 OpenAI 兼容服务对 Base URL 的写法并不一致：
//   讯飞 MaaS 官方文档给的是 .../v2/chat/completions（完整端点）
//   DeepSeek / OpenAI 给的是 .../v1（版本前缀）
// OpenAI SDK 会自己再拼 /chat/completions，所以用户照文档粘贴完整端点时
// 会得到 .../chat/completions/chat/completions 的 404。
// 这里统一把两种写法都收敛成 SDK 需要的“版本前缀”。
function normalizeAiEndpoint(baseURL) {
  let endpoint = baseURL
  // 用户直接粘了完整端点：去掉尾部 /chat/completions
  endpoint = endpoint.replace(/\/chat\/completions\/?$/i, '')
  // 用户粘了 /v1/chat/completions 以外的其它已知端点形式也一并容忍
  endpoint = endpoint.replace(/\/completions\/?$/i, '')
  return endpoint.replace(/\/+$/, '')
}

function validateAiBaseUrl(baseURL) {
  if (!baseURL) return { ok: true, endpoint: 'https://api.openai.com/v1' }
  if (typeof baseURL !== 'string' || baseURL.length > 300) {
    return { ok: false, error: 'Base URL 格式无效' }
  }
  try {
    const url = new URL(baseURL)
    const host = url.hostname.toLowerCase().replace(/\.$/, '')
    if (url.protocol !== 'https:' || !host.includes('.') || net.isIP(host) || host.includes(':') ||
        host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') ||
        host.endsWith('.internal') || url.username || url.password || url.search || url.hash) {
      return { ok: false, error: 'Base URL 必须是 HTTPS 域名地址' }
    }
    return { ok: true, endpoint: normalizeAiEndpoint(url.toString()) }
  } catch {
    return { ok: false, error: 'Base URL 格式无效' }
  }
}

function readAiConfig() {
  const row = db.prepare("SELECT value FROM app_settings WHERE key = 'ai_config'").get()
  if (!row) return { apiKey: '', model: '', baseURL: '' }
  try {
    const parsed = JSON.parse(row.value)
    return {
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : '',
      model: typeof parsed.model === 'string' ? parsed.model : '',
      baseURL: typeof parsed.baseURL === 'string' ? parsed.baseURL : '',
    }
  } catch {
    return { apiKey: '', model: '', baseURL: '' }
  }
}

function maskApiKey(key) {
  if (!key) return ''
  if (key.length <= 8) return `${key.slice(0, 2)}••••`
  return `${key.slice(0, 4)}••••${key.slice(-4)}`
}

function estimateReadingMinutes(text) {
  const raw = String(text || '')
  const cjk = (raw.match(/[\u4e00-\u9fa5]/g) || []).length
  const words = raw.replace(/[\u4e00-\u9fa5]/g, ' ').split(/\s+/).filter(Boolean).length
  return Math.max(1, Math.round(cjk / 400 + words / 200))
}

app.get('/api/admin/ai-config', requireCoustea, (_req, res) => {
  const config = readAiConfig()
  res.json({
    config: {
      model: config.model,
      baseURL: config.baseURL,
      hasApiKey: Boolean(config.apiKey),
      apiKeyHint: maskApiKey(config.apiKey),
    },
  })
})

app.put('/api/admin/ai-config', requireCoustea, (req, res) => {
  const { apiKey, model, baseURL, clearApiKey } = req.body || {}
  const prev = readAiConfig()
  const nextModel = typeof model === 'string' ? model.trim() : prev.model
  const nextBaseURL = typeof baseURL === 'string' ? baseURL.trim() : prev.baseURL
  if (nextModel.length > 100) return res.status(400).json({ error: '模型名称长度不能超过 100 字符' })
  if (nextBaseURL) {
    const checked = validateAiBaseUrl(nextBaseURL)
    if (!checked.ok) return res.status(400).json({ error: checked.error })
  }
  let nextApiKey = prev.apiKey
  if (clearApiKey) {
    nextApiKey = ''
  } else if (typeof apiKey === 'string' && apiKey.trim()) {
    if (apiKey.length > 2048) return res.status(400).json({ error: 'API Key 长度无效' })
    nextApiKey = apiKey.trim()
  }
  const value = JSON.stringify({ apiKey: nextApiKey, model: nextModel, baseURL: nextBaseURL })
  db.prepare(`
    INSERT INTO app_settings (key, value, updated_at) VALUES ('ai_config', ?, datetime('now'))
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
  `).run(value)
  res.json({
    config: {
      model: nextModel,
      baseURL: nextBaseURL,
      hasApiKey: Boolean(nextApiKey),
      apiKeyHint: maskApiKey(nextApiKey),
    },
  })
})

// 配置连通性自检：用当前（或本次提交的）参数发一次极小的真实请求。
// 只回显上游是否可达与错误摘要，不返回密钥，也不产生可观的 token 消耗。
app.post('/api/admin/ai-config/test', requireCoustea, aiLimiter, async (req, res) => {
  const saved = readAiConfig()
  const body = req.body || {}
  const apiKey = typeof body.apiKey === 'string' && body.apiKey.trim() ? body.apiKey.trim() : saved.apiKey
  const model = typeof body.model === 'string' && body.model.trim() ? body.model.trim() : saved.model
  const baseURL = typeof body.baseURL === 'string' && body.baseURL.trim() ? body.baseURL.trim() : saved.baseURL

  if (!apiKey || !model) {
    return res.status(400).json({ error: '请先填写 API Key 与模型名称再测试连接' })
  }
  const checkedUrl = validateAiBaseUrl(baseURL)
  if (!checkedUrl.ok) return res.status(400).json({ error: checkedUrl.error })

  try {
    const client = new OpenAI({ apiKey, baseURL: checkedUrl.endpoint, timeout: 30000, maxRetries: 0 })
    const response = await client.chat.completions.create({
      model,
      messages: [{ role: 'user', content: 'ping' }],
      max_tokens: 16,
    })
    const bizCode = response?.code
    if (bizCode !== undefined && bizCode !== null && Number(bizCode) !== 0) {
      const detail = typeof response?.message === 'string' ? response.message : ''
      return res.status(502).json({
        error: `上游返回业务错误（${bizCode}）${detail ? `：${detail}` : ''}`,
        endpoint: checkedUrl.endpoint,
      })
    }
    res.json({
      ok: true,
      endpoint: checkedUrl.endpoint,
      model: response?.model || model,
      hint: '连接正常，模型可以响应。',
    })
  } catch (error) {
    const upstream = error?.error
    const upstreamMessage = typeof upstream?.message === 'string' ? upstream.message
      : typeof upstream?.error?.message === 'string' ? upstream.error.message
        : typeof error?.message === 'string' ? error.message.replace(/^\d{3}\s+/, '') : ''
    console.error('AI 连接测试失败', { status: error.status, upstream: upstreamMessage.slice(0, 200) })
    // 各家对“模型不存在”的状态码并不统一：OpenAI/DeepSeek 用 404，
    // 讯飞 MaaS 返回 400 + "unsupported model"。所以先看上游文案再退回状态码。
    const lower = upstreamMessage.toLowerCase()
    const modelMissing = /unsupported model|model not found|does not exist|invalid model|no such model/.test(lower)
    const hint = modelMissing ? `模型不可用：请核对模型 ID（上游：${upstreamMessage.slice(0, 120)}）` :
      error.status === 401 ? '鉴权失败：API Key 无效，或该服务要求不同的鉴权方式' :
        error.status === 403 ? '被拒绝：该 Key 可能未开通此模型' :
          error.status === 404 ? '地址或模型不存在：请核对 Base URL 与模型 ID' :
            error.status === 400 ? `请求被拒绝：${upstreamMessage.slice(0, 120) || '参数或模型名不被接受'}` :
              error.status === 429 ? '触发限流或额度不足' :
                error.name === 'APIConnectionTimeoutError' ? '连接超时' : '连接失败'
    res.status(502).json({ error: hint, detail: upstreamMessage.slice(0, 300), endpoint: checkedUrl.endpoint })
  }
})

app.post('/api/ai/markdown', requireCoustea, aiLimiter, async (req, res) => {
  const saved = readAiConfig()
  const body = req.body || {}
  const apiKey = typeof body.apiKey === 'string' && body.apiKey.trim() ? body.apiKey.trim() : saved.apiKey
  const model = typeof body.model === 'string' && body.model.trim() ? body.model.trim() : saved.model
  const baseURL = typeof body.baseURL === 'string' && body.baseURL.trim() ? body.baseURL.trim() : saved.baseURL
  const { mode, prompt, title, context } = body
  if (typeof apiKey !== 'string' || !apiKey.trim() || apiKey.length > 2048 ||
      typeof model !== 'string' || !model.trim() || model.length > 100 ||
      typeof prompt !== 'string' || !prompt.trim() || prompt.length > 2000 ||
      typeof title !== 'string' || title.length > 160 ||
      typeof context !== 'string' || context.length > 12000 ||
      !['draft', 'continue', 'rewrite'].includes(mode)) {
    return res.status(400).json({ error: '请检查 API Key、模型、写作要求和正文长度' })
  }

  const checkedUrl = validateAiBaseUrl(baseURL)
  if (!checkedUrl.ok) return res.status(400).json({ error: checkedUrl.error })
  const endpoint = checkedUrl.endpoint

  const task = mode === 'draft' ? '根据主题和要求撰写一段新笔记' :
    mode === 'continue' ? '接着已有正文续写，不要重复已有内容' :
      '改写选中的正文，保留原意并满足要求'
  const input = `标题：${title.trim() || '未命名笔记'}\n任务：${task}\n写作要求：${prompt.trim()}${context ? `\n已有内容：\n${context}` : ''}`

  try {
    const client = new OpenAI({ apiKey: apiKey.trim(), baseURL: endpoint, timeout: 120000, maxRetries: 0 })
    const response = await client.chat.completions.create({
      model: model.trim(),
      ...(endpoint.includes('xf-yun.com') ? { thinking: { type: 'disabled' } } : {}),
      messages: [
        { role: 'system', content: '你是技术学习笔记写作助手。只输出可直接插入文章的 Markdown 正文，不要用代码围栏包裹整段回答。代码示例要准确；不确定的事实不要编造。' },
        { role: 'user', content: input },
      ],
    })
    // 讯飞 MaaS / 部分国内兼容服务在 HTTP 200 里返回业务错误码（code 非 0），
    // OpenAI SDK 不会把它当异常，直接读 choices 会拿到 undefined。
    // 这里显式识别，避免把“模型不存在”误报成“模型没有返回内容”。
    const bizCode = response?.code
    if (bizCode !== undefined && bizCode !== null && Number(bizCode) !== 0) {
      const detail = typeof response?.message === 'string' ? response.message : ''
      console.error('AI 上游业务错误', { code: bizCode, message: detail })
      return res.status(502).json({
        error: detail
          ? `AI 服务返回错误（${bizCode}）：${detail}`
          : `AI 服务返回错误码 ${bizCode}，请检查模型名称与 Base URL`,
      })
    }
    if (response.choices?.[0]?.finish_reason === 'length') {
      return res.status(502).json({ error: '生成内容达到长度上限，请缩小写作范围后重试' })
    }
    const message = response.choices?.[0]?.message
    // 思考型模型（如 spark-x2.6 默认开启 thinking）可能把内容放进 reasoning_content，
    // 或者正文为空而只有推理过程。优先取正文，正文为空时退回推理内容，避免误判为空响应。
    const markdown = (typeof message?.content === 'string' ? message.content : '').trim() ||
      (typeof message?.reasoning_content === 'string' ? message.reasoning_content : '').trim()
    if (!markdown) return res.status(502).json({ error: '模型没有返回 Markdown 内容' })
    res.json({ markdown })
  } catch (error) {
    // SDK 会把上游错误体挂在 error.error 上；讯飞/DeepSeek 都用 { message } 或 { error: { message } }
    const upstream = error?.error
    const upstreamMessage = typeof upstream?.message === 'string' ? upstream.message
      : typeof upstream?.error?.message === 'string' ? upstream.error.message
        : typeof error?.message === 'string' ? error.message.replace(/^\d{3}\s+/, '') : ''
    console.error('AI 请求失败', {
      name: error.name, status: error.status, requestId: error.requestID,
      upstream: upstreamMessage.slice(0, 200),
    })
    const lower = upstreamMessage.toLowerCase()
    const modelMissing = /unsupported model|model not found|does not exist|invalid model|no such model/.test(lower)
    const message = modelMissing ? `模型不可用，请核对模型 ID（上游：${upstreamMessage}）` :
      error.status === 401 ? `AI 服务鉴权失败，请检查 API Key${upstreamMessage ? `（${upstreamMessage}）` : ''}` :
        error.status === 403 ? 'AI 服务拒绝访问，请确认该 Key 已开通所选模型' :
          error.status === 404 ? '模型或 Base URL 不存在，请检查输入' :
            error.status === 429 ? 'AI 服务请求受限，请稍后再试' :
              error.name === 'APIConnectionTimeoutError' ? 'AI 服务响应超时，请稍后再试' :
                upstreamMessage ? `AI 服务返回错误：${upstreamMessage}` :
                  'AI 服务暂时不可用，请检查模型和 Base URL'
    res.status(error.status === 429 ? 429 : error.name === 'APIConnectionTimeoutError' ? 504 : 502).json({ error: message })
  }
})

app.get('/api/projects', (req, res) => {
  const uid = req.user ? req.user.id : 0
  const rows = db.prepare(`
    SELECT * FROM projects WHERE status = 'published' OR owner_id = ?
    ORDER BY sort_order, id
  `).all(uid)
  const projects = rows.map((project) => projectSummary(project, req.user))
  res.json({ projects })
})

app.post('/api/projects', requireSiteOwner, (req, res) => {
  const name = String(req.body.name || '').trim()
  if (!name) return res.status(400).json({ error: '项目名称不能为空' })
  const slug = uniqueProjectSlug(req.user.id, req.body.slug || name)
  const info = db.prepare(`
    INSERT INTO projects (owner_id, name, slug, description, status, sort_order)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(
    req.user.id,
    name,
    slug,
    String(req.body.description || ''),
    req.body.status === 'published' ? 'published' : 'draft',
    Number(req.body.sortOrder || 0),
  )
  const row = db.prepare('SELECT * FROM projects WHERE id = ?').get(info.lastInsertRowid)
  res.status(201).json({ project: row })
})

app.get('/api/projects/:id', (req, res) => {
  const viewer = req.query.public === '1' ? null : req.user
  const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id)
  if (!project) return res.status(404).json({ error: '项目不存在' })
  if (!visible(project, viewer)) return res.status(404).json({ error: '项目不存在' })
  const nodes = readableNodes(project, viewer)
  const docCount = nodes.filter((node) => node.kind === 'doc').length
  const folderCount = nodes.filter((node) => node.kind === 'folder').length
  res.json({ project: { ...project, doc_count: docCount, folder_count: folderCount }, nodes })
})

app.patch('/api/projects/:id', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id)
  if (!row) return res.status(404).json({ error: '项目不存在' })
  if (!assertOwner(row, req.user, res)) return
  const fields = ['name', 'slug', 'description', 'status', 'sort_order']
  const next = {}
  for (const field of fields) {
    if (req.body[field] !== undefined) next[field] = req.body[field]
  }
  if (next.status && !['draft', 'published'].includes(next.status)) {
    return res.status(400).json({ error: '状态值无效' })
  }
  if (Object.keys(next).length) {
    const set = Object.keys(next).map((key) => `${key} = ?`).join(', ')
    db.prepare(`UPDATE projects SET ${set}, updated_at = datetime('now') WHERE id = ?`)
      .run(...Object.values(next), row.id)
  }
  res.json({ project: db.prepare('SELECT * FROM projects WHERE id = ?').get(row.id) })
})

app.delete('/api/projects/:id', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id)
  if (!row) return res.status(404).json({ error: '项目不存在' })
  if (!assertOwner(row, req.user, res)) return
  db.prepare('DELETE FROM projects WHERE id = ?').run(row.id)
  res.json({ ok: true })
})

app.post('/api/nodes', requireAuth, (req, res) => {
  const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.body.projectId)
  if (!project) return res.status(404).json({ error: '项目不存在' })
  if (!assertOwner(project, req.user, res)) return
  const kind = req.body.kind === 'folder' ? 'folder' : 'doc'
  const title = String(req.body.title || '').trim() || (kind === 'folder' ? '新建文件夹' : '未命名笔记')
  const parentId = Number(req.body.parentId || 0)
  if (!validParent(project.id, parentId)) return res.status(400).json({ error: '父目录无效' })
  const slug = slugify(req.body.slug || title) || `node-${Date.now()}`
  const status = req.body.status === 'published' ? 'published' : 'draft'
  // 学习日：默认记在今天，导入历史笔记时可以指定，用于「今日/打卡」统计
  const dailyDate = normalizeDate(req.body.dailyDate) || today()
  const info = db.prepare(`
    INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, content, tags, sort_order, status, daily_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    req.user.id, project.id, parentId, kind, title, slug,
    String(req.body.content || ''), String(req.body.tags || ''),
    Number(req.body.sortOrder || 0), status, dailyDate,
  )
  touchProject(project.id)
  res.status(201).json({ node: db.prepare('SELECT * FROM nodes WHERE id = ?').get(info.lastInsertRowid) })
})

app.get('/api/nodes/:id', (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ?').get(req.params.id)
  if (!row || !visibleNode(row, req.user)) return res.status(404).json({ error: '内容不存在' })
  res.json({ node: row })
})

app.get('/api/nodes/:id/revisions', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ? AND deleted_at IS NULL').get(req.params.id)
  if (!row) return res.status(404).json({ error: '内容不存在' })
  if (!assertOwner(row, req.user, res)) return
  const revisions = db.prepare(`
    SELECT id, title, created_at FROM node_revisions WHERE node_id = ? ORDER BY id DESC
  `).all(row.id)
  res.json({ revisions })
})

app.get('/api/nodes/:id/revisions/:revisionId', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ? AND deleted_at IS NULL').get(req.params.id)
  if (!row) return res.status(404).json({ error: '内容不存在' })
  if (!assertOwner(row, req.user, res)) return
  const revision = db.prepare('SELECT * FROM node_revisions WHERE node_id = ? AND id = ?')
    .get(row.id, req.params.revisionId)
  if (!revision) return res.status(404).json({ error: '历史版本不存在' })
  res.json({ revision })
})

app.patch('/api/nodes/:id', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ?').get(req.params.id)
  if (!row || row.deleted_at) return res.status(404).json({ error: '内容不存在' })
  if (!assertOwner(row, req.user, res)) return
  const map = {
    title: 'title', slug: 'slug', content: 'content', tags: 'tags',
    sortOrder: 'sort_order', status: 'status', parentId: 'parent_id', dailyDate: 'daily_date',
  }
  const next = {}
  for (const [key, column] of Object.entries(map)) {
    if (req.body[key] !== undefined) next[column] = req.body[key]
  }
  if (next.status && !['draft', 'published'].includes(next.status)) {
    return res.status(400).json({ error: '状态值无效' })
  }
  if (next.daily_date !== undefined) {
    next.daily_date = normalizeDate(next.daily_date) || today()
  }
  if (next.parent_id !== undefined) {
    next.parent_id = Number(next.parent_id)
    if (!validParent(row.project_id, next.parent_id) || next.parent_id === row.id) {
      return res.status(400).json({ error: '父目录无效' })
    }
    if (isDescendant(next.parent_id, row.id)) {
      return res.status(400).json({ error: '不能移动到自己的子目录中' })
    }
  }
  if (Object.keys(next).length) {
    const set = Object.keys(next).map((key) => `${key} = ?`).join(', ')
    db.transaction(() => {
      if (['title', 'slug', 'content', 'tags'].some((key) => next[key] !== undefined && next[key] !== row[key])) {
        db.prepare(`
          INSERT INTO node_revisions (node_id, title, slug, content, tags) VALUES (?, ?, ?, ?, ?)
        `).run(row.id, row.title, row.slug, row.content, row.tags)
      }
      db.prepare(`UPDATE nodes SET ${set}, updated_at = datetime('now') WHERE id = ?`)
        .run(...Object.values(next), row.id)
    })()
  }
  touchProject(row.project_id)
  res.json({ node: db.prepare('SELECT * FROM nodes WHERE id = ?').get(row.id) })
})

// 文件树拖拽：一次事务里移动节点并重排两侧兄弟节点，避免重复 sort_order。
app.post('/api/nodes/:id/move', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ? AND deleted_at IS NULL').get(req.params.id)
  if (!row) return res.status(404).json({ error: '内容不存在' })
  if (!assertOwner(row, req.user, res)) return
  const parentId = Number(req.body.parentId)
  const beforeId = req.body.beforeId == null ? null : Number(req.body.beforeId)
  if (!validParent(row.project_id, parentId) || parentId === row.id || isDescendant(parentId, row.id)) {
    return res.status(400).json({ error: '目标目录无效' })
  }
  if (beforeId !== null) {
    const before = db.prepare('SELECT project_id, parent_id FROM nodes WHERE id = ? AND deleted_at IS NULL').get(beforeId)
    if (!before || before.project_id !== row.project_id || before.parent_id !== parentId || beforeId === row.id) {
      return res.status(400).json({ error: '目标位置无效' })
    }
  }

  const siblings = (parent) => db.prepare(`
    SELECT id FROM nodes WHERE project_id = ? AND parent_id = ? AND deleted_at IS NULL ORDER BY sort_order, id
  `).all(row.project_id, parent).map((item) => item.id)
  db.transaction(() => {
    const oldParentId = row.parent_id
    const oldSiblings = siblings(oldParentId).filter((id) => id !== row.id)
    const nextSiblings = oldParentId === parentId ? oldSiblings : siblings(parentId)
    const insertAt = beforeId === null ? nextSiblings.length : nextSiblings.indexOf(beforeId)
    nextSiblings.splice(insertAt, 0, row.id)
    db.prepare('UPDATE nodes SET parent_id = ?, updated_at = datetime(\'now\') WHERE id = ?').run(parentId, row.id)
    const setOrder = db.prepare('UPDATE nodes SET sort_order = ? WHERE id = ?')
    if (oldParentId !== parentId) oldSiblings.forEach((id, index) => setOrder.run(index, id))
    nextSiblings.forEach((id, index) => setOrder.run(index, id))
    touchProject(row.project_id)
  })()
  res.json({ node: db.prepare('SELECT * FROM nodes WHERE id = ?').get(row.id) })
})

// 删除进回收站，可恢复；?purge=1 才是彻底删除
app.delete('/api/nodes/:id', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ?').get(req.params.id)
  if (!row || row.deleted_at) return res.status(404).json({ error: '内容不存在' })
  if (!assertOwner(row, req.user, res)) return
  if (req.query.purge === '1') {
    db.transaction(() => purgeTree(row.id))()
  } else {
    db.transaction(() => trashTree(row.id, new Date().toISOString()))()
  }
  touchProject(row.project_id)
  res.json({ ok: true, trashed: req.query.purge !== '1' })
})

// 回收站：列出、恢复、清空。单人站点，直接按 owner 过滤即可。
app.get('/api/trash', requireAuth, (req, res) => {
  const nodes = db.prepare(`
    SELECT n.id, n.title, n.kind, n.project_id, n.parent_id, n.deleted_at, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.owner_id = ? AND n.deleted_at IS NOT NULL
      AND (n.parent_id = 0 OR NOT EXISTS (
        SELECT 1 FROM nodes parent WHERE parent.id = n.parent_id AND parent.deleted_at IS NOT NULL
      ))
    ORDER BY n.deleted_at DESC
  `).all(req.user.id)
  const total = db.prepare(
    'SELECT COUNT(*) AS c FROM nodes WHERE owner_id = ? AND deleted_at IS NOT NULL',
  ).get(req.user.id).c
  res.json({ nodes, total })
})

app.post('/api/trash/:id/restore', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ?').get(req.params.id)
  if (!row || !row.deleted_at) return res.status(404).json({ error: '回收站里没有这条内容' })
  if (!assertOwner(row, req.user, res)) return
  // 父目录也被删掉时，挂回根目录，避免恢复后看不见
  const parent = row.parent_id
    ? db.prepare('SELECT * FROM nodes WHERE id = ?').get(row.parent_id)
    : null
  db.transaction(() => {
    restoreTree(row.id)
    if (row.parent_id && (!parent || parent.deleted_at)) {
      db.prepare('UPDATE nodes SET parent_id = 0 WHERE id = ?').run(row.id)
    }
  })()
  touchProject(row.project_id)
  res.json({ ok: true, node: db.prepare('SELECT * FROM nodes WHERE id = ?').get(row.id) })
})

app.delete('/api/trash/:id', requireAuth, (req, res) => {
  const row = db.prepare('SELECT * FROM nodes WHERE id = ?').get(req.params.id)
  if (!row || !row.deleted_at) return res.status(404).json({ error: '回收站里没有这条内容' })
  if (!assertOwner(row, req.user, res)) return
  db.transaction(() => purgeTree(row.id))()
  res.json({ ok: true })
})

// 回收站清空：可选 ?days=N 只清理 N 天前的，默认全清
app.delete('/api/trash', requireAuth, (req, res) => {
  const days = Number(req.query.days || 0)
  const cutoff = days > 0 ? new Date(Date.now() - days * 86400000).toISOString() : null
  const rows = cutoff
    ? db.prepare('SELECT id FROM nodes WHERE owner_id = ? AND deleted_at IS NOT NULL AND deleted_at < ?').all(req.user.id, cutoff)
    : db.prepare('SELECT id FROM nodes WHERE owner_id = ? AND deleted_at IS NOT NULL').all(req.user.id)
  let removed = 0
  db.transaction(() => {
    for (const item of rows) {
      const still = db.prepare('SELECT id FROM nodes WHERE id = ?').get(item.id)
      if (!still) continue
      purgeTree(item.id)
      removed += 1
    }
  })()
  res.json({ ok: true, removed })
})

const MAX_IMPORT_FILES = 300
const MAX_IMPORT_FILE_BYTES = 2 * 1024 * 1024
const MAX_IMPORT_TOTAL_BYTES = 20 * 1024 * 1024

function validateImportFiles(files) {
  if (!Array.isArray(files) || !files.length) return '没有可导入的文件'
  if (files.length > MAX_IMPORT_FILES) return `单次最多导入 ${MAX_IMPORT_FILES} 个文件`
  let bytes = 0
  for (const file of files) {
    const size = Buffer.byteLength(String(file.content || ''), 'utf8')
    if (size > MAX_IMPORT_FILE_BYTES) {
      return `单个文件不能超过 2MB：${file.path || file.name || ''}`
    }
    bytes += size
  }
  if (bytes > MAX_IMPORT_TOTAL_BYTES) return '单次导入总大小不能超过 20MB'
  return null
}

// 目录结构来自前端相对路径，逐段清洗，丢弃隐藏目录与路径穿越片段
function pathSegments(relativePath) {
  return String(relativePath || '')
    .split(/[\\/]+/)
    .map((part) => part.trim())
    .filter((part) => part && part !== '.' && part !== '..' && !part.startsWith('.'))
    .slice(0, 12)
}

function importMarkdownTree({ project, userId, parentId, files, status }) {
  const root = Number(parentId || 0)
  let docs = 0
  const skipped = []
  let duplicates = 0

  // 同一父目录内单独计数，从已有兄弟节点的最大 sort_order 之后追加：
  // 批次内保持前端传来的路径排序，新导入的内容也不会插队到已有笔记前面
  const orderCounters = new Map()
  const nextOrder = (parent) => {
    if (!orderCounters.has(parent)) {
      const row = db.prepare(`
        SELECT COALESCE(MAX(sort_order), -1) AS maxOrder
        FROM nodes
        WHERE project_id = ? AND parent_id = ? AND deleted_at IS NULL
      `).get(project.id, parent)
      orderCounters.set(parent, Number(row.maxOrder) + 1)
    }
    const value = orderCounters.get(parent)
    orderCounters.set(parent, value + 1)
    return value
  }

  const findOrCreateFolder = (parent, title) => {
    const slug = slugify(title) || 'folder'
    const found = db.prepare(`
      SELECT id FROM nodes
      WHERE project_id = ? AND parent_id = ? AND kind = 'folder' AND slug = ? AND deleted_at IS NULL
    `).get(project.id, parent, slug)
    if (found) return found.id
    const info = db.prepare(`
      INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, status, sort_order)
      VALUES (?, ?, ?, 'folder', ?, ?, ?, ?)
    `).run(userId, project.id, parent, title, slug, status, nextOrder(parent))
    return Number(info.lastInsertRowid)
  }

  const tx = db.transaction(() => {
    files.forEach((file, index) => {
      const rel = String(file.path || file.name || '')
      const parts = pathSegments(rel)
      const filename = parts.pop()
      if (!filename || !/\.(md|markdown|mdx|txt)$/i.test(filename)) {
        skipped.push(rel)
        return
      }
      const sourcePath = `${root}/${[...parts, filename].join('/')}`
      if (db.prepare(`
        SELECT id FROM nodes WHERE project_id = ? AND source_path = ? AND deleted_at IS NULL
      `).get(project.id, sourcePath)) {
        duplicates += 1
        return
      }
      const parsed = matter(String(file.content || ''))
      const meta = parsed.data || {}
      let parent = root
      for (const part of parts) parent = findOrCreateFolder(parent, part)
      const firstHeading = (parsed.content || '').split('\n')
        .map((line) => line.trim())
        .find((line) => /^#\s+/.test(line))
      const headingTitle = firstHeading ? firstHeading.replace(/^#\s+/, '').trim() : ''
      const title = String(meta.title || meta.sidebar_label || headingTitle
        || filename.replace(/\.(md|markdown|mdx|txt)$/i, ''))
      const tags = Array.isArray(meta.tags) ? meta.tags.join(',') : String(meta.tags || '')
      // front-matter 显式给了数字 order 时才采用，否则按路径顺序在目录内依次编号
      const rawOrder = meta.order ?? meta.sidebar_position ?? meta.sort_order
      const explicitOrder = rawOrder !== undefined && rawOrder !== null
        && String(rawOrder).trim() !== '' && Number.isFinite(Number(rawOrder))
      const order = explicitOrder ? Number(rawOrder) : nextOrder(parent)
      // 导入时识别 front-matter 里的日期，让历史笔记也能落到正确的学习日
      const dailyDate = normalizeDate(meta.date || meta.created || meta.daily)
        || String(meta.date || '').slice(0, 10) || today()
      db.prepare(`
        INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, content, tags, sort_order, status, daily_date, source_path)
        VALUES (?, ?, ?, 'doc', ?, ?, ?, ?, ?, ?, ?, ?)
      `).run(
        userId, project.id, parent, title,
        slugify(title) || `doc-${Date.now()}-${index}`,
        parsed.content || '', tags, Number.isFinite(order) ? order : index, status,
        /^\d{4}-\d{2}-\d{2}$/.test(dailyDate) ? dailyDate : today(), sourcePath,
      )
      docs += 1
    })
    if (docs) touchProject(project.id)
  })
  tx()
  return { imported: docs, skipped, duplicates }
}

app.post('/api/import', requireSiteOwner, (req, res) => {
  const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.body.projectId)
  if (!project) return res.status(404).json({ error: '项目不存在' })
  if (!assertOwner(project, req.user, res)) return
  const files = Array.isArray(req.body.files) ? req.body.files : []
  const invalid = validateImportFiles(files)
  if (invalid) return res.status(400).json({ error: invalid })
  const parentId = Number(req.body.parentId || 0)
  if (!validParent(project.id, parentId)) return res.status(400).json({ error: '父目录无效' })

  const status = req.body.status === 'published' ? 'published' : 'draft'
  const result = importMarkdownTree({
    project, userId: req.user.id, parentId, files, status,
  })
  res.json({ ok: true, imported: result.imported, skipped: result.skipped.length, duplicates: result.duplicates })
})

// 上传整个文件夹直接建项目：一次请求完成建项目 + 重建多级目录
// 直接用文件夹建项目时，去掉所有文件共有的最外层目录名（前端通常已剥离，这里兜底）
function stripCommonRoot(files) {
  const paths = files.map((file) => String(file.path || file.name || '').split(/[\\/]+/).filter(Boolean))
  if (!paths.length || !paths[0][0]) return files
  const root = paths[0][0]
  const shared = paths.every((parts) => parts.length > 1 && parts[0] === root)
  if (!shared) return files
  return files.map((file, index) => ({ ...file, path: paths[index].slice(1).join('/') }))
}

app.post('/api/projects/from-folder', requireSiteOwner, (req, res) => {
  const files = stripCommonRoot(Array.isArray(req.body.files) ? req.body.files : [])
  const invalid = validateImportFiles(files)
  if (invalid) return res.status(400).json({ error: invalid })

  const name = String(req.body.name || '').trim() || '未命名项目'
  const status = req.body.status === 'draft' ? 'draft' : 'published'
  const slug = uniqueProjectSlug(req.user.id, name)
  const info = db.prepare(`
    INSERT INTO projects (owner_id, name, slug, description, status, sort_order)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(
    req.user.id,
    name,
    slug,
    String(req.body.description || ''),
    status,
    Number(req.body.sortOrder || 0),
  )
  const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(info.lastInsertRowid)
  const result = importMarkdownTree({
    project, userId: req.user.id, parentId: 0, files, status,
  })

  if (!result.imported) {
    db.prepare('DELETE FROM projects WHERE id = ?').run(project.id)
    return res.status(400).json({ error: '文件夹里没有找到 Markdown 文件' })
  }

  res.status(201).json({
    project: { ...project, doc_count: result.imported },
    imported: result.imported,
    skipped: result.skipped.length,
  })
})

app.get('/api/search', (req, res) => {
  const q = String(req.query.q || '').trim()
  if (!q) return res.json({ query: '', projects: [], notes: [], terms: [] })
  const viewer = req.query.public === '1' ? null : req.user
  const uid = visibility(viewer)

  // 支持多个关键词：按空白切分，每个词都要命中（AND）。
  // 这样「go 并发」能同时缩小到既有 go 又有并发的笔记，
  // 而不是像原来那样把整串当成一个子串去匹配，几乎搜不到东西。
  const terms = q.split(/\s+/).filter(Boolean).slice(0, 5)
  const projectWhere = terms.map(() => '(name LIKE ? OR description LIKE ?)').join(' AND ')
  const projectParams = terms.flatMap((term) => [`%${term}%`, `%${term}%`])
  const projects = db.prepare(`
    SELECT id, name, description, status, updated_at
    FROM projects
    WHERE (status = 'published' OR owner_id = ?)
      AND ${projectWhere}
    ORDER BY updated_at DESC LIMIT 50
  `).all(uid, ...projectParams)

  // 笔记侧：标题 / 正文 / 标签任意一项命中该词即可，多个词之间取交集
  const noteWhere = terms
    .map(() => '(n.title LIKE ? OR n.content LIKE ? OR n.tags LIKE ?)')
    .join(' AND ')
  const noteParams = terms.flatMap((term) => [`%${term}%`, `%${term}%`, `%${term}%`])
  const rows = db.prepare(`
    SELECT n.*, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
      AND ${noteWhere}
    ORDER BY n.updated_at DESC
  `).all(uid, uid, ...noteParams).filter((row) => visibleNode(row, viewer)).slice(0, 100)

  const notes = rows.map((row) => ({
    ...row,
    // 摘要围绕第一个词截取，多个词时用第一个最有区分度的
    excerpt: excerpt(row.content, terms[0], row.title),
  }))
  res.json({ query: q, projects, notes, terms })
})

app.get('/api/tags', (req, res) => {
  const uid = visibility(req.user)
  const rows = db.prepare(`
    SELECT n.id, n.owner_id, n.project_id, n.parent_id, n.status, n.deleted_at, n.tags
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
  `).all(uid, uid).filter((row) => visibleNode(row, req.user))
  const counts = new Map()
  for (const row of rows) {
    for (const tag of String(row.tags || '').split(',').map((t) => t.trim()).filter(Boolean)) {
      counts.set(tag, (counts.get(tag) || 0) + 1)
    }
  }
  const tags = [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
  res.json({ tags })
})

app.get('/api/recent', (req, res) => {
  const viewer = req.query.public === '1' ? null : req.user
  const uid = visibility(viewer)
  const limit = Math.min(Math.max(Number(req.query.limit) || 20, 1), 100)
  const notes = db.prepare(`
    SELECT n.*, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
    ORDER BY n.updated_at DESC
  `).all(uid, uid).filter((row) => visibleNode(row, viewer)).slice(0, limit).map((row) => ({
    ...row,
    excerpt: leadExcerpt(row.content, row.title, 140),
    reading_minutes: estimateReadingMinutes(row.content),
  }))
  res.json({ notes })
})

app.get('/api/admin/notes', requireCoustea, (req, res) => {
  const notes = db.prepare(`
    SELECT n.id, n.project_id, n.title, n.tags, n.status, n.daily_date, n.created_at, n.updated_at,
           p.name AS project_name, p.status AS project_status
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.owner_id = ? AND n.kind = 'doc' AND n.deleted_at IS NULL
    ORDER BY n.updated_at DESC, n.id DESC
  `).all(req.user.id)
  res.json({ notes })
})

app.post('/api/admin/notes/batch', requireCoustea, (req, res) => {
  const { ids, action } = req.body || {}
  if (!Array.isArray(ids) || !ids.length || ids.length > 200) {
    return res.status(400).json({ error: '请选择要操作的文章（单次最多 200 篇）' })
  }
  if (!['publish', 'draft', 'trash'].includes(action)) {
    return res.status(400).json({ error: '不支持的批量操作' })
  }
  const uniqueIds = [...new Set(ids.map(Number).filter((id) => Number.isSafeInteger(id) && id > 0))]
  if (!uniqueIds.length) return res.status(400).json({ error: '文章 ID 无效' })

  const touchedProjects = new Set()
  let affected = 0
  const now = new Date().toISOString()
  db.transaction(() => {
    for (const id of uniqueIds) {
      const row = db.prepare("SELECT id, project_id FROM nodes WHERE id = ? AND owner_id = ? AND kind = 'doc' AND deleted_at IS NULL").get(id, req.user.id)
      if (!row) continue
      if (action === 'trash') {
        trashTree(row.id, now)
      } else {
        db.prepare("UPDATE nodes SET status = ?, updated_at = datetime('now') WHERE id = ?")
          .run(action === 'publish' ? 'published' : 'draft', row.id)
      }
      touchedProjects.add(row.project_id)
      affected += 1
    }
    for (const pid of touchedProjects) touchProject(pid)
  })()
  res.json({ ok: true, affected })
})

// 「今日学习」视角：当天写了什么、连续写了多少天、最近一段时间的打卡密度。
// 单人使用，统计只看当前登录用户自己的记录；未登录时返回空日历。
app.get('/api/daily', (req, res) => {
  const date = normalizeDate(req.query.date) || today()
  const days = Math.min(Math.max(Number(req.query.days) || 120, 7), 365)
  if (!req.user) {
    return res.json({ date, notes: [], streak: 0, activeDays: 0, calendar: [] })
  }
  const uid = req.user.id
  const notes = db.prepare(`
    SELECT n.id, n.title, n.project_id, n.tags, n.created_at, n.updated_at,
           n.daily_date, n.status, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL AND n.owner_id = ?
      AND n.daily_date = ?
    ORDER BY n.id DESC
  `).all(uid, date)

  const summary = dailySummary(uid, date)

  const since = new Date(`${date}T00:00:00Z`)
  since.setUTCDate(since.getUTCDate() - (days - 1))
  const calendar = db.prepare(`
    SELECT daily_date AS date, COUNT(*) AS count FROM nodes
    WHERE owner_id = ? AND kind = 'doc' AND deleted_at IS NULL
      AND daily_date >= ? AND daily_date <= ?
    GROUP BY daily_date ORDER BY daily_date
  `).all(uid, since.toISOString().slice(0, 10), date)

  res.json({ ...summary, notes, calendar })
})

// 一键写当天笔记：自动准备一个「每日学习」项目，把新笔记挂进去。
// 单人站点不需要挑项目，点一下就能开始写。
app.post('/api/daily/new', requireAuth, (req, res) => {
  const date = normalizeDate(req.body.date) || today()
  const project = ensureDailyProject(req.user.id)
  const title = String(req.body.title || '').trim() || `${date.slice(5).replace('-', ' 月 ')} 日 · 学习记录`
  const info = db.prepare(`
    INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, content, tags, sort_order, status, daily_date)
    VALUES (?, ?, 0, 'doc', ?, ?, '', '', 0, 'draft', ?)
  `).run(req.user.id, project.id, title, slugify(title) || `daily-${date}`, date)
  touchProject(project.id)
  res.status(201).json({
    node: db.prepare('SELECT * FROM nodes WHERE id = ?').get(info.lastInsertRowid),
    project,
  })
})

function ensureDailyProject(ownerId) {
  const found = db.prepare(
    "SELECT * FROM projects WHERE owner_id = ? AND slug = 'daily'",
  ).get(ownerId)
  if (found) return found
  const info = db.prepare(`
    INSERT INTO projects (owner_id, name, slug, description, status, sort_order)
    VALUES (?, '每日学习', 'daily', '每天写下的代码学习笔记，按日期归档。', 'published', -1)
  `).run(ownerId)
  return db.prepare('SELECT * FROM projects WHERE id = ?').get(info.lastInsertRowid)
}

app.post('/api/uploads', requireAuth, uploadLimiter, (req, res) => {
  const mime = String(req.body.mimeType || '')
  const data = String(req.body.data || '')
  const ext = MIME_EXT[mime]
  if (!ext) return res.status(400).json({ error: '仅支持 PNG / JPEG / GIF / WebP / PDF' })
  if (!data) return res.status(400).json({ error: '文件内容为空' })
  const buffer = Buffer.from(data, 'base64')
  if (!buffer.length) return res.status(400).json({ error: '文件内容无效' })
  if (buffer.length > 10 * 1024 * 1024) return res.status(400).json({ error: '文件不能超过 10MB' })
  const ownerDir = path.join(UPLOAD_DIR, String(req.user.id))
  fs.mkdirSync(ownerDir, { recursive: true })
  const filename = `${crypto.randomUUID()}${ext}`
  fs.writeFileSync(path.join(ownerDir, filename), buffer)
  res.status(201).json({
    url: `/api/uploads/${req.user.id}/${filename}`,
    name: String(req.body.fileName || 'attachment'),
  })
})

function uploadPath(req, res) {
  const owner = req.params.owner
  const file = req.params.file
  if (!/^\d+$/.test(owner) || !/^[0-9a-f-]{36}\.(png|jpg|gif|webp|pdf)$/i.test(file)) {
    res.status(400).json({ error: '文件路径无效' })
    return null
  }
  return path.join(UPLOAD_DIR, owner, file)
}

app.get('/api/uploads/:owner/:file', (req, res) => {
  const full = uploadPath(req, res)
  if (!full) return
  if (!fs.existsSync(full)) return res.status(404).json({ error: '文件不存在' })
  // 文件名是随机 UUID，内容不会变，可以长期缓存
  res.setHeader('Cache-Control', 'public, max-age=31536000, immutable')
  res.sendFile(full)
})

app.delete('/api/uploads/:owner/:file', requireAuth, (req, res) => {
  if (String(req.user.id) !== req.params.owner) {
    return res.status(403).json({ error: '无权删除他人的文件' })
  }
  const full = uploadPath(req, res)
  if (!full) return
  if (!fs.existsSync(full)) return res.status(404).json({ error: '文件不存在' })
  fs.unlinkSync(full)
  res.json({ ok: true })
})

app.get('/api/site', (req, res) => {
  const viewer = req.query.public === '1' ? null : req.user
  const uid = visibility(viewer)
  const projectCount = db.prepare(
    "SELECT COUNT(*) AS c FROM projects WHERE status = 'published' OR owner_id = ?",
  ).get(uid).c
  const noteCount = db.prepare("SELECT * FROM projects WHERE status = 'published' OR owner_id = ?")
    .all(uid).reduce((sum, project) => sum + projectSummary(project, viewer).doc_count, 0)
  res.json({
    site: {
      name: SITE_NAME,
      description: SITE_DESCRIPTION,
      projectCount,
      noteCount,
      url: siteUrl(req),
    },
  })
})

// 打卡摘要：今天写了几篇、连续多少天、累计活跃天数。首页与 /api/daily 共用。
function dailySummary(uid, date = today()) {
  const active = db.prepare(`
    SELECT DISTINCT daily_date FROM nodes
    WHERE owner_id = ? AND kind = 'doc' AND deleted_at IS NULL AND daily_date <> ''
    ORDER BY daily_date DESC
  `).all(uid).map((row) => row.daily_date)
  const activeSet = new Set(active)
  let streak = 0
  const cursor = new Date(`${date}T00:00:00Z`)
  if (!activeSet.has(date)) cursor.setUTCDate(cursor.getUTCDate() - 1)
  while (activeSet.has(cursor.toISOString().slice(0, 10))) {
    streak += 1
    cursor.setUTCDate(cursor.getUTCDate() - 1)
  }
  const todayCount = db.prepare(`
    SELECT COUNT(*) AS c FROM nodes
    WHERE owner_id = ? AND kind = 'doc' AND deleted_at IS NULL AND daily_date = ?
  `).get(uid, date).c
  return { date, todayCount, streak, activeDays: active.length }
}

// 首页一次拿齐：站点信息、项目、最近笔记、标签与合计，避免首屏连发 4 个请求
app.get('/api/overview', (req, res) => {
  const viewer = req.query.public === '1' ? null : req.user
  const uid = visibility(viewer)
  const projectRows = db.prepare(`
    SELECT * FROM projects WHERE status = 'published' OR owner_id = ?
    ORDER BY sort_order, id
  `).all(uid)
  const projects = projectRows.map((project) => projectSummary(project, viewer))

  const recent = db.prepare(`
    SELECT n.id, n.owner_id, n.project_id, n.parent_id, n.title, n.content, n.tags, n.status, n.deleted_at, n.updated_at,
           p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
    ORDER BY n.updated_at DESC
  `).all(uid, uid).filter((row) => visibleNode(row, viewer)).slice(0, 18).map((row) => ({
    id: row.id,
    project_id: row.project_id,
    project_name: row.project_name,
    title: row.title,
    tags: row.tags,
    status: row.status,
    updated_at: row.updated_at,
    excerpt: leadExcerpt(row.content, row.title, 140),
    reading_minutes: estimateReadingMinutes(row.content),
  }))

  const tagRows = db.prepare(`
    SELECT n.id, n.owner_id, n.project_id, n.parent_id, n.status, n.deleted_at, n.tags
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
  `).all(uid, uid).filter((row) => visibleNode(row, viewer))
  const counts = new Map()
  for (const row of tagRows) {
    for (const tag of String(row.tags || '').split(',').map((t) => t.trim()).filter(Boolean)) {
      counts.set(tag, (counts.get(tag) || 0) + 1)
    }
  }
  const tags = [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
    .slice(0, 14)

  res.json({
    site: {
      name: SITE_NAME,
      description: SITE_DESCRIPTION,
      url: siteUrl(req),
      projectCount: projects.length,
      noteCount: projects.reduce((sum, project) => sum + project.doc_count, 0),
    },
    projects,
    recent,
    tags,
    daily: uid ? dailySummary(uid) : { date: today(), todayCount: 0, streak: 0, activeDays: 0 },
  })
})

function publishedNotes(limit) {
  return db.prepare(`
    SELECT n.*, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND n.status = 'published' AND p.status = 'published'
    ORDER BY n.updated_at DESC, n.id DESC
  `).all().filter((row) => visibleNode(row, null)).slice(0, limit)
}

app.get('/rss.xml', (req, res) => {
  const base = siteUrl(req)
  const items = publishedNotes(30).map((note) => {
    const description = plainText(note.content).slice(0, 300)
    const link = `${base}/p/${note.project_id}/n/${note.id}`
    const date = new Date(`${String(note.updated_at).replace(' ', 'T')}Z`).toUTCString()
    return `    <item>
      <title>${escapeXml(note.title)}</title>
      <link>${escapeXml(link)}</link>
      <guid isPermaLink="true">${escapeXml(link)}</guid>
      <description>${escapeXml(description)}</description>
      <category>${escapeXml(note.project_name)}</category>
      <pubDate>${date}</pubDate>
    </item>`
  }).join('\n')

  res.type('application/rss+xml').send(`<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>${escapeXml(SITE_NAME)}</title>
    <link>${escapeXml(base)}</link>
    <description>${escapeXml(SITE_DESCRIPTION)}</description>
    <language>zh-CN</language>
${items}
  </channel>
</rss>`)
})

app.get('/sitemap.xml', (req, res) => {
  const base = siteUrl(req)
  const projects = db.prepare(
    "SELECT id, updated_at FROM projects WHERE status = 'published' ORDER BY id",
  ).all()
  const notes = db.prepare(`
    SELECT n.id, n.owner_id, n.project_id, n.parent_id, n.status, n.deleted_at, n.updated_at
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND n.status = 'published' AND p.status = 'published'
    ORDER BY n.project_id, n.id
  `).all().filter((row) => visibleNode(row, null))

  const urls = [
    { loc: `${base}/`, priority: '1.0' },
    ...projects.map((project) => ({
      loc: `${base}/p/${project.id}`,
      lastmod: String(project.updated_at).slice(0, 10),
      priority: '0.8',
    })),
    ...notes.map((note) => ({
      loc: `${base}/p/${note.project_id}/n/${note.id}`,
      lastmod: String(note.updated_at).slice(0, 10),
      priority: '0.6',
    })),
  ]

  const body = urls.map((entry) => `  <url>
    <loc>${escapeXml(entry.loc)}</loc>${entry.lastmod ? `\n    <lastmod>${entry.lastmod}</lastmod>` : ''}
    <priority>${entry.priority}</priority>
  </url>`).join('\n')

  res.type('application/xml').send(`<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${body}
</urlset>`)
})

app.get('/robots.txt', (req, res) => {
  const base = siteUrl(req)
  res.type('text/plain').send([
    'User-agent: *',
    'Allow: /',
    'Disallow: /admin',
    'Disallow: /edit',
    'Disallow: /login',
    'Disallow: /api/',
    '',
    `Sitemap: ${base}/sitemap.xml`,
    '',
  ].join('\n'))
})

const distDir = path.join(__dirname, '..', 'dist')
const hasBuild = fs.existsSync(path.join(distDir, 'index.html'))
if (hasBuild) {
  app.use(express.static(distDir, {
    index: false,
    setHeaders(res, filePath) {
      // 带哈希的产物可以永久缓存，入口 HTML 必须每次校验
      if (/[\\/]assets[\\/]/.test(filePath)) {
        res.setHeader('Cache-Control', 'public, max-age=31536000, immutable')
      }
    },
  }))
  app.get('*', (req, res, next) => {
    if (req.path.startsWith('/api') || req.path.startsWith('/rss.xml') || req.path.startsWith('/sitemap.xml')) {
      return next()
    }
    // 看起来像静态文件的路径（/assets/x.js、/favicon.ico、/a.png）不要回退成 index.html：
    // 否则旧缓存里的失效资源会拿到 200 + text/html，浏览器报 MIME 错而不是干脆 404。
    if (req.path.startsWith('/assets/') || /\.[a-z0-9]{2,5}$/i.test(req.path)) {
      return res.status(404).type('txt').send('Not Found')
    }
    res.setHeader('Cache-Control', 'no-cache')
    res.sendFile(path.join(distDir, 'index.html'))
  })
}

app.use((req, res) => {
  res.status(404).json({ error: '接口或页面不存在' })
})

// 统一错误出口。body-parser 抛出的错误自带 type / status，如果一律回 500，
// 用户看到的是「服务器内部错误」，而实际原因是请求本身有问题（JSON 写坏了、
// 正文超过 24mb 上限），既误导排查也污染 5xx 监控。
app.use((err, _req, res, _next) => {
  if (res.headersSent) return

  if (err && (err.type === 'entity.parse.failed' || err instanceof SyntaxError)) {
    return res.status(400).json({ error: '请求体不是合法的 JSON' })
  }
  if (err && err.type === 'entity.too.large') {
    return res.status(413).json({ error: '请求体过大，单次请求上限 24MB' })
  }
  if (err && err.type === 'encoding.unsupported') {
    return res.status(415).json({ error: '不支持的请求体编码' })
  }

  console.error(err)
  res.status(500).json({ error: '服务器内部错误' })
})

const PORT = Number(process.env.PORT || 3001)
const HOST = process.env.HOST || '0.0.0.0'

seedDefaultAdmin()

if (!hasBuild && IS_PROD) {
  console.warn('[提示] 未找到 dist 目录，仅提供 API。请先执行 npm run build。')
}

// 生产环境启动自检：单人自托管最容易漏的几项，宁可启动时刷一屏提醒，
// 也不要等 RSS 里全是 http 链接或者被扫站脚本用默认密码登进来才发现。
function auditProductionConfig() {
  if (!IS_PROD) return
  const warnings = []
  if (!process.env.JWT_SECRET) {
    warnings.push('JWT_SECRET 未设置，正在用 data/.jwt-secret 自动生成的密钥；迁移或重建卷后所有登录会失效')
  }
  if (!process.env.SITE_URL) {
    warnings.push('SITE_URL 未设置，RSS / sitemap / robots.txt 的绝对链接会按请求头推断，反代后可能是 http 或内网地址')
  }
  if (!allowedOrigins.length) {
    warnings.push('ALLOWED_ORIGINS 为空，CORS 允许任意来源；对外站点建议填真实域名')
  }
  // TRUST_PROXY=1 是「前面有一层 nginx」时的正确配置，不能当成问题来报，
  // 否则按 README 部署的每次启动都会刷一条假警告，久而久之就没人看自检输出了。
  // 真正需要提醒的是完全没配的情况：反代后 express 会把所有请求都记成 nginx 的 IP。
  if (process.env.TRUST_PROXY === undefined) {
    warnings.push('TRUST_PROXY 未设置。前面有一层 nginx 就填 1，直连公网就填 false，否则登录限流会把所有人算成同一个 IP')
  }
  if (defaultAdminSeeded) {
    warnings.push('新库用内置默认密码 coustea 建了管理员账号，请立刻在「账户设置」里改掉')
  }
  if (!warnings.length) {
    console.log('生产自检通过：JWT_SECRET / SITE_URL / ALLOWED_ORIGINS / TRUST_PROXY / DEFAULT_ADMIN_PASSWORD 均已配置。')
    return
  }
  console.warn(`[生产自检] 发现 ${warnings.length} 项待处理：`)
  warnings.forEach((item, index) => console.warn(`  ${index + 1}. ${item}`))
}

auditProductionConfig()

const server = app.listen(PORT, HOST, () => {
  console.log(`拾页 · Folio API 已启动：http://localhost:${PORT}`)
  if (!IS_PROD) {
    console.log('开发模式：前端由 vite 提供（npm run dev），已构建的 dist 会同时被托管。')
  }
})

server.keepAliveTimeout = 65000
server.headersTimeout = 70000

let shuttingDown = false
function shutdown(signal) {
  if (shuttingDown) return
  shuttingDown = true
  console.log(`收到 ${signal}，正在关闭服务…`)
  const done = () => {
    closeDatabase()
    process.exit(0)
  }
  server.close(done)
  // 兜底：10 秒内没有关完就强制退出，避免容器 k8s 卡在 terminating
  setTimeout(() => {
    closeDatabase()
    process.exit(0)
  }, 10000).unref()
}

process.on('SIGTERM', () => shutdown('SIGTERM'))
process.on('SIGINT', () => shutdown('SIGINT'))
process.on('unhandledRejection', (reason) => {
  console.error('未处理的 Promise 拒绝：', reason)
})
