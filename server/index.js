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

const SITE_NAME = process.env.SITE_NAME || '笔记库'
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

  const legacy = username === 'coustea'
    ? db.prepare("SELECT id FROM users WHERE username = 'cosustea'").get()
    : null
  if (legacy) {
    db.prepare('UPDATE users SET username = ? WHERE id = ?').run(username, legacy.id)
    return
  }

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

function excerpt(text, query) {
  const clean = plainText(text)
  const at = clean.toLowerCase().indexOf(query.toLowerCase())
  if (at < 0) return clean.slice(0, 140) + (clean.length > 140 ? '…' : '')
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

app.get('/api/projects', (req, res) => {
  const uid = req.user ? req.user.id : 0
  const rows = db.prepare(`
    SELECT p.*,
      (SELECT COUNT(*) FROM nodes n
        WHERE n.project_id = p.id AND n.kind = 'doc' AND n.deleted_at IS NULL
          AND (n.status = 'published' OR n.owner_id = ?)) AS doc_count,
      (SELECT COUNT(*) FROM nodes n
        WHERE n.project_id = p.id AND n.kind = 'folder' AND n.deleted_at IS NULL
          AND (n.status = 'published' OR n.owner_id = ?)) AS folder_count,
      (SELECT GROUP_CONCAT(n.tags, ',') FROM nodes n
        WHERE n.project_id = p.id AND n.kind = 'doc' AND n.tags <> '' AND n.deleted_at IS NULL
          AND (n.status = 'published' OR n.owner_id = ?)) AS tag_blob
    FROM projects p
    WHERE p.status = 'published' OR p.owner_id = ?
    ORDER BY p.sort_order, p.id
  `).all(uid, uid, uid, uid)
  const projects = rows.map(({ tag_blob: tagBlob, ...project }) => ({
    ...project,
    tags: [...new Set(String(tagBlob || '').split(',').map((tag) => tag.trim()).filter(Boolean))].slice(0, 4),
  }))
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
  const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.params.id)
  if (!project) return res.status(404).json({ error: '项目不存在' })
  if (!visible(project, req.user)) return res.status(404).json({ error: '项目不存在' })
  const uid = req.user ? req.user.id : 0
  const nodes = db.prepare(`
    SELECT * FROM nodes
    WHERE project_id = ? AND deleted_at IS NULL AND (status = 'published' OR owner_id = ?)
    ORDER BY sort_order, id
  `).all(project.id, uid)
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
  if (next.status === 'published') {
    db.prepare('UPDATE nodes SET status = ? WHERE project_id = ? AND owner_id = ? AND deleted_at IS NULL')
      .run('published', row.id, req.user.id)
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
  if (parentId) {
    const parent = db.prepare('SELECT * FROM nodes WHERE id = ?').get(parentId)
    if (!parent || parent.project_id !== project.id) {
      return res.status(400).json({ error: '父目录不属于该项目' })
    }
  }
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
  if (!row || row.deleted_at) return res.status(404).json({ error: '内容不存在' })
  if (!visible(row, req.user)) return res.status(404).json({ error: '内容不存在' })
  res.json({ node: row })
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
  if (next.parent_id) {
    const parent = db.prepare('SELECT * FROM nodes WHERE id = ?').get(next.parent_id)
    if (!parent || parent.project_id !== row.project_id || parent.id === row.id) {
      return res.status(400).json({ error: '父目录无效' })
    }
    if (isDescendant(next.parent_id, row.id)) {
      return res.status(400).json({ error: '不能移动到自己的子目录中' })
    }
  }
  if (Object.keys(next).length) {
    const set = Object.keys(next).map((key) => `${key} = ?`).join(', ')
    db.prepare(`UPDATE nodes SET ${set}, updated_at = datetime('now') WHERE id = ?`)
      .run(...Object.values(next), row.id)
  }
  touchProject(row.project_id)
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

  const findOrCreateFolder = (parent, title) => {
    const slug = slugify(title) || 'folder'
    const found = db.prepare(`
      SELECT id FROM nodes
      WHERE project_id = ? AND parent_id = ? AND kind = 'folder' AND slug = ?
    `).get(project.id, parent, slug)
    if (found) return found.id
    const info = db.prepare(`
      INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, status)
      VALUES (?, ?, ?, 'folder', ?, ?, ?)
    `).run(userId, project.id, parent, title, slug, status)
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
      const order = Number(meta.order ?? meta.sidebar_position ?? meta.sort_order ?? index)
      // 导入时识别 front-matter 里的日期，让历史笔记也能落到正确的学习日
      const dailyDate = normalizeDate(meta.date || meta.created || meta.daily)
        || String(meta.date || '').slice(0, 10) || today()
      db.prepare(`
        INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, content, tags, sort_order, status, daily_date)
        VALUES (?, ?, ?, 'doc', ?, ?, ?, ?, ?, ?, ?)
      `).run(
        userId, project.id, parent, title,
        slugify(title) || `doc-${Date.now()}-${index}`,
        parsed.content || '', tags, Number.isFinite(order) ? order : index, status,
        /^\d{4}-\d{2}-\d{2}$/.test(dailyDate) ? dailyDate : today(),
      )
      docs += 1
    })
    touchProject(project.id)
  })
  tx()
  return { imported: docs, skipped }
}

app.post('/api/import', requireSiteOwner, (req, res) => {
  const project = db.prepare('SELECT * FROM projects WHERE id = ?').get(req.body.projectId)
  if (!project) return res.status(404).json({ error: '项目不存在' })
  if (!assertOwner(project, req.user, res)) return
  const files = Array.isArray(req.body.files) ? req.body.files : []
  const invalid = validateImportFiles(files)
  if (invalid) return res.status(400).json({ error: invalid })

  const status = req.body.status === 'published' ? 'published' : 'draft'
  const result = importMarkdownTree({
    project, userId: req.user.id, parentId: req.body.parentId, files, status,
  })
  res.json({ ok: true, imported: result.imported, skipped: result.skipped.length })
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
  const uid = visibility(req.user)

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
    SELECT n.id, n.title, n.project_id, n.content, n.tags, n.updated_at, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
      AND ${noteWhere}
    ORDER BY n.updated_at DESC LIMIT 100
  `).all(uid, uid, ...noteParams)

  const notes = rows.map((row) => ({
    ...row,
    // 摘要围绕第一个词截取，多个词时用第一个最有区分度的
    excerpt: excerpt(row.content, terms[0]),
  }))
  res.json({ query: q, projects, notes, terms })
})

app.get('/api/tags', (req, res) => {
  const uid = visibility(req.user)
  const rows = db.prepare(`
    SELECT n.tags FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
  `).all(uid, uid)
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
  const uid = visibility(req.user)
  const limit = Math.min(Math.max(Number(req.query.limit) || 20, 1), 100)
  const notes = db.prepare(`
    SELECT n.id, n.title, n.project_id, n.tags, n.updated_at, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
    ORDER BY n.updated_at DESC LIMIT ?
  `).all(uid, uid, limit)
  res.json({ notes })
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
  const uid = visibility(req.user)
  const projectCount = db.prepare(
    "SELECT COUNT(*) AS c FROM projects WHERE status = 'published' OR owner_id = ?",
  ).get(uid).c
  const noteCount = db.prepare(`
    SELECT COUNT(*) AS c FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
  `).get(uid, uid).c
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
  const uid = visibility(req.user)
  const projectRows = db.prepare(`
    SELECT p.*,
      (SELECT COUNT(*) FROM nodes n
        WHERE n.project_id = p.id AND n.kind = 'doc' AND n.deleted_at IS NULL
          AND (n.status = 'published' OR n.owner_id = ?)) AS doc_count,
      (SELECT COUNT(*) FROM nodes n
        WHERE n.project_id = p.id AND n.kind = 'folder' AND n.deleted_at IS NULL
          AND (n.status = 'published' OR n.owner_id = ?)) AS folder_count,
      (SELECT GROUP_CONCAT(n.tags, ',') FROM nodes n
        WHERE n.project_id = p.id AND n.kind = 'doc' AND n.tags <> '' AND n.deleted_at IS NULL
          AND (n.status = 'published' OR n.owner_id = ?)) AS tag_blob
    FROM projects p
    WHERE p.status = 'published' OR p.owner_id = ?
    ORDER BY p.sort_order, p.id
  `).all(uid, uid, uid, uid)
  const projects = projectRows.map(({ tag_blob: tagBlob, ...project }) => ({
    ...project,
    tags: [...new Set(String(tagBlob || '').split(',').map((tag) => tag.trim()).filter(Boolean))].slice(0, 4),
  }))

  const recent = db.prepare(`
    SELECT n.id, n.title, n.project_id, n.tags, n.updated_at, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
    ORDER BY n.updated_at DESC LIMIT 6
  `).all(uid, uid)

  const tagRows = db.prepare(`
    SELECT n.tags FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND (n.status = 'published' OR n.owner_id = ?)
      AND (p.status = 'published' OR p.owner_id = ?)
  `).all(uid, uid)
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
    SELECT n.id, n.title, n.content, n.tags, n.updated_at, n.created_at,
           n.project_id, p.name AS project_name
    FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND n.status = 'published' AND p.status = 'published'
    ORDER BY n.updated_at DESC, n.id DESC
    LIMIT ?
  `).all(limit)
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
    SELECT n.id, n.project_id, n.updated_at FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.kind = 'doc' AND n.deleted_at IS NULL
      AND n.status = 'published' AND p.status = 'published'
    ORDER BY n.project_id, n.id
  `).all()

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
    'Disallow: /edit',
    'Disallow: /login',
    'Disallow: /settings',
    'Disallow: /trash',
    'Disallow: /daily',
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
  console.log(`笔记库 API 已启动：http://localhost:${PORT}`)
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
