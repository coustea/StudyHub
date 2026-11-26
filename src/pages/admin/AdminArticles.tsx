import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { usePageMeta } from '../../site'
import Icon from '../../components/Icon'
import { Button } from '../../components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../../components/ui/dialog'
import type { AdminNote, AiConfig, Project } from '../../types'

const formatDate = (value: string) => String(value || '').slice(0, 10)

export default function AdminArticles() {
  const navigate = useNavigate()
  const [notes, setNotes] = useState<AdminNote[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [aiConfig, setAiConfig] = useState<AiConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [query, setQuery] = useState('')
  const [projectId, setProjectId] = useState<number>(0)
  const [statusFilter, setStatusFilter] = useState<'all' | 'published' | 'draft'>('all')
  const [sortBy, setSortBy] = useState<'updated' | 'created' | 'title'>('updated')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [busyId, setBusyId] = useState<number>(0)
  const [batchBusy, setBatchBusy] = useState(false)
  const [startingDaily, setStartingDaily] = useState(false)

  const [showNew, setShowNew] = useState(false)
  const [newProjectId, setNewProjectId] = useState<number>(0)
  const [newTitle, setNewTitle] = useState('')
  const [newStatus, setNewStatus] = useState<'draft' | 'published'>('published')
  const newTriggerRef = useRef<HTMLButtonElement | null>(null)

  usePageMeta('文章管理')

  const load = useCallback(async () => {
    const [notesRes, overviewRes, aiRes] = await Promise.all([
      api.adminNotes(),
      api.overview(false),
      api.aiConfig().catch(() => ({ config: null })),
    ])
    setNotes(notesRes.notes)
    setProjects(overviewRes.projects || [])
    setAiConfig(aiRes.config)
    setSelectedIds((prev) => prev.filter((id) => notesRes.notes.some((n) => n.id === id)))
  }, [])

  useEffect(() => {
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [load])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const list = notes.filter((note) => {
      if (statusFilter !== 'all' && note.status !== statusFilter) return false
      if (projectId && note.project_id !== projectId) return false
      if (needle && !`${note.title} ${note.project_name} ${note.tags}`.toLowerCase().includes(needle)) return false
      return true
    })
    return [...list].sort((a, b) => {
      if (sortBy === 'title') return a.title.localeCompare(b.title, 'zh-CN')
      if (sortBy === 'created') return b.created_at.localeCompare(a.created_at)
      return b.updated_at.localeCompare(a.updated_at)
    })
  }, [notes, query, projectId, statusFilter, sortBy])

  const publishedCount = notes.filter((n) => n.status === 'published').length
  const draftCount = notes.length - publishedCount
  const allVisibleSelected = filtered.length > 0 && filtered.every((n) => selectedIds.includes(n.id))

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      const visibleSet = new Set(filtered.map((n) => n.id))
      setSelectedIds((prev) => prev.filter((id) => !visibleSet.has(id)))
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...filtered.map((n) => n.id)])])
    }
  }

  const toggleOne = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]))
  }

  const togglePublish = async (note: AdminNote) => {
    setBusyId(note.id)
    setError('')
    try {
      const nextStatus = note.status === 'published' ? 'draft' : 'published'
      await api.updateNode(note.id, { status: nextStatus })
      await load()
      setNotice(nextStatus === 'published' ? `已发布「${note.title}」` : `已将「${note.title}」转为草稿`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusyId(0)
    }
  }

  const trashNote = async (note: AdminNote) => {
    if (!window.confirm(`将「${note.title}」移入回收站？可以在回收站中恢复。`)) return
    setBusyId(note.id)
    setError('')
    try {
      await api.deleteNode(note.id)
      await load()
      setNotice(`已移入回收站：「${note.title}」`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusyId(0)
    }
  }

  const runBatch = async (action: 'publish' | 'draft' | 'trash') => {
    if (!selectedIds.length || batchBusy) return
    if (action === 'trash' && !window.confirm(`确定将选中的 ${selectedIds.length} 篇文章移入回收站？`)) return
    setBatchBusy(true)
    setError('')
    try {
      const res = await api.batchAdminNotes(selectedIds, action)
      setSelectedIds([])
      await load()
      const label = action === 'publish' ? '发布' : action === 'draft' ? '转为草稿' : '移入回收站'
      setNotice(`已批量${label} ${res.affected} 篇文章`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBatchBusy(false)
    }
  }

  const openNewDialog = () => {
    if (!projects.length) {
      navigate('/admin/projects')
      return
    }
    setNewProjectId(projectId || projects[0]?.id || 0)
    setNewTitle('')
    setNewStatus('published')
    setShowNew(true)
  }

  const startNewArticle = () => {
    if (!newProjectId) return
    const params = new URLSearchParams({
      projectId: String(newProjectId),
      status: newStatus,
      from: '/admin',
    })
    if (newTitle.trim()) params.set('title', newTitle.trim())
    setShowNew(false)
    navigate(`/edit?${params.toString()}`)
  }

  const startDaily = async () => {
    if (startingDaily) return
    setStartingDaily(true)
    try {
      const res = await api.dailyNew({})
      navigate(`/edit?nodeId=${res.node.id}`)
    } catch (e: any) {
      setError(e.message)
      setStartingDaily(false)
    }
  }

  return (
    <div className="admin-page">
      <div className="page-title-row">
        <div>
          <h1>文章管理</h1>
          <p>集中管理全部已发布与草稿文章；支持筛选、快捷切换状态、批量操作与进入编辑。</p>
        </div>
        <div className="head-actions">
          <Link className="btn btn-sm" to="/admin/settings#ai-model">
            <Icon name="sparkle" size={14} />
            {aiConfig?.hasApiKey && aiConfig?.model ? `模型：${aiConfig.model}` : '配置系统模型'}
          </Link>
          <button type="button" className="btn btn-sm" onClick={startDaily} disabled={startingDaily}>
            <Icon name="flame" size={14} />{startingDaily ? '准备中…' : '写今日笔记'}
          </button>
          <button
            ref={newTriggerRef}
            type="button"
            className="btn btn-primary btn-sm"
            onClick={openNewDialog}
          >
            <Icon name="plus" size={14} />{projects.length ? '新建文章' : '先建项目'}
          </button>
        </div>
      </div>

      <div className="admin-stats-bar" role="group" aria-label="文章概览">
        <button type="button" className={`admin-stat-btn${statusFilter === 'all' ? ' is-active' : ''}`} onClick={() => setStatusFilter('all')}>
          <strong>{notes.length}</strong><span>全部文章</span>
        </button>
        <button type="button" className={`admin-stat-btn${statusFilter === 'published' ? ' is-active' : ''}`} onClick={() => setStatusFilter('published')}>
          <strong>{publishedCount}</strong><span>已发布</span>
        </button>
        <button type="button" className={`admin-stat-btn${statusFilter === 'draft' ? ' is-active' : ''}`} onClick={() => setStatusFilter('draft')}>
          <strong>{draftCount}</strong><span>草稿</span>
        </button>
        <Link className="admin-stat-btn" to="/admin/projects">
          <strong>{projects.length}</strong><span>项目总数</span>
        </Link>
      </div>

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

      <div className="admin-toolbar">
        <span className="filter-wrap">
          <span className="search-glyph"><Icon name="search" size={15} /></span>
          <input
            className="filter-input"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索文章标题、标签或项目"
            aria-label="搜索文章"
          />
        </span>
        <select className="select" value={projectId} onChange={(e) => setProjectId(Number(e.target.value))} aria-label="按项目筛选">
          <option value={0}>全部项目</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select className="select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)} aria-label="按状态筛选">
          <option value="all">全部状态</option>
          <option value="published">已发布</option>
          <option value="draft">草稿</option>
        </select>
        <select className="select" value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)} aria-label="排序方式">
          <option value="updated">按更新时间</option>
          <option value="created">按创建时间</option>
          <option value="title">按标题排序</option>
        </select>
      </div>

      {selectedIds.length > 0 && (
        <div className="admin-batch-bar" role="region" aria-label="批量操作">
          <span>已选 <strong>{selectedIds.length}</strong> 篇</span>
          <div className="admin-batch-actions">
            <button type="button" className="btn btn-sm" onClick={() => runBatch('publish')} disabled={batchBusy}>批量发布</button>
            <button type="button" className="btn btn-sm" onClick={() => runBatch('draft')} disabled={batchBusy}>批量转草稿</button>
            <button type="button" className="btn btn-sm btn-danger" onClick={() => runBatch('trash')} disabled={batchBusy}>移入回收站</button>
            <button type="button" className="link-btn" onClick={() => setSelectedIds([])}>取消选择</button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading-line"><span className="spinner" />正在读取文章列表…</div>
      ) : filtered.length === 0 ? (
        <div className="empty">
          <Icon name="file" size={26} className="empty-icon" />
          <span className="empty-title">{notes.length ? '没有匹配的文章' : '还没有文章'}</span>
          <p>{notes.length ? '调整搜索关键词或筛选条件试试。' : projects.length ? '点击右上角「新建文章」，或导入 Markdown 文件夹。' : '先创建一个项目，再开始写第一篇文章。'}</p>
          {!projects.length && <Link className="btn btn-primary btn-sm" to="/admin/projects">前往项目管理</Link>}
        </div>
      ) : (
        <div tabIndex={0} role="region" aria-labelledby="admin-articles-caption" className="table-wrapper">
          <table className="admin-table">
            <caption id="admin-articles-caption" className="sr-only">文章管理列表（共 {filtered.length} 篇）</caption>
            <thead>
              <tr>
                <th scope="col" className="col-check">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    aria-label="全选当前列表"
                  />
                </th>
                <th scope="col">文章标题</th>
                <th scope="col">所属项目</th>
                <th scope="col">状态</th>
                <th scope="col">更新时间</th>
                <th scope="col" className="col-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((note) => {
                const busy = busyId === note.id
                const previewUrl = `/p/${note.project_id}/n/${note.id}${note.status === 'draft' || note.project_status === 'draft' ? '?preview=1' : ''}`
                return (
                  <tr key={note.id} className={selectedIds.includes(note.id) ? 'is-selected' : ''}>
                    <td className="col-check">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(note.id)}
                        onChange={() => toggleOne(note.id)}
                        aria-label={`选择 ${note.title}`}
                      />
                    </td>
                    <th scope="row" className="col-title">
                      <Link to={`/edit?nodeId=${note.id}`} className="admin-note-title">{note.title}</Link>
                      {note.tags && <span className="admin-note-tags">{note.tags}</span>}
                    </th>
                    <td>
                      <Link to={`/admin/projects/${note.project_id}`} className="admin-project-link">{note.project_name}</Link>
                      {note.project_status === 'draft' && <span className="dim" style={{ fontSize: 11, marginLeft: 4 }}>(草稿项目)</span>}
                    </td>
                    <td>
                      <span className={`badge ${note.status === 'published' ? 'badge-published' : 'badge-draft'}`}>
                        {note.status === 'published' ? '已发布' : '草稿'}
                      </span>
                      {note.status === 'published' && note.project_status === 'draft' && (
                        <span className="dim" style={{ display: 'block', fontSize: 11, marginTop: 3 }} title="所属项目仍为草稿，发布项目后访客可见">
                          项目未发布
                        </span>
                      )}
                    </td>
                    <td className="col-date">{formatDate(note.updated_at)}</td>
                    <td className="col-actions">
                      <div className="admin-row-actions">
                        <Link className="btn btn-sm btn-primary" to={`/edit?nodeId=${note.id}`}>编辑</Link>
                        <Link className="btn btn-sm" to={previewUrl}>预览</Link>
                        <button type="button" className="btn btn-sm" onClick={() => togglePublish(note)} disabled={busy}>
                          {note.status === 'published' ? '转草稿' : '发布'}
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => trashNote(note)}
                          disabled={busy}
                          aria-label={`删除 ${note.title}`}
                          title="移入回收站"
                        >
                          <Icon name="trash-simple" size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={showNew} onOpenChange={setShowNew}>
        <DialogContent
          className="study-dialog sm:max-w-lg"
          onCloseAutoFocus={(e) => { e.preventDefault(); newTriggerRef.current?.focus() }}
        >
          <DialogHeader>
            <DialogTitle>新建文章</DialogTitle>
            <DialogDescription>选择归属项目后直接进入编辑器，首次保存时才会写入数据库。</DialogDescription>
          </DialogHeader>
          <div className="modal-body">
            <label className="field">
              <span className="field-label">所属项目</span>
              <select className="select" value={newProjectId} onChange={(e) => setNewProjectId(Number(e.target.value))}>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{p.status === 'draft' ? '（草稿项目）' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">文章标题（选填，可在编辑器中填写）</span>
              <input
                className="input"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="例如：Go 并发原语与 Context 实践"
                autoFocus
                onKeyDown={(e) => { if (e.key === 'Enter') startNewArticle() }}
              />
            </label>
            <label className="field">
              <span className="field-label">默认状态</span>
              <select className="select" value={newStatus} onChange={(e) => setNewStatus(e.target.value as 'draft' | 'published')}>
                <option value="published">已发布（访客可见）</option>
                <option value="draft">先存草稿（访客不可见）</option>
              </select>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNew(false)}>取消</Button>
            <Button onClick={startNewArticle} disabled={!newProjectId}>
              进入编辑器
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
