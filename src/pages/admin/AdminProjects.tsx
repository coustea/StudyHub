import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { usePageMeta } from '../../site'
import { countFolders, readFromDataTransfer, readFromFileList, type FolderReadResult } from '../../lib/folder'
import Icon from '../../components/Icon'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../../components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../../components/ui/dialog'
import type { Project } from '../../types'

const formatDate = (value: string) => String(value || '').slice(0, 10)

export default function AdminProjects() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [dragging, setDragging] = useState(false)

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'draft' | 'published'>('published')
  const [creating, setCreating] = useState(false)

  const [folder, setFolder] = useState<FolderReadResult | null>(null)
  const [folderName, setFolderName] = useState('')
  const [folderDescription, setFolderDescription] = useState('')
  const [folderStatus, setFolderStatus] = useState<'draft' | 'published'>('published')
  const [importing, setImporting] = useState(false)

  const [editing, setEditing] = useState<Project | null>(null)
  const [formName, setFormName] = useState('')
  const [formDesc, setFormDesc] = useState('')
  const [formSort, setFormSort] = useState(0)

  const folderInputRef = useRef<HTMLInputElement | null>(null)
  const createTriggerRef = useRef<HTMLButtonElement | null>(null)

  usePageMeta('项目管理')

  const load = useCallback(() => api.overview(false).then((res) => setProjects(res.projects || [])), [])

  useEffect(() => {
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [load])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  const create = async () => {
    if (!name.trim() || creating) return
    setCreating(true)
    try {
      const res = await api.createProject({ name: name.trim(), description, status })
      setShowCreate(false)
      setName('')
      setDescription('')
      navigate(`/admin/projects/${res.project.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  const openFolder = (result: FolderReadResult) => {
    if (!result.files.length) { setError('这个文件夹里没有找到 Markdown 文件（.md / .mdx / .txt）'); return }
    setError('')
    setFolder(result)
    setFolderName(result.rootName || '未命名项目')
    setFolderDescription('')
    setFolderStatus('published')
  }

  const pickFolder = async (event: ChangeEvent<HTMLInputElement>) => {
    const result = await readFromFileList(event.target.files)
    event.target.value = ''
    openFolder(result)
  }

  const onDrop = async (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    openFolder(await readFromDataTransfer(event.dataTransfer))
  }

  const createFromFolder = async () => {
    if (!folder || !folder.files.length || importing) return
    setImporting(true)
    try {
      const res = await api.createProjectFromFolder({
        name: folderName.trim(), description: folderDescription, status: folderStatus, files: folder.files,
      })
      setFolder(null)
      navigate(`/admin/projects/${res.project.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setImporting(false)
    }
  }

  const togglePublish = async (project: Project) => {
    try {
      const next = project.status === 'published' ? 'draft' : 'published'
      await api.updateProject(project.id, { status: next })
      await load()
      setNotice(next === 'published' ? `已发布项目「${project.name}」` : `已将「${project.name}」转为草稿`)
    } catch (e: any) { setError(e.message) }
  }

  const openEdit = (project: Project) => {
    setEditing(project)
    setFormName(project.name)
    setFormDesc(project.description)
    setFormSort(project.sort_order)
  }

  const saveEdit = async () => {
    if (!editing) return
    try {
      await api.updateProject(editing.id, { name: formName.trim(), description: formDesc, sort_order: formSort })
      setEditing(null)
      await load()
      setNotice('项目信息已更新')
    } catch (e: any) { setError(e.message) }
  }

  const removeProject = async (project: Project) => {
    if (!window.confirm(`确定删除项目「${project.name}」及其全部笔记？此操作不可撤销。`)) return
    try {
      await api.deleteProject(project.id)
      setEditing(null)
      await load()
      setNotice(`已删除项目「${project.name}」`)
    } catch (e: any) { setError(e.message) }
  }

  return (
    <div className="admin-page">
      <div className="page-title-row">
        <div>
          <h1>项目管理</h1>
          <p>每个项目对应一本专题册子。支持拖入本地 Markdown 文件夹自动重建多级目录。</p>
        </div>
        <div className="head-actions">
          <button type="button" className="btn btn-sm" onClick={() => folderInputRef.current?.click()}>
            <Icon name="upload" size={14} />用文件夹建项目
          </button>
          <button ref={createTriggerRef} type="button" className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
            <Icon name="plus" size={14} />新建项目
          </button>
          <input
            ref={(el) => {
              folderInputRef.current = el
              if (el) { el.setAttribute('webkitdirectory', ''); el.setAttribute('directory', '') }
            }}
            type="file"
            multiple
            className="sr-only"
            tabIndex={-1}
            aria-label="选择本地 Markdown 文件夹"
            onChange={pickFolder}
          />
        </div>
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

      <div
        className={`project-list ${dragging ? 'dragging' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {dragging && <div className="drop-veil">松开，按这个文件夹创建项目</div>}

        {loading && <div className="loading-line"><span className="spinner" />正在加载项目…</div>}

        {!loading && projects.map((project) => (
          <Card key={project.id} className="project-card admin-project-card">
            <CardHeader>
              <div className={`project-mark ${project.status === 'draft' ? 'is-draft' : ''}`} aria-hidden="true">
                {project.name.trim().slice(0, 1)}
              </div>
              <CardAction>
                <Badge variant={project.status === 'published' ? 'secondary' : 'outline'}>
                  {project.status === 'published' ? '已发布' : '草稿'}
                </Badge>
              </CardAction>
              <CardTitle>
                <Link to={`/admin/projects/${project.id}`}><h3>{project.name}</h3></Link>
              </CardTitle>
              <CardDescription>{project.description || '还没有填写项目描述。'}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="dim" style={{ fontSize: 12.5 }}>
                {project.doc_count || 0} 篇笔记 · {project.folder_count || 0} 个目录 · 更新于 {formatDate(project.updated_at)}
              </div>
            </CardContent>
            <CardFooter className="admin-project-actions">
              <Link className="btn btn-sm btn-primary" to={`/admin/projects/${project.id}`}>管理目录</Link>
              <button type="button" className="btn btn-sm" onClick={() => togglePublish(project)}>
                {project.status === 'published' ? '转草稿' : '发布'}
              </button>
              <button type="button" className="btn btn-sm" onClick={() => openEdit(project)}>设置</button>
            </CardFooter>
          </Card>
        ))}

        {!loading && projects.length === 0 && (
          <div className="empty">
            <Icon name="folder" size={26} className="empty-icon" />
            <span className="empty-title">还没有项目</span>
            <p>新建一个项目，或者把本地 Markdown 文件夹直接拖到这里。</p>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>新建项目</button>
          </div>
        )}
      </div>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="study-dialog sm:max-w-lg" onCloseAutoFocus={(e) => { e.preventDefault(); createTriggerRef.current?.focus() }}>
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
            <DialogDescription>一个项目对应一本专题册子，笔记按目录挂进去。</DialogDescription>
          </DialogHeader>
          <div className="modal-body">
            <label className="field">
              <span className="field-label">项目名称</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus onKeyDown={(e) => { if (e.key === 'Enter') create() }} />
            </label>
            <label className="field">
              <span className="field-label">项目描述</span>
              <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="一句话说明这个项目讲什么" />
            </label>
            <label className="field">
              <span className="field-label">初始状态</span>
              <select className="select" value={status} onChange={(e) => setStatus(e.target.value as 'draft' | 'published')}>
                <option value="published">直接发布，访客可见</option>
                <option value="draft">先存草稿，仅自己可见</option>
              </select>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>取消</Button>
            <Button onClick={create} disabled={!name.trim() || creating}>{creating ? '创建中…' : '创建项目'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {folder && (
        <Dialog open onOpenChange={(open) => { if (!open) setFolder(null) }}>
          <DialogContent className="study-dialog sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>用文件夹创建项目</DialogTitle>
              <DialogDescription>
                {folder.files.length} 篇 Markdown · {countFolders(folder.files)} 个目录
                {folder.skipped > 0 ? ` · 跳过 ${folder.skipped} 个其它文件` : ''}
              </DialogDescription>
            </DialogHeader>
            <div className="modal-body">
              <label className="field">
                <span className="field-label">项目名称</span>
                <input className="input" value={folderName} onChange={(e) => setFolderName(e.target.value)} autoFocus />
              </label>
              <label className="field">
                <span className="field-label">项目描述</span>
                <textarea className="textarea" value={folderDescription} onChange={(e) => setFolderDescription(e.target.value)} rows={2} />
              </label>
              <label className="field">
                <span className="field-label">发布状态</span>
                <select className="select" value={folderStatus} onChange={(e) => setFolderStatus(e.target.value as 'draft' | 'published')}>
                  <option value="published">直接发布，访客可见</option>
                  <option value="draft">先存草稿，仅自己可见</option>
                </select>
              </label>
              <div className="file-preview">
                {folder.files.slice(0, 6).map((f) => <div key={f.path}>{f.path}</div>)}
                {folder.files.length > 6 && <div className="dim">还有 {folder.files.length - 6} 篇…</div>}
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setFolder(null)} disabled={importing}>取消</Button>
              <Button onClick={createFromFolder} disabled={importing || !folderName.trim()}>{importing ? '导入中…' : '创建并导入'}</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {editing && (
        <Dialog open onOpenChange={(open) => { if (!open) setEditing(null) }}>
          <DialogContent className="study-dialog sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>项目设置</DialogTitle>
              <DialogDescription>修改项目名称、描述、排序，或删除整个项目。</DialogDescription>
            </DialogHeader>
            <div className="modal-body">
              <label className="field">
                <span className="field-label">项目名称</span>
                <input className="input" value={formName} onChange={(e) => setFormName(e.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">项目描述</span>
                <textarea className="textarea" value={formDesc} onChange={(e) => setFormDesc(e.target.value)} rows={3} />
              </label>
              <label className="field">
                <span className="field-label">排序</span>
                <input className="input" type="number" value={formSort} onChange={(e) => setFormSort(Number(e.target.value))} />
                <span className="field-hint">数字小的排在前面。</span>
              </label>
            </div>
            <DialogFooter>
              <Button variant="destructive" onClick={() => removeProject(editing)} style={{ marginRight: 'auto' }}>删除项目</Button>
              <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
              <Button onClick={saveEdit} disabled={!formName.trim()}>保存</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
