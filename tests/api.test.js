const { test, before, after } = require('node:test')
const assert = require('node:assert/strict')
const { spawn } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')
const os = require('node:os')
const Database = require('better-sqlite3')
const bcrypt = require('bcryptjs')

const PORT = 39001
const DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'notes-api-test-'))
const ROOT = path.join(__dirname, '..')
const base = `http://127.0.0.1:${PORT}`
let server = null

const PNG_1PX = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=='

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
  server = spawn(process.execPath, ['--require', path.join(__dirname, 'mock-ai-fetch.js'), 'server/index.js'], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), DATA_DIR, JWT_SECRET: 'test-only-secret', SITE_OWNER: 'owner', OPENAI_API_KEY: 'unused-env-key' },
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

test('笔记库 API 完整流程', async (t) => {
  const state = {}

  await t.test('账号与鉴权', async () => {
    const defaultLogin = await call('/api/auth/login', 'POST', {
      username: 'coustea', password: 'coustea',
    })
    assert.equal(defaultLogin.status, 200, '内置账号应可登录')
    assert.ok(defaultLogin.data.token)
    assert.equal(defaultLogin.data.user.username, 'coustea')
    state.coustea = defaultLogin.data.token

    const blocked = await call('/api/auth/register', 'POST', {
      username: 'newuser', password: 'pass123',
    })
    assert.equal(blocked.status, 403, '注册接口应关闭')

    const db = new Database(path.join(DATA_DIR, 'notes.db'))
    db.pragma('busy_timeout = 5000')
    const insert = db.prepare('INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)')
    const ownerInfo = insert.run('owner', bcrypt.hashSync('pass123', 10), '站长')
    const otherInfo = insert.run('other', bcrypt.hashSync('pass123', 10), '其他用户')
    db.close()

    const ownerLogin = await call('/api/auth/login', 'POST', { username: 'owner', password: 'pass123' })
    assert.equal(ownerLogin.status, 200)
    state.owner = ownerLogin.data.token
    state.ownerId = Number(ownerInfo.lastInsertRowid)

    const otherLogin = await call('/api/auth/login', 'POST', { username: 'other', password: 'pass123' })
    assert.equal(otherLogin.status, 200)
    state.other = otherLogin.data.token
    state.otherId = Number(otherInfo.lastInsertRowid)

    assert.equal((await call('/api/auth/login', 'POST', { username: 'owner', password: 'wrong' })).status, 401)
    assert.equal((await call('/api/auth/me')).status, 401)
    assert.equal((await call('/api/auth/me', 'GET', undefined, state.owner)).status, 200)

    assert.equal((await call('/api/auth/change-password', 'POST', {
      oldPassword: 'wrong', newPassword: 'newpass123',
    }, state.owner)).status, 400)
    assert.equal((await call('/api/auth/change-password', 'POST', {
      oldPassword: 'pass123', newPassword: 'newpass123',
    }, state.owner)).status, 200)
    assert.equal((await call('/api/auth/login', 'POST', { username: 'owner', password: 'newpass123' })).status, 200)
  })

  await t.test('AI 写作仅 coustea 可用，并使用页面提交的密钥', async () => {
    const input = { model: 'test-model', baseURL: '', mode: 'draft', prompt: '写一段笔记', title: '测试', context: '' }
    assert.equal((await call('/api/ai/markdown', 'POST', input)).status, 401)
    assert.equal((await call('/api/ai/markdown', 'POST', input, state.other)).status, 403)
    assert.equal((await call('/api/ai/markdown', 'POST', { ...input, apiKey: 'submitted-key' }, state.owner)).status, 403,
      '即使 SITE_OWNER 指向其他账号，该账号也不能使用 AI')
    assert.equal((await call('/api/ai/markdown', 'POST', { ...input, model: '' }, state.coustea)).status, 400)
    assert.equal((await call('/api/ai/markdown', 'POST', { ...input, baseURL: 'http://127.0.0.1:3001/v1' }, state.coustea)).status, 400)
    assert.equal((await call('/api/ai/markdown', 'POST', { ...input, baseURL: 'https://127.0.0.1/v1' }, state.coustea)).status, 400)
    assert.equal((await call('/api/ai/markdown', 'POST', { ...input, baseURL: 'https://localhost./v1' }, state.coustea)).status, 400)
    assert.equal((await call('/api/ai/markdown', 'POST', input, state.coustea)).status, 400, '缺少页面提交的 API Key 应被拒绝')
    const generated = await call('/api/ai/markdown', 'POST', {
      ...input, apiKey: 'submitted-key', baseURL: 'https://notes-ai.example.test/v1',
    }, state.coustea)
    assert.equal(generated.status, 200)
    assert.equal(generated.data.markdown, '# 测试笔记')
  })

  await t.test('讯飞星火与 DeepSeek 走 OpenAI 协议均可用', async () => {
    const base = { mode: 'draft', prompt: '写一段笔记', title: '兼容性', context: '' }

    // 讯飞星火：Base URL 按官方文档给的是完整端点（.../v2/chat/completions），
    // 必须被收敛成 /v2 前缀，否则 SDK 会拼出 /chat/completions/chat/completions 的 404。
    const sparkFull = await call('/api/ai/markdown', 'POST', {
      ...base,
      apiKey: 'spark-key',
      model: 'spark-x2.6',
      baseURL: 'https://spark-maas.example.test/v2/chat/completions',
    }, state.coustea)
    assert.equal(sparkFull.status, 200, '完整端点写法应被自动纠正')
    assert.equal(sparkFull.data.markdown, '# 星火笔记')

    // 版本前缀写法同样可用
    const sparkPrefix = await call('/api/ai/markdown', 'POST', {
      ...base,
      apiKey: 'spark-key',
      model: 'spark-x2.6',
      baseURL: 'https://spark-maas.example.test/v2',
    }, state.coustea)
    assert.equal(sparkPrefix.status, 200)
    assert.equal(sparkPrefix.data.markdown, '# 星火笔记')

    // 思考型模型正文为空、只有 reasoning_content 时不能误判成空响应
    const sparkThinking = await call('/api/ai/markdown', 'POST', {
      ...base,
      prompt: '请思考后写一段笔记',
      apiKey: 'spark-key',
      model: 'spark-x2.6',
      baseURL: 'https://spark-maas.example.test/v2',
    }, state.coustea)
    assert.equal(sparkThinking.status, 200)
    assert.equal(sparkThinking.data.markdown, '# 星火推理笔记', '应回退到 reasoning_content')

    // HTTP 200 里的业务错误码必须被识别，不能当成“模型没有返回内容”
    const sparkBizError = await call('/api/ai/markdown', 'POST', {
      ...base,
      apiKey: 'spark-key',
      model: 'spark-x2.6',
      baseURL: 'https://spark-biz-error.example.test/v2',
    }, state.coustea)
    assert.equal(sparkBizError.status, 502)
    assert.match(sparkBizError.data.error, /10013|model not found/, '应透出上游业务错误码与原因')

    // DeepSeek：标准 /v1 前缀
    const deepseek = await call('/api/ai/markdown', 'POST', {
      ...base,
      apiKey: 'deepseek-key',
      model: 'deepseek-chat',
      baseURL: 'https://deepseek.example.test/v1',
    }, state.coustea)
    assert.equal(deepseek.status, 200)
    assert.equal(deepseek.data.markdown, '# DeepSeek 笔记')

    // 鉴权失败时错误信息应带上游原因，便于排查
    const badKey = await call('/api/ai/markdown', 'POST', {
      ...base,
      apiKey: 'wrong-key',
      model: 'deepseek-chat',
      baseURL: 'https://deepseek.example.test/v1',
    }, state.coustea)
    assert.equal(badKey.status, 502)
    assert.match(badKey.data.error, /鉴权失败/)
  })

  await t.test('AI 配置连通性自检', async () => {
    assert.equal((await call('/api/admin/ai-config/test', 'POST', {})).status, 401)
    assert.equal((await call('/api/admin/ai-config/test', 'POST', {}, state.other)).status, 403)

    const ok = await call('/api/admin/ai-config/test', 'POST', {
      apiKey: 'spark-key', model: 'spark-x2.6', baseURL: 'https://spark-maas.example.test/v2/chat/completions',
    }, state.coustea)
    assert.equal(ok.status, 200)
    assert.equal(ok.data.ok, true)
    assert.equal(ok.data.endpoint, 'https://spark-maas.example.test/v2', '自检应回显收敛后的真实端点')

    const bizFail = await call('/api/admin/ai-config/test', 'POST', {
      apiKey: 'spark-key', model: 'spark-x2.6', baseURL: 'https://spark-biz-error.example.test/v2',
    }, state.coustea)
    assert.equal(bizFail.status, 502)
    assert.match(bizFail.data.error, /10013/)

    const authFail = await call('/api/admin/ai-config/test', 'POST', {
      apiKey: 'wrong-key', model: 'spark-x2.6', baseURL: 'https://spark-maas.example.test/v2',
    }, state.coustea)
    assert.equal(authFail.status, 502)
    assert.match(authFail.data.error, /鉴权失败/)

    const badUrl = await call('/api/admin/ai-config/test', 'POST', {
      apiKey: 'spark-key', model: 'spark-x2.6', baseURL: 'http://spark-maas.example.test/v2',
    }, state.coustea)
    assert.equal(badUrl.status, 400)
  })

  await t.test('管理文章接口仅 coustea 可访问', async () => {
    assert.equal((await call('/api/admin/notes')).status, 401)
    assert.equal((await call('/api/admin/notes', 'GET', undefined, state.other)).status, 403)
    assert.equal((await call('/api/admin/notes', 'GET', undefined, state.owner)).status, 403)
    const result = await call('/api/admin/notes', 'GET', undefined, state.coustea)
    assert.equal(result.status, 200)
    assert.ok(Array.isArray(result.data.notes))
  })

  await t.test('项目创建与可见性', async () => {
    assert.equal((await call('/api/projects', 'POST', { name: '未登录项目' })).status, 401)

    let res = await call('/api/projects', 'POST', {
      name: '学习项目', description: '用于测试全文检索', status: 'draft', sort_order: 2,
    }, state.owner)
    assert.equal(res.status, 201)
    state.pid = res.data.project.id
    assert.equal(res.data.project.status, 'draft')

    assert.equal((await call(`/api/projects/${state.pid}`)).status, 404, '草稿项目对访客不可见')
    assert.equal((await call(`/api/projects/${state.pid}`, 'GET', undefined, state.other)).status, 404)

    res = await call(`/api/projects/${state.pid}`, 'PATCH', {
      name: '学习项目（改名）', description: '用于测试全文检索与标签', sort_order: 1,
    }, state.owner)
    assert.equal(res.data.project.name, '学习项目（改名）')
    assert.equal(res.data.project.sort_order, 1)
    assert.equal((await call(`/api/projects/${state.pid}`, 'PATCH', { name: '越权' }, state.other)).status, 403)
  })

  await t.test('目录树与笔记 CRUD', async () => {
    let res = await call('/api/nodes', 'POST', {
      projectId: state.pid, parentId: 0, kind: 'folder', title: '第一章', status: 'published',
    }, state.owner)
    assert.equal(res.status, 201)
    state.folderId = res.data.node.id

    res = await call('/api/nodes', 'POST', {
      projectId: state.pid, parentId: state.folderId, kind: 'folder', title: '小节', status: 'published',
    }, state.owner)
    state.childFolderId = res.data.node.id

    res = await call('/api/nodes', 'POST', {
      projectId: state.pid, parentId: state.childFolderId, kind: 'doc',
      title: 'React 入门', content: '# React 入门\n\n使用 useState 管理组件状态。',
      tags: 'React, 前端', sortOrder: 3, status: 'draft',
    }, state.owner)
    assert.equal(res.status, 201)
    state.docId = res.data.node.id

    assert.equal((await call('/api/nodes', 'POST', {
      projectId: state.pid, parentId: state.docId, kind: 'doc', title: '不能挂在笔记下',
    }, state.owner)).status, 400)

    assert.equal((await call(`/api/nodes/${state.docId}`)).status, 404, '草稿笔记对访客不可见')

    res = await call(`/api/nodes/${state.docId}`, 'PATCH', { content: '# React 入门\n\n使用 useState 与 useEffect 管理状态。', status: 'published' }, state.owner)
    assert.equal(res.status, 200)
    assert.equal((await call(`/api/nodes/${state.docId}`)).status, 404, '草稿项目里的已发布笔记也不能直读')
    assert.equal((await call(`/api/nodes/${state.docId}`, 'GET', undefined, state.owner)).status, 200)

    res = await call(`/api/nodes/${state.docId}`, 'PATCH', { parentId: state.folderId }, state.owner)
    assert.equal(res.status, 200)
    assert.equal(res.data.node.parent_id, state.folderId)

    assert.equal((await call(`/api/nodes/${state.docId}`, 'PATCH', {
      parentId: state.docId,
    }, state.owner)).status, 400)

    res = await call(`/api/nodes/${state.folderId}`, 'PATCH', { parentId: state.childFolderId }, state.owner)
    assert.equal(res.status, 400, '不能把文件夹移动进自己的子目录')

    assert.equal((await call(`/api/nodes/${state.docId}`, 'PATCH', { title: '越权' }, state.other)).status, 403)
    assert.equal((await call(`/api/nodes/${state.docId}`, 'PATCH', { title: '未登录' })).status, 401)
    assert.equal((await call(`/api/nodes/${state.docId}`, 'DELETE', undefined, state.other)).status, 403)
  })

  await t.test('文件树移动与排序', async () => {
    const project = await call('/api/projects', 'POST', { name: '移动测试', status: 'draft' }, state.owner)
    assert.equal(project.status, 201)
    const pid = project.data.project.id
    const create = async (title, kind, parentId = 0) => {
      const result = await call('/api/nodes', 'POST', { projectId: pid, parentId, kind, title, status: 'published' }, state.owner)
      assert.equal(result.status, 201)
      return result.data.node.id
    }
    const folder = await create('目录 A', 'folder')
    const secondFolder = await create('目录 B', 'folder')
    const first = await create('笔记 A', 'doc')
    const second = await create('笔记 B', 'doc')
    const child = await create('子目录', 'folder', folder)
    const move = (id, parentId, beforeId, token = state.owner) =>
      call(`/api/nodes/${id}/move`, 'POST', { parentId, beforeId }, token)

    assert.equal((await move(second, 0, first)).status, 200)
    let tree = (await call(`/api/projects/${pid}`, 'GET', undefined, state.owner)).data.nodes
    assert.deepEqual(tree.filter((node) => node.parent_id === 0).map((node) => node.id), [folder, secondFolder, second, first])

    assert.equal((await move(second, folder, null)).status, 200)
    tree = (await call(`/api/projects/${pid}`, 'GET', undefined, state.owner)).data.nodes
    assert.deepEqual(tree.filter((node) => node.parent_id === folder).map((node) => node.id), [child, second])
    assert.equal((await move(folder, child, null)).status, 400, '不能移进自己的子目录')
    assert.equal((await move(first, folder, secondFolder)).status, 400, '锚点必须在目标目录中')
    assert.equal((await move(first, folder, null, state.other)).status, 403)
    assert.equal((await move(first, folder, null, null)).status, 401)
  })

  await t.test('项目发布与公开读取', async () => {
    assert.equal((await call(`/api/projects/${state.pid}`)).status, 404, '项目未发布时整体不可见')
    const res = await call(`/api/projects/${state.pid}`, 'PATCH', { status: 'published' }, state.owner)
    assert.equal(res.status, 200)
    assert.equal((await call(`/api/nodes/${state.docId}`)).status, 200)

    const draft = await call('/api/nodes', 'POST', {
      projectId: state.pid, kind: 'doc', title: '暂不公开', status: 'draft',
    }, state.owner)
    assert.equal(draft.status, 201)
    await call(`/api/projects/${state.pid}`, 'PATCH', { status: 'draft' }, state.owner)
    await call(`/api/projects/${state.pid}`, 'PATCH', { status: 'published' }, state.owner)
    assert.equal((await call(`/api/nodes/${draft.data.node.id}`)).status, 404, '重新发布项目不能发布笔记草稿')

    const hiddenFolder = await call('/api/nodes', 'POST', {
      projectId: state.pid, kind: 'folder', title: '隐藏目录', status: 'draft',
    }, state.owner)
    const hiddenChild = await call('/api/nodes', 'POST', {
      projectId: state.pid, parentId: hiddenFolder.data.node.id,
      kind: 'doc', title: '隐藏目录中的公开笔记', content: '秘密目录检索词',
      tags: '秘密目录标签', status: 'published',
    }, state.owner)
    assert.equal((await call(`/api/nodes/${hiddenChild.data.node.id}`)).status, 404)
    assert.equal((await call('/api/search?q=秘密目录检索词')).data.notes.length, 0)
    assert.equal((await call('/api/recent')).data.notes.some((n) => n.id === hiddenChild.data.node.id), false)
    assert.equal((await call('/api/tags')).data.tags.some((tag) => tag.tag === '秘密目录标签'), false)
    assert.equal((await call('/api/overview')).data.recent.some((n) => n.id === hiddenChild.data.node.id), false)
    assert.equal((await fetch(`${base}/rss.xml`).then((res) => res.text())).includes('隐藏目录中的公开笔记'), false)
    assert.equal((await fetch(`${base}/sitemap.xml`).then((res) => res.text())).includes(`/n/${hiddenChild.data.node.id}`), false)

    const detail = await call(`/api/projects/${state.pid}`)
    assert.equal(detail.status, 200)
    assert.equal(detail.data.nodes.length, 3)
    assert.ok(detail.data.nodes.some((n) => n.title === 'React 入门'))

    const list = await call('/api/projects')
    assert.ok(list.data.projects.some((p) => p.id === state.pid))
    const listed = list.data.projects.find((p) => p.id === state.pid)
    assert.equal(listed.doc_count, 1)
    assert.ok(Array.isArray(listed.tags) && listed.tags.includes('React'), '项目列表应聚合标签')
  })

  await t.test('历史版本仅作者可读，恢复时保留当前版本', async () => {
    const url = `/api/nodes/${state.docId}/revisions`
    assert.equal((await call(url)).status, 401)
    assert.equal((await call(url, 'GET', undefined, state.other)).status, 403)
    let history = await call(url, 'GET', undefined, state.owner)
    assert.equal(history.data.revisions.length, 1)
    const firstId = history.data.revisions[0].id
    const first = await call(`${url}/${firstId}`, 'GET', undefined, state.owner)
    assert.match(first.data.revision.content, /使用 useState 管理组件状态/)
    assert.equal((await call(`${url}/${firstId}`, 'GET', undefined, state.other)).status, 403)

    await call(`/api/nodes/${state.docId}`, 'PATCH', { status: 'draft' }, state.owner)
    history = await call(url, 'GET', undefined, state.owner)
    assert.equal(history.data.revisions.length, 1, '只切换发布状态不生成正文版本')
    await call(`/api/nodes/${state.docId}`, 'PATCH', {
      content: first.data.revision.content, status: 'published',
    }, state.owner)
    history = await call(url, 'GET', undefined, state.owner)
    assert.equal(history.data.revisions.length, 2, '恢复旧内容时当前内容也应进入历史')
    const current = await call(`/api/nodes/${state.docId}`, 'GET', undefined, state.owner)
    assert.equal(current.data.node.content, first.data.revision.content)
    assert.equal((await call(`${url}/999999`, 'GET', undefined, state.owner)).status, 404)
  })

  await t.test('Markdown 导入与 frontmatter', async () => {
    const res = await call('/api/import', 'POST', {
      projectId: state.pid, parentId: 0, status: 'published',
      files: [
        {
          name: 'useState.md',
          path: '02 进阶/Hooks/useState.md',
          content: '---\ntitle: useState 深入\norder: 7\ntags: [React, Hooks]\n---\n\n# useState\n\n状态管理关键词：渲染优化。',
        },
        {
          name: 'notes.md',
          path: '02 进阶/notes.md',
          content: '# 普通笔记\n\n没有 frontmatter 的文件。',
        },
      ],
    }, state.owner)
    assert.equal(res.status, 200)
    assert.equal(res.data.imported, 2)

    const detail = await call(`/api/projects/${state.pid}`)
    const titles = detail.data.nodes.map((n) => n.title)
    for (const title of ['02 进阶', 'Hooks', 'useState 深入', '普通笔记']) {
      assert.ok(titles.includes(title), `缺少节点 ${title}`)
    }
    const doc = detail.data.nodes.find((n) => n.title === 'useState 深入')
    assert.equal(doc.sort_order, 7)
    assert.equal(doc.tags, 'React,Hooks')
    assert.ok(doc.content.includes('# useState'))

    const again = await call('/api/import', 'POST', {
      projectId: state.pid, parentId: 0, status: 'published',
      files: [{ name: 'useState.md', path: '02 进阶/Hooks/useState.md', content: '# 已修改源文件' }],
    }, state.owner)
    assert.equal(again.data.imported, 0)
    assert.equal(again.data.duplicates, 1)
    const afterImport = await call(`/api/projects/${state.pid}`)
    assert.equal(afterImport.data.nodes.filter((n) => n.kind === 'doc').length,
      detail.data.nodes.filter((n) => n.kind === 'doc').length)
    assert.equal(afterImport.data.nodes.find((n) => n.id === doc.id).content, doc.content, '重复导入不能覆盖笔记')

    assert.equal((await call('/api/import', 'POST', { projectId: state.pid, files: [] }, state.owner)).status, 400)
    assert.equal((await call('/api/import', 'POST', {
      projectId: state.pid, parentId: state.docId,
      files: [{ name: 'wrong.md', content: '# wrong' }],
    }, state.owner)).status, 400)
    assert.equal((await call('/api/import', 'POST', { projectId: state.pid, files: [{ name: 'a.md', content: 'x' }] })).status, 401)
  })

  await t.test('导入顺序：同目录连续编号，增量导入追加在已有内容之后', async () => {
    const proj = await call('/api/projects', 'POST', { name: '导入顺序测试' }, state.owner)
    const pid = proj.data.project.id

    const first = await call('/api/import', 'POST', {
      projectId: pid, parentId: 0, status: 'published',
      files: [
        { name: 'a.md', path: '01 基础/01-概述.md', content: '# 概述' },
        { name: 'b.md', path: '01 基础/02-变量.md', content: '# 变量' },
      ],
    }, state.owner)
    assert.equal(first.status, 200)
    assert.equal(first.data.imported, 2)

    const second = await call('/api/import', 'POST', {
      projectId: pid, parentId: 0, status: 'published',
      files: [
        { name: 'c.md', path: '02 进阶/01-循环.md', content: '# 循环' },
        { name: 'd.md', path: '01 基础/03-补充.md', content: '# 补充' },
      ],
    }, state.owner)
    assert.equal(second.status, 200)
    assert.equal(second.data.imported, 2)

    const detail = await call(`/api/projects/${pid}`, 'GET', undefined, state.owner)
    const rootTitles = detail.data.nodes.filter((n) => n.parent_id === 0).map((n) => n.title)
    assert.deepEqual(rootTitles, ['01 基础', '02 进阶'], '文件夹按导入先后排列')
    const folderId = detail.data.nodes.find((n) => n.title === '01 基础').id
    const inFolder = detail.data.nodes.filter((n) => n.parent_id === folderId).map((n) => n.title)
    assert.deepEqual(inFolder, ['概述', '变量', '补充'], '增量导入应追加在已有笔记之后，而不是插到最前')

    await call(`/api/projects/${pid}`, 'DELETE', undefined, state.owner)
  })

  await t.test('全文搜索 / 标签 / 最近更新', async () => {
    let res = await call('/api/search?q=useState')
    assert.equal(res.status, 200)
    assert.ok(res.data.notes.some((n) => n.title === 'useState 深入'))
    assert.ok(res.data.notes.some((n) => n.excerpt.includes('useState')))

    res = await call('/api/search?q=Hooks')
    assert.ok(res.data.notes.length >= 1, '标签搜索应命中')

    res = await call('/api/search?q=渲染优化')
    assert.equal(res.data.notes.length, 1, '正文搜索应命中唯一笔记')

    res = await call('/api/search?q=学习项目')
    assert.equal(res.data.projects.length, 1)

    res = await call('/api/search?q=')
    assert.equal(res.data.notes.length, 0)

    // 摘要要剥掉 Markdown 记号，否则列表里会出现「## 标题 **粗体** `code`」
    // 这种原始语法，读者看到的是源码而不是句子
    const withMarkdown = await call('/api/nodes', 'POST', {
      projectId: state.pid,
      kind: 'doc',
      title: '摘要清理验证',
      content: '## 二级标题\n\n**加粗内容**与 `行内代码`，还有 [一个链接](https://example.com)。\n\n```js\nconst hidden = 1\n```\n',
      status: 'published',
    }, state.owner)
    assert.equal(withMarkdown.status, 201)
    const cleaned = await call('/api/search?q=加粗内容')
    const hit = cleaned.data.notes.find((n) => n.id === withMarkdown.data.node.id)
    assert.ok(hit, '应能搜到刚建的笔记')
    assert.ok(!hit.excerpt.includes('**'), `摘要不应含粗体记号：${hit.excerpt}`)
    assert.ok(!hit.excerpt.includes('`'), `摘要不应含行内代码记号：${hit.excerpt}`)
    assert.ok(!hit.excerpt.includes('##'), `摘要不应含标题记号：${hit.excerpt}`)
    assert.ok(!hit.excerpt.includes('const hidden'), '摘要不应含代码块内容')
    assert.ok(hit.excerpt.includes('加粗内容'), '摘要应保留正文文字')
    assert.ok(hit.excerpt.includes('一个链接'), '链接应只留文字')
    await call(`/api/nodes/${withMarkdown.data.node.id}?purge=1`, 'DELETE', undefined, state.owner)

    // 多关键词按 AND 处理：每个词都要命中，否则「go 并发」这种组合
    // 会被当成一整串子串去匹配，几乎搜不到东西
    const multi = await call('/api/search?q=' + encodeURIComponent('useState Hooks'))
    assert.equal(multi.status, 200)
    assert.deepEqual(multi.data.terms, ['useState', 'Hooks'], '应把查询切成两个词')
    assert.ok(multi.data.notes.length >= 1, '两个词都在的笔记应命中')
    assert.ok(
      multi.data.notes.every((n) => /useState/i.test(n.title + n.content + n.tags)),
      '结果必须含第一个词',
    )
    // 一个必然不存在的词参与时，结果应为空（AND 语义）
    const none = await call('/api/search?q=' + encodeURIComponent('useState 绝不存在的词xyz'))
    assert.equal(none.data.notes.length, 0, 'AND 语义下不该有结果')
    // 空白分隔的多个词数不应超过上限 5 个
    const capped = await call('/api/search?q=' + encodeURIComponent('a b c d e f g h'))
    assert.ok(capped.data.terms.length <= 5, '关键词最多取 5 个')

    res = await call('/api/tags')
    const react = res.data.tags.find((t) => t.tag === 'React')
    assert.ok(react && react.count >= 2)

    res = await call('/api/recent?limit=1')
    assert.equal(res.data.notes.length, 1)
  })

  await t.test('附件上传与访问控制', async () => {
    let res = await call('/api/uploads', 'POST', {
      fileName: 'bad.svg', mimeType: 'image/svg+xml', data: PNG_1PX,
    }, state.owner)
    assert.equal(res.status, 400, '不支持的类型应被拒绝')

    res = await call('/api/uploads', 'POST', {
      fileName: 'pixel.png', mimeType: 'image/png', data: PNG_1PX,
    }, state.owner)
    assert.equal(res.status, 201)
    const url = res.data.url
    state.uploadUrl = url

    const file = await fetch(base + url)
    assert.equal(file.status, 200)
    assert.match(file.headers.get('content-type'), /image\/png/)

    assert.equal((await call(url, 'DELETE', undefined, state.other)).status, 403)
    assert.equal((await call(`/api/uploads/${state.ownerId}/..%2Fnotes.db`, 'DELETE', undefined, state.owner)).status, 400)

    assert.equal((await call(url, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await fetch(base + url)).status, 404)
  })

  await t.test('删除与数据回收', async () => {
    assert.equal((await call(`/api/nodes/${state.docId}`, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call(`/api/nodes/${state.docId}`)).status, 404)

    assert.equal((await call(`/api/projects/${state.pid}`, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call(`/api/projects/${state.pid}`)).status, 404)
    const list = await call('/api/projects')
    assert.equal(list.data.projects.length, 0)
  })

  await t.test('仅站点所有者可创建项目与导入', async () => {
    const created = await call('/api/projects', 'POST', { name: '他人项目' }, state.other)
    assert.equal(created.status, 403, '非站点所有者不能创建项目')

    const imported = await call('/api/import', 'POST', {
      projectId: 1,
      files: [{ name: 'a.md', content: '# a' }],
    }, state.other)
    assert.equal(imported.status, 403, '非站点所有者不能导入内容')

    const folder = await call('/api/projects/from-folder', 'POST', {
      name: '他人文件夹项目',
      files: [{ name: 'a.md', path: 'a.md', content: '# a' }],
    }, state.other)
    assert.equal(folder.status, 403, '非站点所有者不能用文件夹建项目')

    assert.equal((await call('/api/projects/from-folder', 'POST', { files: [] })).status, 401)
  })

  await t.test('上传文件夹创建项目', async () => {
    const res = await call('/api/projects/from-folder', 'POST', {
      name: 'Go 教程',
      description: '按目录导入',
      files: [
        { name: 'a.md', path: 'golang/01 入门/hello.md', content: '# 第一个程序\n\n内容' },
        { name: 'b.md', path: 'golang/01 入门/变量.md', content: '---\ntitle: 变量与常量\ntags: [Go]\n---\n\n正文' },
        { name: 'c.md', path: 'golang/02 控制流/循环.md', content: '# 循环\n\nfor 语句' },
        { name: 'logo.png', path: 'golang/assets/logo.png', content: 'binary' },
      ],
    }, state.owner)
    assert.equal(res.status, 201)
    assert.equal(res.data.imported, 3, '应导入 3 篇 Markdown')
    assert.equal(res.data.skipped, 1, '应跳过非 Markdown 文件')
    state.folderPid = res.data.project.id
    assert.equal(res.data.project.name, 'Go 教程')

    const detail = await call(`/api/projects/${state.folderPid}`)
    const folders = detail.data.nodes.filter((n) => n.kind === 'folder').map((n) => n.title).sort()
    assert.deepEqual(folders, ['01 入门', '02 控制流'], '应按路径重建一级目录')
    assert.equal(detail.data.project.doc_count, 3)
    assert.equal(detail.data.project.folder_count, 2)

    const list = await call('/api/projects')
    const listed = list.data.projects.find((p) => p.id === state.folderPid)
    assert.equal(listed.doc_count, 3, '项目篇数应为项目内文档数')
    assert.equal(listed.folder_count, 2, '项目目录数应为项目内文件夹数')

    // 第二个项目只有 1 篇，验证计数按项目独立统计
    const single = await call('/api/projects', 'POST', { name: '单篇项目', status: 'published' }, state.owner)
    state.singlePid = single.data.project.id
    await call('/api/nodes', 'POST', {
      projectId: state.singlePid, parentId: 0, kind: 'doc', title: '唯一一篇', content: '# 唯一', status: 'published',
    }, state.owner)

    const list2 = await call('/api/projects')
    const go = list2.data.projects.find((p) => p.id === state.folderPid)
    const one = list2.data.projects.find((p) => p.id === state.singlePid)
    assert.equal(go.doc_count, 3)
    assert.equal(one.doc_count, 1)
    assert.equal(one.folder_count, 0)
  })

  await t.test('站点信息 / RSS / sitemap', async () => {
    const site = await call('/api/site')
    assert.equal(site.status, 200)
    assert.ok(site.data.site.noteCount >= 4, '站点统计应包含公开笔记')

    const rss = await fetch(`${base}/rss.xml`)
    assert.equal(rss.status, 200)
    assert.match(rss.headers.get('content-type'), /rss\+xml|xml/)
    const rssBody = await rss.text()
    assert.ok(rssBody.includes('<rss'), 'RSS 应为合法结构')
    assert.ok(rssBody.includes('循环'), 'RSS 应包含最新笔记')

    const sitemap = await fetch(`${base}/sitemap.xml`)
    assert.equal(sitemap.status, 200)
    const sitemapBody = await sitemap.text()
    assert.ok(sitemapBody.includes(`/p/${state.folderPid}`), '站点地图应包含项目页')
    assert.ok(sitemapBody.includes(`/p/${state.folderPid}/n/`), '站点地图应包含笔记页')

    assert.equal((await call(`/api/projects/${state.folderPid}`, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call(`/api/projects/${state.singlePid}`, 'DELETE', undefined, state.owner)).status, 200)
  })

  await t.test('健康检查与首页聚合接口', async () => {
    const health = await fetch(`${base}/api/healthz`)
    assert.equal(health.status, 200)
    const healthBody = await health.json()
    assert.equal(healthBody.ok, true, '健康检查应返回 ok')
    assert.equal(typeof healthBody.uptime, 'number')

    const ownerProject = await call('/api/projects', 'POST', {
      name: '聚合接口项目', description: '用于校验 overview', status: 'published',
    }, state.owner)
    assert.equal(ownerProject.status, 201)
    const pid = ownerProject.data.project.id
    await call('/api/nodes', 'POST', {
      projectId: pid, parentId: 0, kind: 'doc', title: '聚合笔记',
      content: '# 聚合\n\n正文', tags: '聚合, 测试', status: 'published',
    }, state.owner)

    const overview = await call('/api/overview')
    assert.equal(overview.status, 200)
    assert.ok(overview.data.site && typeof overview.data.site.name === 'string')
    assert.ok(Array.isArray(overview.data.projects))
    assert.ok(Array.isArray(overview.data.recent))
    assert.ok(Array.isArray(overview.data.tags))
    assert.ok(overview.data.projects.some((p) => p.id === pid), 'overview 应包含公开项目')
    const recentTitles = overview.data.recent.map((n) => n.title)
    assert.ok(recentTitles.includes('聚合笔记'), 'overview 应包含最新笔记')
    const tagNames = overview.data.tags.map((t) => t.tag)
    assert.ok(tagNames.includes('聚合'), 'overview 应聚合标签')
    assert.equal(overview.data.site.noteCount >= 1, true)
    // 草稿项目不应出现在访客的 overview 里
    const draftProject = await call('/api/projects', 'POST', {
      name: '草稿聚合项目', status: 'draft',
    }, state.owner)
    const guestOverview = await call('/api/overview')
    assert.equal(
      guestOverview.data.projects.some((p) => p.id === draftProject.data.project.id),
      false,
      '访客不应看到草稿项目',
    )
    const ownerOverview = await call('/api/overview', 'GET', undefined, state.owner)
    assert.equal(ownerOverview.data.projects.some((p) => p.id === draftProject.data.project.id), true)
    const publicOverview = await call('/api/overview?public=1', 'GET', undefined, state.owner)
    assert.equal(publicOverview.data.projects.some((p) => p.id === draftProject.data.project.id), false,
      '已登录账号打开阅读首页也不能看到草稿项目')
    assert.equal((await call(`/api/projects/${pid}`, 'DELETE', undefined, state.owner)).status, 200)
    assert.equal((await call(`/api/projects/${draftProject.data.project.id}`, 'DELETE', undefined, state.owner)).status, 200)
  })

  await t.test('系统 AI 模型配置持久化、批量文章管理与公开视图隔离', async () => {
    // 1. 系统 AI 模型配置仅 coustea 可读写，且不回显明文 Key
    assert.equal((await call('/api/admin/ai-config')).status, 401)
    assert.equal((await call('/api/admin/ai-config', 'GET', undefined, state.owner)).status, 403)
    const initialCfg = await call('/api/admin/ai-config', 'GET', undefined, state.coustea)
    assert.equal(initialCfg.status, 200)
    assert.equal(initialCfg.data.config.hasApiKey, false)

    const badUrl = await call('/api/admin/ai-config', 'PUT', {
      apiKey: 'sk-test-secret-1234', model: 'gpt-4o-mini', baseURL: 'http://127.0.0.1/v1',
    }, state.coustea)
    assert.equal(badUrl.status, 400)

    const saved = await call('/api/admin/ai-config', 'PUT', {
      apiKey: 'submitted-key', model: 'test-model', baseURL: 'https://notes-ai.example.test/v1',
    }, state.coustea)
    assert.equal(saved.status, 200)
    assert.equal(saved.data.config.hasApiKey, true)
    assert.equal(saved.data.config.model, 'test-model')
    assert.equal(saved.data.config.apiKey, undefined, '不能回显明文 API Key')

    // 保存系统模型后，调用 /api/ai/markdown 不再需要每次重复传 apiKey/model/baseURL
    const viaSaved = await call('/api/ai/markdown', 'POST', {
      mode: 'draft', prompt: '写一段笔记', title: '系统模型测试', context: '',
    }, state.coustea)
    assert.equal(viaSaved.status, 200)
    assert.equal(viaSaved.data.markdown, '# 测试笔记')

    // 2. 批量文章管理与 ?public=1 公开视图隔离
    const db = new Database(path.join(DATA_DIR, 'notes.db'))
    const cousteaId = db.prepare("SELECT id FROM users WHERE username = 'coustea'").get().id
    const projId = Number(db.prepare(
      "INSERT INTO projects (owner_id, name, slug, description, status) VALUES (?, '后台测试专题', 'admin-batch-proj', 'desc', 'published')",
    ).run(cousteaId).lastInsertRowid)
    const n1 = Number(db.prepare(
      "INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, content, status) VALUES (?, ?, 0, 'doc', '草稿A', 'draft-a', '正文内容', 'draft')",
    ).run(cousteaId, projId).lastInsertRowid)
    const n2 = Number(db.prepare(
      "INSERT INTO nodes (owner_id, project_id, parent_id, kind, title, slug, content, status) VALUES (?, ?, 0, 'doc', '公开B', 'pub-b', '公开正文', 'published')",
    ).run(cousteaId, projId).lastInsertRowid)
    db.close()

    // 即使携带 coustea token，?public=1 也只返回已发布内容
    const pubProj = await call(`/api/projects/${projId}?public=1`, 'GET', undefined, state.coustea)
    assert.equal(pubProj.status, 200)
    assert.equal(pubProj.data.nodes.some((n) => n.id === n1), false, 'public=1 不应包含草稿')
    assert.equal(pubProj.data.nodes.some((n) => n.id === n2), true)

    // 批量发布仅 coustea 可调用
    assert.equal((await call('/api/admin/notes/batch', 'POST', { ids: [n1], action: 'publish' }, state.owner)).status, 403)
    const batchPub = await call('/api/admin/notes/batch', 'POST', { ids: [n1], action: 'publish' }, state.coustea)
    assert.equal(batchPub.status, 200)
    assert.equal(batchPub.data.affected, 1)

    const pubProjAfter = await call(`/api/projects/${projId}?public=1`, 'GET', undefined, state.coustea)
    assert.equal(pubProjAfter.data.nodes.some((n) => n.id === n1), true, '批量发布后 public=1 应可见')

    const batchTrash = await call('/api/admin/notes/batch', 'POST', { ids: [n1, n2], action: 'trash' }, state.coustea)
    assert.equal(batchTrash.status, 200)
    assert.equal(batchTrash.data.affected, 2)
  })

  await t.test('安全响应头、robots 与 404 处理', async () => {
    const home = await fetch(`${base}/`)
    assert.equal(home.status, 200)
    assert.match(home.headers.get('content-type'), /text\/html/)
    assert.ok(home.headers.get('content-security-policy'), '应下发 CSP')
    assert.equal(home.headers.get('x-content-type-options'), 'nosniff')
    assert.ok(home.headers.get('referrer-policy'), '应下发 Referrer-Policy')
    assert.equal(home.headers.get('x-powered-by'), null, '不应暴露 Express 标识')

    const robots = await fetch(`${base}/robots.txt`)
    assert.equal(robots.status, 200)
    const robotsBody = await robots.text()
    assert.match(robotsBody, /Sitemap:/)
    assert.match(robotsBody, /Disallow: \/api\//)

    const missingApi = await call('/api/不存在')
    assert.equal(missingApi.status, 404)
    assert.ok(missingApi.data.error, '接口 404 应返回 JSON')

    // SPA 回退：未知前端路由返回 index.html，而不是 JSON
    const spaFallback = await fetch(`${base}/some/deep/link`)
    assert.equal(spaFallback.status, 200)
    assert.match(spaFallback.headers.get('content-type'), /text\/html/)

    // 静态资源带长期缓存头
    const assets = await fetch(`${base}/`)
    const html = await assets.text()
    const assetPath = /\/assets\/[^"']+\.js/.exec(html)
    if (assetPath) {
      const asset = await fetch(base + assetPath[0])
      assert.equal(asset.status, 200)
      assert.match(asset.headers.get('cache-control'), /immutable/)
    }

    // 不存在的静态资源必须真的 404：回退成 index.html 会让浏览器拿到
    // 200 + text/html，报的是 MIME 类型错误，很难看出是文件没了
    const missingAsset = await fetch(`${base}/assets/nope-not-here.js`)
    assert.equal(missingAsset.status, 404)
    assert.match(missingAsset.headers.get('content-type'), /text\/plain/)
    const missingIcon = await fetch(`${base}/nope.svg`)
    assert.equal(missingIcon.status, 404)

    // 请求体本身有问题时不能回 500：body-parser 的错误如果不单独处理，
    // 用户只看到「服务器内部错误」，5xx 监控也会被这些客户端问题污染
    const badJson = await fetch(`${base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{bad json',
    })
    assert.equal(badJson.status, 400)
    assert.match((await badJson.json()).error, /JSON/)

    // 超过 24mb 的正文应回 413，而不是 500
    const tooLarge = await fetch(`${base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pad: 'x'.repeat(25 * 1024 * 1024) }),
    })
    assert.equal(tooLarge.status, 413)
  })
})
