import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useTheme } from '../theme'
import { usePageMeta } from '../site'
import MarkdownView from '../components/MarkdownView'
import Icon from '../components/Icon'

function insertAt(text: string, snippet: string, start: number, end: number) {
  const next = `${text.slice(0, start)}${snippet}${text.slice(end)}`
  return { next, caret: start + snippet.length }
}

export default function Editor() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { resolved } = useTheme()
  const nodeId = Number(searchParams.get('nodeId') || 0)
  const projectId = Number(searchParams.get('projectId') || 0)
  const parentId = Number(searchParams.get('parentId') || 0)
  const dailyDate = searchParams.get('dailyDate') || ''

  const [kind, setKind] = useState<'folder' | 'doc'>(searchParams.get('kind') === 'folder' ? 'folder' : 'doc')
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [content, setContent] = useState('')
  const [tags, setTags] = useState('')
  const [sortOrder, setSortOrder] = useState(0)
  const [status, setStatus] = useState<'draft' | 'published'>('published')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [projectNodes, setProjectNodes] = useState<any[]>([])
  const [nodeProjectId, setNodeProjectId] = useState(0)
  const [parent, setParent] = useState(parentId)
  const [loadingNode, setLoadingNode] = useState(Boolean(nodeId))
  // 窄屏没有并排的空间，默认只显示编辑区；想对照可以手动切到「并排预览」
  const [mode, setMode] = useState<'write' | 'split'>(
    () => (typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches ? 'write' : 'split'),
  )
  const [dirty, setDirty] = useState(false)
  const [autosavedAt, setAutosavedAt] = useState('')
  const [restorable, setRestorable] = useState<{ title: string; content: string; tags: string; at: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const mdRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const pid = projectId || nodeProjectId
  const draftKey = `notes_draft_${nodeId || `new-${projectId || 0}-${parentId}`}`

  usePageMeta(nodeId ? '编辑内容' : '新建笔记')

  useEffect(() => {
    if (!pid) return
    api.getProject(pid).then((res) => setProjectNodes(res.nodes)).catch(() => {})
  }, [pid])

  const folderOptions = useMemo(() => {
    const result: { id: number; label: string }[] = []
    const walk = (parentValue: number, depth: number) => {
      projectNodes
        .filter((n) => n.kind === 'folder' && n.parent_id === parentValue && n.id !== nodeId)
        .forEach((n) => {
          result.push({ id: n.id, label: `${'　'.repeat(depth)}${n.title}` })
          walk(n.id, depth + 1)
        })
    }
    walk(0, 0)
    return result
  }, [projectNodes, nodeId])

  // 本地草稿：写到 localStorage，刷新或断网都不至于丢内容
  const readDraft = useCallback(() => {
    try {
      const raw = localStorage.getItem(draftKey)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }, [draftKey])

  useEffect(() => {
    if (!nodeId) {
      // 新建笔记：如果上次有没保存的草稿，提示恢复
      const draft = readDraft()
      if (draft && (draft.content || draft.title)) {
        setRestorable({
          title: draft.title || '',
          content: draft.content || '',
          tags: draft.tags || '',
          at: draft.at || '',
        })
      }
      return
    }
    setLoadingNode(true)
    api.getNode(nodeId)
      .then(({ node }) => {
        setTitle(node.title)
        setSlug(node.slug)
        setContent(node.content)
        setTags(node.tags)
        setSortOrder(node.sort_order)
        setStatus(node.status)
        setKind(node.kind)
        setNodeProjectId(node.project_id)
        setParent(node.parent_id)
        setDirty(false)
        // 服务器内容比本地草稿新时丢弃草稿，否则提示恢复
        const draft = readDraft()
        if (draft && draft.at && (draft.content || '') !== node.content) {
          setRestorable({
            title: draft.title || '',
            content: draft.content || '',
            tags: draft.tags || '',
            at: draft.at || '',
          })
        } else if (draft) {
          localStorage.removeItem(draftKey)
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingNode(false))
  }, [nodeId, readDraft, draftKey])

  // 有改动后每 3 秒把草稿存到本地，不打扰服务器
  useEffect(() => {
    if (!dirty) return
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(draftKey, JSON.stringify({
          title, content, tags, at: new Date().toISOString(),
        }))
        setAutosavedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
      } catch {
        // 配额满了就放弃本地草稿，不影响正常保存
      }
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [dirty, title, content, tags, draftKey])

  // 离开页面时提醒，浏览器刷新/关标签页也拦一道
  useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const applyDraft = () => {
    if (!restorable) return
    if (restorable.title) setTitle(restorable.title)
    setContent(restorable.content)
    if (restorable.tags) setTags(restorable.tags)
    setDirty(true)
    setRestorable(null)
  }

  const discardDraft = () => {
    localStorage.removeItem(draftKey)
    setRestorable(null)
  }

  const uploadAttachment = async (file: File) => {
    if (file.size > 10 * 1024 * 1024) { setError('附件不能超过 10MB'); return }
    setUploading(true)
    setError('')
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
        reader.onerror = () => reject(new Error('读取文件失败'))
        reader.readAsDataURL(file)
      })
      const res = await api.upload(file.name, file.type, base64)
      const isPdf = file.type === 'application/pdf'
      setContent((prev) => `${prev}\n${isPdf ? `[${file.name}](${res.url})` : `![${file.name}](${res.url})`}\n`)
      setDirty(true)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  // 直接粘贴截图就上传，省掉「先存文件再选文件」这一步
  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(event.clipboardData?.items || [])
    const image = items.find((item) => item.type.startsWith('image/'))
    if (!image) return
    const file = image.getAsFile()
    if (!file) return
    event.preventDefault()
    uploadAttachment(file)
  }

  // 把一个 .md 文件的内容读进编辑器，等于「上传 md 后继续在线编辑」
  const loadMarkdownFile = async (file: File) => {
    if (file.size > 2 * 1024 * 1024) { setError('单个 Markdown 文件不能超过 2MB'); return }
    if (dirty && !window.confirm('当前有未保存的修改，导入会覆盖正文，确定继续吗？')) return
    try {
      const text = await file.text()
      setContent(text)
      if (!title.trim()) {
        const heading = text.split('\n').map((line) => line.trim()).find((line) => /^#\s+/.test(line))
        const fallback = file.name.replace(/\.(md|markdown|mdx|txt)$/i, '')
        setTitle((heading ? heading.replace(/^#\s+/, '') : fallback).slice(0, 120))
      }
      setDirty(true)
      setError('')
    } catch {
      setError('读取文件失败')
    }
  }

  const wrapSelection = (before: string, after = '') => {
    const area = textareaRef.current
    if (!area) return
    const start = area.selectionStart
    const end = area.selectionEnd
    const chosen = content.slice(start, end)
    const { next, caret } = insertAt(content, `${before}${chosen}${after}`, start, end)
    setContent(next)
    setDirty(true)
    window.setTimeout(() => {
      area.focus()
      area.setSelectionRange(caret - after.length, caret - after.length)
    }, 0)
  }

  const save = async () => {
    if (!title.trim()) { setError('标题不能为空'); return }
    if (!nodeId && !projectId) { setError('缺少项目信息'); return }
    if (saving) return
    setSaving(true)
    setError('')
    try {
      const payload: Record<string, unknown> = { title, slug, content, tags, sortOrder, status, parentId: parent }
      if (!nodeId && dailyDate) payload.dailyDate = dailyDate
      const res = nodeId
        ? await api.updateNode(nodeId, payload)
        : await api.createNode({ projectId, kind, ...payload })
      setDirty(false)
      localStorage.removeItem(draftKey)
      navigate(`/p/${res.node.project_id}/n/${res.node.id}`)
    } catch (e: any) {
      setError(e.message)
      setSaving(false)
    }
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const goBack = () => {
    if (dirty && !window.confirm('还有未保存的修改，确定离开吗？')) return
    navigate(-1)
  }

  const heading = nodeId ? '编辑内容' : kind === 'folder' ? '新建文件夹' : '新建笔记'

  return (
    <div className="page editor-page">
      <div className="editor-head">
        <div>
          <Link to={pid ? `/p/${pid}` : '/'} className="back-link"><Icon name="arrow-left" size={13} />返回项目</Link>
          <h1>{heading}</h1>
        </div>
        <div className="head-actions">
          {dirty && (
            <span className="badge badge-draft" title={autosavedAt ? `本地草稿已存于 ${autosavedAt}` : '本地草稿会自动保存'}>
              {autosavedAt ? `未保存 · 草稿 ${autosavedAt}` : '未保存'}
            </span>
          )}
          <button className="btn" onClick={goBack}>取消</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}

      {restorable && (
        <div className="alert alert-info draft-restore">
          <Icon name="clock" size={16} />
          <span>
            发现 {restorable.at ? new Date(restorable.at).toLocaleString('zh-CN') : '上次'} 的本地草稿
            {restorable.title ? `「${restorable.title}」` : ''}，要恢复吗？
          </span>
          <div className="draft-restore-actions">
            <button className="btn btn-sm" onClick={discardDraft}>丢弃</button>
            <button className="btn btn-sm btn-primary" onClick={applyDraft}>恢复草稿</button>
          </div>
        </div>
      )}

      <div className="editor-fields">
        <label className="field">
          <span className="field-label">标题</span>
          <input
            className="input"
            value={title}
            onChange={(e) => { setTitle(e.target.value); setDirty(true) }}
            autoFocus
            placeholder="给这篇起个名字"
          />
        </label>
        <label className="field">
          <span className="field-label">URL 标识</span>
          <input className="input" value={slug} onChange={(e) => { setSlug(e.target.value); setDirty(true) }} placeholder="留空则根据标题生成" />
        </label>
        <label className="field">
          <span className="field-label">标签</span>
          <input className="input" value={tags} onChange={(e) => { setTags(e.target.value); setDirty(true) }} placeholder="用英文逗号分隔，例如：Go, 并发" />
        </label>
        {pid > 0 && (
          <label className="field">
            <span className="field-label">所在目录</span>
            <select className="select" value={parent} onChange={(e) => { setParent(Number(e.target.value)); setDirty(true) }}>
              <option value={0}>根目录</option>
              {folderOptions.map((folder) => (
                <option key={folder.id} value={folder.id}>{folder.label}</option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span className="field-label">排序</span>
          <input className="input" type="number" value={sortOrder} onChange={(e) => { setSortOrder(Number(e.target.value)); setDirty(true) }} />
        </label>
        <label className="field">
          <span className="field-label">状态</span>
          <select className="select" value={status} onChange={(e) => { setStatus(e.target.value as 'draft' | 'published'); setDirty(true) }}>
            <option value="published">已发布，访客可见</option>
            <option value="draft">草稿，只有自己可见</option>
          </select>
        </label>
        {!nodeId && (
          <label className="field">
            <span className="field-label">类型</span>
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value as 'folder' | 'doc')}>
              <option value="doc">笔记</option>
              <option value="folder">文件夹</option>
            </select>
          </label>
        )}
      </div>

      {kind === 'doc' && (
        <div className="editor-markdown" data-color-mode={resolved}>
          <div className="editor-toolbar">
            <div className="edit-tabs">
              <button className={mode === 'write' ? 'on' : ''} onClick={() => setMode('write')}>写</button>
              <button className={mode === 'split' ? 'on' : ''} onClick={() => setMode('split')}>并排预览</button>
            </div>
            <span className="toolbar-sep" />
            <div className="format-buttons">
              <button type="button" className="icon-btn" title="标题" onClick={() => wrapSelection('## ')}>H2</button>
              <button type="button" className="icon-btn" title="加粗" onClick={() => wrapSelection('**', '**')}>B</button>
              <button type="button" className="icon-btn" title="行内代码" onClick={() => wrapSelection('`', '`')}>{'</>'}</button>
              <button type="button" className="icon-btn" title="链接" onClick={() => wrapSelection('[', '](https://)')}>Link</button>
              <button type="button" className="icon-btn" title="引用" onClick={() => wrapSelection('> ')}>Quote</button>
            </div>
            <span className="toolbar-sep" />
            <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
              <Icon name="upload" size={14} />
              {uploading ? '上传中…' : '插图或附件'}
            </button>
            <input
              ref={fileRef}
              type="file"
              hidden
              aria-label="插入图片或附件"
              accept="image/png,image/jpeg,image/gif,image/webp,application/pdf"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) uploadAttachment(file)
                e.target.value = ''
              }}
            />
            <button className="btn btn-sm" onClick={() => mdRef.current?.click()}>
              <Icon name="file" size={14} />导入 md
            </button>
            <input
              ref={mdRef}
              type="file"
              hidden
              aria-label="导入 Markdown 文件"
              accept=".md,.markdown,.mdx,.txt,text/markdown,text/plain"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) loadMarkdownFile(file)
                e.target.value = ''
              }}
            />
            <span className="hint">可直接粘贴截图上传；PNG / JPEG / GIF / WebP / PDF 单个不超过 10MB</span>
          </div>

          <div className={`edit-body mode-${mode}`}>
            {loadingNode ? (
              <div className="loading-line"><span className="spinner" />正在读取内容…</div>
            ) : (
              <>
                <textarea
                  ref={textareaRef}
                  className="edit-textarea"
                  value={content}
                  onChange={(e) => { setContent(e.target.value); setDirty(true) }}
                  onPaste={onPaste}
                  placeholder="直接用 Markdown 写。支持 GFM 表格、任务列表、代码块，截图可以直接粘贴。"
                  spellCheck={false}
                />
                {mode === 'split' && (
                  <div className="edit-preview">
                    <MarkdownView content={content} emptyHint="左侧开始写，这里会实时预览。" />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
