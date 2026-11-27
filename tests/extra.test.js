// 每日学习 / 回收站 / 软删除可见性 —— 与 api.test.js 共用同一套启动方式，独立进程独立数据目录。
const { test, before, after } = require('node:test')
const assert = require('node:assert/strict')
const { spawn, spawnSync } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')
const os = require('node:os')
const Database = require('better-sqlite3')
const bcrypt = require('bcryptjs')

const PORT = 39002
const DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'notes-extra-test-'))
const ROOT = path.join(__dirname, '..')
const base = `http://127.0.0.1:${PORT}`
let server = null

async function call(urlPath, method = 'GET', body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(base + urlPath, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data = null
  try { data = await res.json() } catch { data = null }
  return { status: res.status, data }
}

before(async () => {
  server = spawn(process.execPath, ['server/index.js'], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), DATA_DIR, JWT_SECRET: 'test-only-secret', SITE_OWNER: 'owner' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('服务启动超时')), 20000)
    server.stdout.on('data', (chunk) => {
      if (String(chunk).includes('API 已启动')) {
        clearTimeout(timer)
        resolve()
      }
    })
    server.on('exit', (code) => {
      clearTimeout(timer)
      reject(new Error(`服务提前退出，代码 ${code}`))
    })
  })
  const db = new Database(path.join(DATA_DIR, 'notes.db'))
  db.pragma('busy_timeout = 5000')
  const insert = db.prepare('INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)')
  insert.run('owner', bcrypt.hashSync('pass123', 10), '站长')
  insert.run('other', bcrypt.hashSync('pass123', 10), '其他用户')
  db.close()
})

after(async () => {
  if (server && !server.killed) {
    const exited = new Promise((resolve) => server.once('exit', resolve))
    server.kill()
    await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 3000))])
  }
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      fs.rmSync(DATA_DIR, { recursive: true, force: true })
      break
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
  }
})

test('每日学习与回收站', async (t) => {
  const state = {}

  await t.test('登录', async () => {
    const owner = await call('/api/auth/login', 'POST', { username: 'owner', password: 'pass123' })
    assert.equal(owner.status, 200)
    state.owner = owner.data.token
    state.ownerId = owner.data.user.id
    const other = await call('/api/auth/login', 'POST', { username: 'other', password: 'pass123' })
    assert.equal(other.status, 200)
    state.other = other.data.token
  })

  await t.test('每日学习视角与打卡统计', async () => {
    const guest = await call('/api/daily')
    assert.equal(guest.status, 200)
    assert.equal(guest.data.notes.length, 0, '未登录时不应返回笔记')
    assert.deepEqual(guest.data.calendar, [])

    assert.equal((await call('/api/daily/new', 'POST', {})).status, 401)

    const day = '2026-01-15'
    let res = await call('/api/daily/new', 'POST', { date: day }, state.owner)
    assert.equal(res.status, 201)
    assert.equal(res.data.node.daily_date, day, '应写入指定学习日')
    assert.equal(res.data.node.status, 'draft')
    assert.equal(res.data.project.slug, 'daily', '应自动创建每日学习项目')
    state.dailyNodeId = res.data.node.id
    state.dailyPid = res.data.project.id

    res = await call('/api/daily/new', 'POST', { date: day, title: '手写标题' }, state.owner)
    assert.equal(res.status, 201)
    assert.equal(res.data.node.title, '手写标题')
    assert.equal(res.data.project.id, state.dailyPid, '同一天复用同一个项目')
    state.dailyNode2Id = res.data.node.id

    const daily = await call(`/api/daily?date=${day}`, 'GET', undefined, state.owner)
    assert.equal(daily.status, 200)
    assert.equal(daily.data.notes.length, 2)
    assert.equal(daily.data.todayCount, 2)
    assert.ok(daily.data.streak >= 1, '当天有记录时连续天数至少为 1')
    const cell = daily.data.calendar.find((c) => c.date === day)
    assert.ok(cell && cell.count === 2, '日历应统计当天篇数')

    // 非法日期回落到今天，不会污染统计
    const fallback = await call('/api/daily?date=2026-13-99', 'GET', undefined, state.owner)
    assert.equal(fallback.status, 200)
    assert.match(fallback.data.date, /^\d{4}-\d{2}-\d{2}$/)

    // 别人的日历看不到我的笔记
    const otherDaily = await call(`/api/daily?date=${day}`, 'GET', undefined, state.other)
    assert.equal(otherDaily.data.notes.length, 0, '每日学习按用户隔离')

    const overview = await call('/api/overview', 'GET', undefined, state.owner)
    assert.ok(overview.data.daily.activeDays >= 1, '首页聚合应带上打卡摘要')
    assert.equal(overview.data.daily.date.length, 10)
    const guestOverview = await call('/api/overview')
    assert.equal(guestOverview.data.daily.activeDays, 0)

    // 不带日期时应落在今天，并计入今日篇数
    const todayNote = await call('/api/daily/new', 'POST', {}, state.owner)
    assert.equal(todayNote.status, 201)
    const todaySummary = await call('/api/overview', 'GET', undefined, state.owner)
    assert.equal(todaySummary.data.daily.todayCount, 1, '今天的笔记应计入今日篇数')
    assert.equal(todaySummary.data.daily.streak, 1, '今天写过即连续 1 天')

    // 软删除的笔记不能计入打卡统计，否则回收站里的东西还在「今天写了 N 篇」里数着
    const todayId = todayNote.data.node.id
    await call(`/api/nodes/${todayId}`, 'DELETE', undefined, state.owner)
    const afterTrash = await call('/api/overview', 'GET', undefined, state.owner)
    assert.equal(afterTrash.data.daily.todayCount, 0, '软删除后今日篇数应归零')
    const afterTrashDaily = await call('/api/daily', 'GET', undefined, state.owner)
    assert.ok(
      !afterTrashDaily.data.notes.some((n) => n.id === todayId),
      '软删除的笔记不应出现在每日列表',
    )
    // 恢复后统计要回来
    await call(`/api/trash/${todayId}/restore`, 'POST', undefined, state.owner)
    const afterRestore = await call('/api/overview', 'GET', undefined, state.owner)
    assert.equal(afterRestore.data.daily.todayCount, 1, '恢复后今日篇数应回来')

    await call(`/api/nodes/${todayId}?purge=1`, 'DELETE', undefined, state.owner)
    const afterPurge = await call('/api/overview', 'GET', undefined, state.owner)
    assert.equal(afterPurge.data.daily.todayCount, 0, '彻底删除后今日篇数归零')
  })

  await t.test('回收站：软删除、恢复与彻底删除', async () => {
    const project = await call('/api/projects', 'POST', { name: '回收站项目', status: 'published' }, state.owner)
    assert.equal(project.status, 201)
    const pid = project.data.project.id
    const folder = await call('/api/nodes', 'POST', {
      projectId: pid, parentId: 0, kind: 'folder', title: '待删目录', status: 'published',
    }, state.owner)
    const folderId = folder.data.node.id
    const doc = await call('/api/nodes', 'POST', {
      projectId: pid, parentId: folderId, kind: 'doc', title: '待删笔记',
      content: '# 待删笔记\n\n回收站唯一关键词：影无踪', status: 'published',
    }, state.owner)
    const docId = doc.data.node.id

    const del = await call(`/api/nodes/${docId}`, 'DELETE', undefined, state.owner)
    assert.equal(del.status, 200)
    assert.equal(del.data.trashed, true, '默认应进回收站而不是直接删除')
    assert.equal((await call(`/api/nodes/${docId}`)).status, 404)

    const searched = await call('/api/search?q=影无踪')
    assert.equal(searched.data.notes.length, 0, '回收站内容不应被搜索到')
    const recent = await call('/api/recent?limit=50')
    assert.equal(recent.data.notes.some((n) => n.id === docId), false, '回收站内容不应出现在最近更新')

    let trash = await call('/api/trash', 'GET', undefined, state.owner)
    assert.equal(trash.status, 200)
    assert.equal(trash.data.total, 1)
    assert.ok(trash.data.nodes.some((n) => n.id === docId && n.project_name === '回收站项目'))
    assert.equal((await call('/api/trash', 'GET', undefined, state.other)).data.total, 0, '回收站按用户隔离')

    const restored = await call(`/api/trash/${docId}/restore`, 'POST', undefined, state.owner)
    assert.equal(restored.status, 200)
    assert.equal((await call(`/api/nodes/${docId}`)).status, 200)
    assert.equal((await call('/api/trash', 'GET', undefined, state.owner)).data.total, 0)

    // 父目录先删，子笔记会跟着进回收站；此时单独恢复子笔记应挂回根目录
    assert.equal((await call(`/api/nodes/${folderId}`, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call(`/api/nodes/${docId}`)).status, 404, '父目录进回收站时子笔记一并隐藏')
    trash = await call('/api/trash', 'GET', undefined, state.owner)
    assert.equal(trash.data.nodes.length, 1, '父子都被删时只列顶层')
    assert.equal(trash.data.total, 2)
    const orphan = await call(`/api/trash/${docId}/restore`, 'POST', undefined, state.owner)
    assert.equal(orphan.status, 200)
    assert.equal(orphan.data.node.parent_id, 0, '父目录还在回收站时应挂回根目录')

    // 彻底删除
    await call(`/api/nodes/${docId}`, 'DELETE', undefined, state.owner)
    assert.equal((await call(`/api/trash/${docId}`, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call(`/api/trash/${docId}/restore`, 'POST', undefined, state.owner)).status, 404)
    assert.equal((await call(`/api/nodes/${docId}`, 'GET', undefined, state.owner)).status, 404)

    // 清空回收站
    assert.equal((await call('/api/trash', 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call('/api/trash', 'GET', undefined, state.owner)).data.total, 0)
    assert.equal((await call(`/api/projects/${pid}`, 'DELETE', undefined, state.owner)).status, 200)
  })

  await t.test('孤儿附件清理脚本', async () => {
    // 上传两张图，只让其中一张被笔记引用
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
    const used = await call('/api/uploads', 'POST', { fileName: 'used.png', mimeType: 'image/png', data: png }, state.owner)
    const orphan = await call('/api/uploads', 'POST', { fileName: 'orphan.png', mimeType: 'image/png', data: png }, state.owner)
    assert.equal(used.status, 201)
    assert.equal(orphan.status, 201)

    const note = await call('/api/nodes', 'POST', {
      projectId: state.dailyPid, kind: 'doc', title: '引用附件', content: `![x](${used.data.url})`, status: 'draft',
    }, state.owner)
    assert.equal(note.status, 201)

    const usedFile = path.join(DATA_DIR, 'uploads', String(state.ownerId), path.basename(used.data.url))
    const orphanFile = path.join(DATA_DIR, 'uploads', String(state.ownerId), path.basename(orphan.data.url))
    assert.ok(fs.existsSync(usedFile), '被引用的附件应存在于磁盘')
    assert.ok(fs.existsSync(orphanFile), '未被引用的附件上传后也在磁盘上')

    // 预演模式：只列不删
    const dry = spawnSync(process.execPath, [path.join(ROOT, 'scripts/clean-orphan-uploads.js')], {
      env: { ...process.env, DATA_DIR },
      encoding: 'utf8',
    })
    assert.equal(dry.status, 0, dry.stderr)
    assert.match(dry.stdout, /孤儿附件：1 个/)
    assert.ok(fs.existsSync(orphanFile), '预演不应删除任何文件')

    // --apply 才真删
    const applied = spawnSync(process.execPath, [path.join(ROOT, 'scripts/clean-orphan-uploads.js'), '--apply'], {
      env: { ...process.env, DATA_DIR },
      encoding: 'utf8',
    })
    assert.equal(applied.status, 0, applied.stderr)
    assert.match(applied.stdout, /已删除 1 个孤儿附件/)
    assert.ok(!fs.existsSync(orphanFile), '孤儿附件应被删除')
    assert.ok(fs.existsSync(usedFile), '被引用的附件必须保留')

    await call(`/api/nodes/${note.data.node.id}?purge=1`, 'DELETE', undefined, state.owner)
    await call(`/api/uploads/${used.data.url.split('/api/uploads/')[1]}`, 'DELETE', undefined, state.owner)
  })
})
