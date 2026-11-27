import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { useTheme } from '../theme'
import { usePageMeta } from '../site'
import { buildFolderOptions } from '../lib/tree'
import MarkdownView from '../components/MarkdownView'
import ProjectFileTree from '../components/ProjectFileTree'
import MarkdownAssistant from '../components/MarkdownAssistant'
import { ArticlePublishControl, DraftProjectBanner } from '../components/PublishControl'
import Icon from '../components/Icon'
import type { NoteNode, Project } from '../types'

function insertAt(text: string, snippet: string, start: number, end: number) {
  const next = `${text.slice(0, start)}${snippet}${text.slice(end)}`
  return { next, caret: start + snippet.length }
}

/** 简单解析导入 .md 文件顶部的 YAML frontmatter（title / tags） */
function parseFrontmatter(raw: string) {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) return { title: '', tags: '', body: raw }
  const meta = match[1]
  const body = match[2]
  const titleMatch = meta.match(/^title:\s*(.+)$/m)
  const tagsMatch = meta.match(/^tags:\s*(.+)$/m)
  const clean = (s: string) => s.trim().replace(/^['"]|['"]$/g, '')
  const tagsRaw = tagsMatch ? tagsMatch[1].trim().replace(/^\[|\]$/g, '') : ''
  const tags = tagsRaw ? tagsRaw.split(',').map((t) => clean(t)).filter(Boolean).join(', ') : ''
  return {
    title: titleMatch ? clean(titleMatch[1]) : '',
    tags,
    body,
  }
}

export default function Editor() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { resolved } = useTheme()
  const nodeId = Number(searchParams.get('nodeId') || 0)
  const projectId = Number(searchParams.get('projectId') || 0)
  const parentId = Number(searchParams.get('parentId') || 0)
  const dailyDate = searchParams.get('dailyDate') || ''
  const fromPath = searchParams.get('from') || ''
  const initialTitle = searchParams.get('title') || ''
  const initialStatus = searchParams.get('status') === 'draft' ? 'draft' : 'published'

  const [kind, setKind] = useState<'folder' | 'doc'>(searchParams.get('kind') === 'folder' ? 'folder' : 'doc')
  const [title, setTitle] = useState(initialTitle)
  const [slug, setSlug] = useState('')
  const [content, setContent] = useState('')
  const [tags, setTags] = useState('')
  const [status, setStatus] = useState<'draft' | 'published'>(initialStatus)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [publishingProject, setPublishingProject] = useState(false)
  const [savedAt, setSavedAt] = useState('')
  const [uploading, setUploading] = useState(false)
  const [projectInfo, setProjectInfo] = useState<Project | null>(null)
  const [projectNodes, setProjectNodes] = useState<NoteNode[]>([])
  const [nodeProjectId, setNodeProjectId] = useState(0)
  const [parent, setParent] = useState(parentId)
  const [loadingNode, setLoadingNode] = useState(Boolean(nodeId))
  const [explorerOpen, setExplorerOpen] = useState(false)
  const [mode, setMode] = useState<'write' | 'split'>(
    () => (typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches ? 'write' : 'split'),
  )
  const [dirty, setDirty] = useState(false)
  const [autosavedAt, setAutosavedAt] = useState('')
  const [restorable, setRestorable] = useState<{ title: string; content: string; tags: string; at: string } | null>(null)
  const [revisions, setRevisions] = useState<{ id: number; title: string; created_at: string }[] | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const mdRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const saveRef = useRef<() => void>(() => {})
  const pid = projectId || nodeProjectId
  const draftKey = `notes_draft_${nodeId || `new-${projectId || 0}-${parentId}`}`
  const backTarget = fromPath.startsWith('/') ? fromPath : (user?.username === 'coustea' ? '/admin' : (pid ? `/p/${pid}` : '/'))
  const backLabel = fromPath.startsWith('/admin/projects/') ? '返回项目目录' : user?.username === 'coustea' ? '返回文章管理' : '返回阅读页'
  const folderOptions = useMemo(
    () => buildFolderOptions(projectNodes, kind === 'folder' ? nodeId : undefined),
    [projectNodes, kind, nodeId],
  )

  usePageMeta(nodeId ? '编辑内容' : '新建笔记')

  const loadTree = useCallback(async () => {
    if (!pid) return
    const res = await api.getProject(pid)
    setProjectInfo(res.project)
    setProjectNodes(res.nodes)
  }, [pid])

  useEffect(() => { loadTree().catch((e) => setError(e.message)) }, [loadTree])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  const readDraft = useCallback(() => {
    try {
      const raw = localStorage.getItem(draftKey)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }, [draftKey])

  useEffect(() => {
    let cancelled = false
    setRevisions(null)
    setHistoryOpen(false)
    setRestorable(null)
    setError('')
    if (!nodeId) {
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
        if (cancelled) return
        setTitle(node.title)
        setSlug(node.slug)
        setContent(node.content)
        setTags(node.tags)
        setStatus(node.status)
        setKind(node.kind)
        setNodeProjectId(node.project_id)
        setParent(node.parent_id)
        setDirty(false)
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
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoadingNode(false) })
    return () => { cancelled = true }
  }, [nodeId, readDraft, draftKey])

  useEffect(() => {
    if (!dirty) return
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(draftKey, JSON.stringify({
          title, content, tags, at: new Date().toISOString(),
        }))
        setAutosavedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
      } catch {
        // 配额满时静默忽略本地草稿
      }
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [dirty, title, content, tags, draftKey])

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

  const toggleHistory = async () => {
    if (historyOpen) { setHistoryOpen(false); return }
    setHistoryOpen(true)
    if (revisions) return
    try {
      const result = await api.nodeRevisions(nodeId)
      setRevisions(result.revisions)
    } catch (e: any) { setError(e.message); setHistoryOpen(false) }
  }

  const loadRevision = async (revisionId: number) => {
    if (dirty && !window.confirm('加载历史版本会覆盖当前未保存的修改，确定继续吗？')) return
    try {
      const { revision } = await api.nodeRevision(nodeId, revisionId)
      setTitle(revision.title)
      setSlug(revision.slug)
      setContent(revision.content)
      setTags(revision.tags)
      setDirty(true)
      setHistoryOpen(false)
      setError('')
    } catch (e: any) { setError(e.message) }
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

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(event.clipboardData?.items || [])
    const image = items.find((item) => item.type.startsWith('image/'))
    if (!image) return
    const file = image.getAsFile()
    if (!file) return
    event.preventDefault()
    uploadAttachment(file)
  }

  const loadMarkdownFile = async (file: File) => {
    if (file.size > 2 * 1024 * 1024) { setError('单个 Markdown 文件不能超过 2MB'); return }
    if (dirty && !window.confirm('当前有未保存的修改，导入会覆盖正文，确定继续吗？')) return
    try {
      const parsed = parseFrontmatter(await file.text())
      setContent(parsed.body)
      if (parsed.tags && !tags.trim()) setTags(parsed.tags)
      if (!title.trim()) {
        const heading = parsed.body.split('\n').map((line) => line.trim()).find((line) => /^#\s+/.test(line))
        const fallback = file.name.replace(/\.(md|markdown|mdx|txt)$/i, '')
        setTitle((parsed.title || (heading ? heading.replace(/^#\s+/, '') : fallback)).slice(0, 120))
      }
      setDirty(true)
      setError('')
      setNotice(`已载入「${file.name}」（${parsed.body.length} 字），请确认后保存或发布`)
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

  const applyGenerated = (markdown: string, range?: { start: number; end: number }) => {
    setContent((current) => range
      ? `${current.slice(0, range.start)}${markdown}${current.slice(range.end)}`
      : `${current}${current ? current.endsWith('\n\n') ? '' : current.endsWith('\n') ? '\n' : '\n\n' : ''}${markdown}`)
    setDirty(true)
  }

  const save = async (nextStatus?: 'draft' | 'published') => {
    if (loadingNode) return
    if (!title.trim()) { setError('标题不能为空'); return }
    if (!nodeId && !projectId) { setError('缺少项目信息'); return }
    if (saving) return
    const effectiveStatus = nextStatus ?? status
    setSaving(true)
    setError('')
    try {
      const payload: Record<string, unknown> = {
        title: title.trim(),
        slug,
        content,
        tags,
        status: effectiveStatus,
        parentId: parent,
      }
      if (!nodeId) {
        payload.sortOrder = Math.max(-1, ...projectNodes.filter((node) => node.parent_id === parent).map((node) => node.sort_order)) + 1
      }
      if (!nodeId && dailyDate) payload.dailyDate = dailyDate
      const res = nodeId
        ? await api.updateNode(nodeId, payload)
        : await api.createNode({ projectId, kind, ...payload })
      setStatus(effectiveStatus)
      setDirty(false)
      setAutosavedAt('')
      setSavedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
      localStorage.removeItem(draftKey)
      setNodeProjectId(res.node.project_id)
      await loadTree()
      if (nextStatus === 'published') setNotice(status === 'published' ? '已更新发布内容' : '文章已发布')
      else if (nextStatus === 'draft') setNotice('已存为草稿')
      if (!nodeId) {
        const nextParams = new URLSearchParams({ nodeId: String(res.node.id) })
        if (fromPath) nextParams.set('from', fromPath)
        navigate(`/edit?${nextParams.toString()}`, { replace: true })
      }
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  saveRef.current = () => { save() }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        saveRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const publishProject = async () => {
    if (!projectInfo || publishingProject) return
    setPublishingProject(true)
    setError('')
    try {
      await api.updateProject(projectInfo.id, { status: 'published' })
      await loadTree()
      setNotice(`已发布项目「${projectInfo.name}」`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setPublishingProject(false)
    }
  }

  const renameInTree = async (target: NoteNode, newTitle: string) => {
    try {
      await api.updateNode(target.id, { title: newTitle })
      if (target.id === nodeId) setTitle(newTitle)
      await loadTree()
      setNotice(`已重命名为「${newTitle}」`)
    } catch (e: any) {
      setError(e.message)
      throw e
    }
  }

  const goBack = () => {
    if (dirty && !window.confirm('还有未保存的修改，确定离开吗？')) return
    navigate(backTarget)
  }

  const openNode = (target: NoteNode) => {
    if (target.id === nodeId) return
    if (dirty && !window.confirm('还有未保存的修改，确定切换笔记吗？')) return
    const nextParams = new URLSearchParams({ nodeId: String(target.id) })
    if (fromPath) nextParams.set('from', fromPath)
    navigate(`/edit?${nextParams.toString()}`)
  }

  const createInTree = async (targetParent: number, targetKind: 'folder' | 'doc', targetTitle: string) => {
    if (targetKind === 'doc' && dirty && !window.confirm('还有未保存的修改，确定新建并打开笔记吗？')) throw new Error('已取消新建')
    try {
      const sortOrder = Math.max(-1, ...projectNodes.filter((node) => node.parent_id === targetParent).map((node) => node.sort_order)) + 1
      const { node } = await api.createNode({ projectId: pid, parentId: targetParent, kind: targetKind, title: targetTitle, sortOrder, status: targetKind === 'doc' ? 'draft' : 'published' })
      await loadTree()
      if (targetKind === 'doc') {
        const nextParams = new URLSearchParams({ nodeId: String(node.id) })
        if (fromPath) nextParams.set('from', fromPath)
        navigate(`/edit?${nextParams.toString()}`)
      }
    } catch (e: any) { setError(e.message); throw e }
  }

  const moveInTree = async (targetId: number, targetParent: number, beforeId: number | null) => {
    try {
      await api.moveNode(targetId, { parentId: targetParent, beforeId })
      await loadTree()
    } catch (e: any) { setError(e.message); throw e }
  }

  const deleteInTree = async (target: NoteNode) => {
    if (!window.confirm(`删除「${target.title}」${target.kind === 'folder' ? '及其全部子内容' : ''}？可以在回收站里恢复。`)) return
    try {
      let current = projectNodes.find((node) => node.id === nodeId)
      const removingCurrent = (() => {
        const seen = new Set<number>()
        while (current && !seen.has(current.id)) {
          if (current.id === target.id) return true
          seen.add(current.id)
          current = projectNodes.find((node) => node.id === current!.parent_id)
        }
        return false
      })()
      await api.deleteNode(target.id)
      if (removingCurrent) {
        localStorage.removeItem(draftKey)
        setDirty(false)
        navigate(backTarget)
      } else {
        await loadTree()
      }
    } catch (e: any) { setError(e.message) }
  }

  const previewHref = nodeId > 0 && pid > 0
    ? `/p/${pid}/n/${nodeId}${status === 'draft' ? '?preview=1' : ''}`
    : ''

  return (
    <div className="page editor-page">
      <div className="editor-head">
        <div className="editor-head-left">
          <button type="button" onClick={goBack} className="back-link">
            <Icon name="arrow-left" size={13} />{backLabel}
          </button>
          <span className="editor-status-text">
            {dirty
              ? (autosavedAt ? `未保存 · 本地草稿 ${autosavedAt}` : '有未保存的修改')
              : (savedAt ? `已保存于 ${savedAt}` : (nodeId ? '已同步' : '新建笔记'))}
          </span>
        </div>
        <div className="head-actions">
          {pid > 0 && (
            <button type="button" className="btn btn-sm nav-toggle" aria-expanded={explorerOpen} aria-controls="editor-explorer"
              onClick={() => setExplorerOpen((open) => !open)}>
              <Icon name="list" size={15} />目录
            </button>
          )}
          {nodeId > 0 && kind === 'doc' && (
            <button type="button" className="btn btn-sm" onClick={toggleHistory} aria-expanded={historyOpen} aria-controls={historyOpen ? 'revision-history' : undefined}>
              历史版本
            </button>
          )}
          {previewHref && kind === 'doc' && (
            <Link className="btn btn-sm" to={previewHref}>
              <Icon name="book-open" size={14} />{status === 'draft' ? '预览草稿' : '查看文章'}
            </Link>
          )}
          <ArticlePublishControl
            mode="editor"
            status={status}
            busy={saving || loadingNode}
            onPublish={() => save('published')}
            onDraft={() => save('draft')}
            saveHint="Cmd/Ctrl + S"
          />
        </div>
      </div>

      {projectInfo?.status === 'draft' && (
        <DraftProjectBanner
          projectName={projectInfo.name}
          busy={publishingProject}
          onPublishProject={publishProject}
        />
      )}

      {error && (
        <div className="alert" role="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
          <button type="button" className="link-btn" style={{ marginLeft: 'auto', fontSize: 12 }} onClick={() => setError('')}>关闭</button>
        </div>
      )}

      {notice && (
        <div className="alert alert-info" role="status">
          <Icon name="check-circle" size={16} />
          <span>{notice}</span>
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
            <button type="button" className="btn btn-sm" onClick={discardDraft}>丢弃</button>
            <button type="button" className="btn btn-sm btn-primary" onClick={applyDraft}>恢复草稿</button>
          </div>
        </div>
      )}

      {historyOpen && (
        <div id="revision-history" className="alert alert-info" style={{ display: 'block' }}>
          <h2 style={{ fontSize: 16 }}>历史版本</h2>
          <p>点击版本会加载到编辑器，确认内容后再点“保存”。</p>
          {revisions === null ? <span>正在读取…</span> : revisions.length === 0 ? <span>还没有旧版本</span> : (
            <ol style={{ maxHeight: 220, overflowY: 'auto', marginTop: 8 }}>
              {revisions.map((revision) => (
                <li key={revision.id} style={{ marginBottom: 8 }}>
                  <button type="button" className="btn btn-sm" onClick={() => loadRevision(revision.id)}>
                    {revision.title} · 备份于 {revision.created_at} · #{revision.id}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      <div className="editor-workspace">
        {pid > 0 && (
          <aside id="editor-explorer" className={`editor-explorer side-panel ${explorerOpen ? 'is-open' : ''}`} aria-label="项目文件树">
            <ProjectFileTree
              nodes={projectNodes}
              selectedId={nodeId || null}
              owner
              onSelect={openNode}
              onCreate={createInTree}
              onRename={renameInTree}
              onMove={moveInTree}
              onDelete={deleteInTree}
              onEdit={openNode}
            />
          </aside>
        )}

        <div className="editor-main">
          <div className="editor-meta-card">
            <input
              className="editor-title-input"
              value={title}
              onChange={(e) => { setTitle(e.target.value); setDirty(true) }}
              autoFocus
              placeholder="输入文章标题…"
              aria-label="文章标题"
            />
            <div className="editor-meta-row">
              {pid > 0 && (
                <label className="editor-inline-field editor-folder-field">
                  <span>所属目录</span>
                  <select
                    className="select"
                    value={parent}
                    onChange={(e) => { setParent(Number(e.target.value)); setDirty(true) }}
                  >
                    {folderOptions.map((opt) => (
                      <option key={opt.id} value={opt.id}>{opt.label}</option>
                    ))}
                  </select>
                </label>
              )}
              <label className="editor-inline-field">
                <span>标签</span>
                <input
                  className="input"
                  value={tags}
                  onChange={(e) => { setTags(e.target.value); setDirty(true) }}
                  placeholder="英文逗号分隔，如 Go, 并发"
                />
              </label>
              <details className="editor-advanced">
                <summary>URL 标识</summary>
                <input
                  className="input"
                  value={slug}
                  onChange={(e) => { setSlug(e.target.value); setDirty(true) }}
                  placeholder="留空自动生成"
                  aria-label="URL 标识"
                />
              </details>
            </div>
          </div>

          {kind === 'doc' && (
            <div className="editor-markdown" data-color-mode={resolved}>
              <div className="editor-toolbar">
                <div className="edit-tabs">
                  <button type="button" className={mode === 'write' ? 'on' : ''} onClick={() => setMode('write')}>写</button>
                  <button type="button" className={mode === 'split' ? 'on' : ''} onClick={() => setMode('split')}>并排预览</button>
                </div>
                <span className="toolbar-sep" />
                <div className="format-buttons">
                  <button type="button" className="icon-btn" title="二级标题" onClick={() => wrapSelection('## ')}>H2</button>
                  <button type="button" className="icon-btn" title="加粗" onClick={() => wrapSelection('**', '**')}>加粗</button>
                  <button type="button" className="icon-btn" title="行内代码" onClick={() => wrapSelection('`', '`')}>代码</button>
                  <button type="button" className="icon-btn" title="链接" onClick={() => wrapSelection('[', '](https://)')}>链接</button>
                  <button type="button" className="icon-btn" title="引用" onClick={() => wrapSelection('> ')}>引用</button>
                </div>
                <span className="toolbar-sep" />
                <button type="button" className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
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
                <button type="button" className="btn btn-sm" onClick={() => mdRef.current?.click()}>
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
                <span className="hint">Cmd/Ctrl + S 原地保存 · 可直接粘贴截图</span>
              </div>

              {!loadingNode && user?.username === 'coustea' && (
                <MarkdownAssistant
                  key={nodeId || `new-${projectId}`}
                  title={title}
                  content={content}
                  textareaRef={textareaRef}
                  onApply={applyGenerated}
                />
              )}

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
      </div>
    </div>
  )
}
