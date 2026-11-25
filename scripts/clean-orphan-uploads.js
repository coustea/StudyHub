#!/usr/bin/env node
/**
 * 清理没有被任何笔记引用的附件文件。
 *
 * 为什么需要这个脚本：
 *   上传接口把文件写到 data/uploads/<userId>/<uuid>.<ext>，笔记正文里只存一个
 *   Markdown 图片链接。删除笔记（或删掉正文里的图片语法）时，磁盘上的文件不会
 *   跟着消失 —— 时间一长 uploads/ 会攒下一堆没人引用的图片，备份体积也一起变大。
 *
 * 判定规则：
 *   扫描所有笔记的正文（含回收站里的，因为恢复后还要能显示），
 *   把 /api/uploads/<owner>/<file> 形式的路径收集成白名单；
 *   磁盘上不在白名单里的文件即为孤儿。
 *
 * 用法：
 *   node scripts/clean-orphan-uploads.js            # 只列出，不删除（默认）
 *   node scripts/clean-orphan-uploads.js --apply    # 真的删除
 *   node scripts/clean-orphan-uploads.js --apply --days 30   # 只删 30 天前的
 *
 * 建议先跑一次不带 --apply 的，看清楚要删什么再动手。
 */

const fs = require('fs')
const path = require('path')

const ROOT_DIR = path.join(__dirname, '..')

// 与 server/index.js 完全一致的 .env 加载逻辑：保证 DATA_DIR 指向同一个库
function loadEnvFile(file) {
  if (!fs.existsSync(file)) return
  const text = fs.readFileSync(file, 'utf8')
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const index = trimmed.indexOf('=')
    if (index <= 0) continue
    const key = trimmed.slice(0, index).trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue
    // 命令行传入的环境变量优先，不被 .env 覆盖
    if (process.env[key] !== undefined) continue
    let value = trimmed.slice(index + 1).trim()
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    process.env[key] = value
  }
}

loadEnvFile(process.env.ENV_FILE || path.join(ROOT_DIR, '.env'))
if (process.env.DATA_DIR && !path.isAbsolute(process.env.DATA_DIR)) {
  process.env.DATA_DIR = path.resolve(ROOT_DIR, process.env.DATA_DIR)
}

const DATA_DIR = process.env.DATA_DIR || path.join(ROOT_DIR, 'data')
const UPLOAD_DIR = path.join(DATA_DIR, 'uploads')
const DB_FILE = path.join(DATA_DIR, 'notes.db')

const args = process.argv.slice(2)
const APPLY = args.includes('--apply')
const daysIndex = args.indexOf('--days')
const MIN_AGE_DAYS = daysIndex >= 0 ? Number(args[daysIndex + 1]) : 0

if (!fs.existsSync(DB_FILE)) {
  console.error(`[错误] 找不到数据库：${DB_FILE}`)
  process.exit(1)
}
if (!fs.existsSync(UPLOAD_DIR)) {
  console.log(`[信息] 附件目录不存在，无需清理：${UPLOAD_DIR}`)
  process.exit(0)
}
if (!Number.isFinite(MIN_AGE_DAYS) || MIN_AGE_DAYS < 0) {
  console.error('[错误] --days 需要一个非负整数')
  process.exit(1)
}

const Database = require('better-sqlite3')
const db = new Database(DB_FILE, { readonly: true })

// 含回收站里的笔记：恢复后图片还要能显示，所以不能只扫未删除的
const rows = db.prepare("SELECT content FROM nodes WHERE kind = 'doc'").all()
db.close()

const referenced = new Set()
// 同时兼容 /api/uploads/1/xxx.png 与带域名的绝对地址
const pattern = /\/api\/uploads\/(\d+)\/([0-9a-fA-F-]{36}\.[A-Za-z0-9]+)/g
for (const row of rows) {
  const content = String(row.content || '')
  let match
  while ((match = pattern.exec(content)) !== null) {
    referenced.add(`${match[1]}/${match[2].toLowerCase()}`)
  }
}

const cutoff = MIN_AGE_DAYS > 0 ? Date.now() - MIN_AGE_DAYS * 86400000 : Infinity
const orphans = []
let totalFiles = 0
let totalBytes = 0

for (const ownerEntry of fs.readdirSync(UPLOAD_DIR, { withFileTypes: true })) {
  if (!ownerEntry.isDirectory()) continue
  const ownerDir = path.join(UPLOAD_DIR, ownerEntry.name)
  for (const fileEntry of fs.readdirSync(ownerDir, { withFileTypes: true })) {
    if (!fileEntry.isFile()) continue
    totalFiles += 1
    const key = `${ownerEntry.name}/${fileEntry.name.toLowerCase()}`
    if (referenced.has(key)) continue
    const full = path.join(ownerDir, fileEntry.name)
    const stat = fs.statSync(full)
    if (stat.mtimeMs > cutoff) continue
    totalBytes += stat.size
    orphans.push({ full, size: stat.size, ageDays: Math.floor((Date.now() - stat.mtimeMs) / 86400000) })
  }
}

console.log(`[信息] 数据目录：${DATA_DIR}`)
console.log(`[信息] 笔记引用到的附件：${referenced.size} 个`)
console.log(`[信息] 磁盘上的附件：${totalFiles} 个`)
console.log(`[信息] 孤儿附件：${orphans.length} 个，共 ${(totalBytes / 1024).toFixed(1)} KB`)

if (!orphans.length) {
  console.log('[信息] 没有需要清理的文件')
  process.exit(0)
}

for (const item of orphans.slice(0, 50)) {
  console.log(`  ${path.relative(ROOT_DIR, item.full)}  ${(item.size / 1024).toFixed(1)} KB  ${item.ageDays} 天前`)
}
if (orphans.length > 50) console.log(`  ... 还有 ${orphans.length - 50} 个`)

if (!APPLY) {
  console.log('\n[提示] 这是预演，没有删除任何文件。确认无误后加 --apply 再跑一次。')
  process.exit(0)
}

let removed = 0
for (const item of orphans) {
  try {
    fs.unlinkSync(item.full)
    removed += 1
  } catch (error) {
    console.error(`[错误] 删除失败 ${item.full}：${error.message}`)
  }
}
console.log(`\n[信息] 已删除 ${removed} 个孤儿附件，释放 ${(totalBytes / 1024).toFixed(1)} KB`)
