import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api'
import { usePageMeta } from '../../site'
import { countFolders, readFromDataTransfer, readFromFileList, type FolderReadResult } from '../../lib/folder'
import { buildFolderOptions } from '../../lib/tree'
import ProjectFileTree from '../../components/ProjectFileTree'
import MarkdownView from '../../components/MarkdownView'
import { ArticlePublishControl, DraftProjectBanner, ProjectPublishControl } from '../../components/PublishControl'
import Icon from '../../components/Icon'
import { Button } from '../../components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../../components/ui/dialog'
import type { NoteNode, Project } from '../../types'

export default function AdminProjectTree() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [nodes, setNodes] = useState<NoteNode[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busyPublish, setBusyPublish] = useState(false)

  const [showImport, setShowImport] = useState(false)
  const [importParentId, setImportParentId] = useState<number>(0)
  const [importStatus, setImportStatus] = useState<'draft' | 'published'>('published')
  const [pendingImport, setPendingImport] = useState<FolderReadResult | null>(null)
  const [importDragging, setImportDragging] = useState(false)
  const [importing, setImporting] = useState(false)
  const filesRef = useRef<HTMLInputElement | null>(null)
  const folderRef = useRef<HTMLInputElement | null>(null)

  const load = useCallback(() => api.getProject(id!, false).then((res) => {
    setProject(res.project)
    setNodes(res.nodes)
    setSelectedId((cur) => (cur && res.nodes.some((n) => n.id === cur && n.kind === 'doc')
      ? cur
      : (res.nodes.find((n) => n.kind === 'doc')?.id ?? null)))
  }), [id])

  usePageMeta(project ? `管理目录 · ${project.name}` : '管理目录')

  useEffect(() => {
    setLoading(true)
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [load])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2800)
    return () => window.clearTimeout(timer)
  }, [notice])

  const selected = nodes.find((n) => n.id === selectedId && n.kind === 'doc') || null
  const folderOptions = useMemo(() => buildFolderOptions(nodes), [nodes])
  const draftDocIds = useMemo(
    () => nodes.filter((n) => n.kind === 'doc' && n.status === 'draft').map((n) => n.id),
    [nodes],
  )

  const createNode = async (parentId: number, kind: 'folder' | 'doc', title: string) => {
    const sortOrder = Math.max(-1, ...nodes.filter((n) => n.parent_id === parentId).map((n) => n.sort_order)) + 1
    const { node } = await api.createNode({ projectId: project!.id, parentId, kind, title, sortOrder, status: kind === 'doc' ? 'draft' : 'published' })
    await load()
    if (kind === 'doc') navigate(`/edit?nodeId=${node.id}&from=${encodeURIComponent(`/admin/projects/${project!.id}`)}`)
    else setNotice(`已创建文件夹「${title}」`)
  }

  const renameNode = async (node: NoteNode, title: string) => {
    await api.updateNode(node.id, { title })
    await load()
    setNotice(`已重命名为「${title}」`)
  }

  const moveNode = async (nodeId: number, parentId: number, beforeId: number | null) => {
    await api.moveNode(nodeId, { parentId, beforeId })
    await load()
  }

  const removeNode = async (node: NoteNode) => {
    if (!window.confirm(`删除「${node.title}」${node.kind === 'folder' ? '及其全部子内容' : ''}？可以在回收站恢复。`)) return
    await api.deleteNode(node.id)
    await load()
    setNotice(`已移入回收站：「${node.title}」`)
  }

  const setNodeStatus = async (next: 'draft' | 'published') => {
    if (!selected || busyPublish) return
    setBusyPublish(true)
    setError('')
    try {
      await api.updateNode(selected.id, { status: next })
      await load()
      setNotice(next === 'published' ? `已发布「${selected.title}」` : `已将「${selected.title}」转为草稿`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusyPublish(false)
    }
  }

  const toggleProjectPublish = async () => {
    if (!project || busyPublish) return
    setBusyPublish(true)
    setError('')
    try {
      const next = project.status === 'published' ? 'draft' : 'published'
      await api.updateProject(project.id, { status: next })
      await load()
      setNotice(next === 'published' ? `已发布项目「${project.name}」` : `已将项目「${project.name}」转为草稿`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusyPublish(false)
    }
  }

  const publishAllDrafts = async () => {
    if (!draftDocIds.length || busyPublish) return
    setBusyPublish(true)
    setError('')
    try {
      const res = await api.batchAdminNotes(draftDocIds, 'publish')
      await load()
      setNotice(`已批量发布 ${res.affected} 篇草稿笔记`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusyPublish(false)
    }
  }

  const openImportDialog = (targetParentId = 0) => {
    setImportParentId(targetParentId)
    setImportStatus(project?.status === 'draft' ? 'draft' : 'published')
    setPendingImport(null)
    setImportDragging(false)
    setError('')
    setShowImport(true)
  }

  const stageImportResult = (result: FolderReadResult) => {
    if (!result.files.length) {
      setError('未找到可导入的 Markdown 文件（支持 .md / .markdown / .mdx / .txt）')
      return
    }
    setError('')
    setPendingImport(result)
  }

  const handleImportDrop = async (event: DragEvent) => {
    event.preventDefault()
    setImportDragging(false)
    stageImportResult(await readFromDataTransfer(event.dataTransfer))
  }

  const confirmImport = async () => {
    if (!project || !pendingImport?.files.length || importing) return
    setImporting(true)
    setError('')
    try {
      const res = await api.importFiles({
        projectId: project.id,
        parentId: importParentId,
        status: importStatus,
        files: pendingImport.files,
      })
      const targetLabel = folderOptions.find((f) => f.id === importParentId)?.path || '项目根目录'
      setShowImport(false)
      setPendingImport(null)
      await load()
      setNotice(`已导入 ${res.imported} 篇笔记到「${targetLabel}」${res.duplicates ? `（跳过 ${res.duplicates} 篇重复路径）` : ''}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setImporting(false)
    }
  }

  if (loading) return <div className="admin-page"><div className="loading-line"><span className="spinner" />正在加载项目目录…</div></div>
  if (!project) {
    return (
      <div className="admin-page">
        <div className="empty">
          <span className="empty-title">项目不存在</span>
          <Link className="btn btn-sm" to="/admin/projects">返回项目管理</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="admin-page">
      <div className="page-title-row">
        <div>
          <Link to="/admin/projects" className="back-link"><Icon name="arrow-left" size={13} />项目管理</Link>
          <h1>{project.name}</h1>
          <p>支持多级文件夹创建、行内重命名、拖拽排序、指定目录导入与一键发布。</p>
        </div>
        <div className="head-actions">
          <ProjectPublishControl
            status={project.status}
            draftCount={draftDocIds.length}
            busy={busyPublish}
            onToggleProject={toggleProjectPublish}
            onPublishAllDrafts={publishAllDrafts}
          />
          <button type="button" className="btn btn-sm" onClick={() => openImportDialog(0)}>
            <Icon name="upload" size={14} />导入 Markdown
          </button>
          <Link className="btn btn-sm" to={`/p/${project.id}${project.status === 'draft' ? '?preview=1' : ''}`}>
            <Icon name="book-open" size={14} />阅读视图
          </Link>
        </div>
      </div>

      {project.status === 'draft' && (
        <DraftProjectBanner
          projectName={project.name}
          busy={busyPublish}
          onPublishProject={toggleProjectPublish}
        />
      )}

      {error && (
        <div className="alert" role="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
          <button type="button" className="link-btn" style={{ marginLeft: 'auto', fontSize: 12 }} onClick={() => setError('')}>关闭</button>
        </div>
      )}
      {notice && <div className="alert alert-info" role="status"><Icon name="check-circle" size={16} /><span>{notice}</span></div>}

      <div className="admin-tree-workspace">
        <aside className="side-panel" aria-label="项目目录树">
          <ProjectFileTree
            nodes={nodes}
            selectedId={selectedId}
            owner
            onSelect={(node) => setSelectedId(node.id)}
            onCreate={createNode}
            onRename={renameNode}
            onImportInto={(folder) => openImportDialog(folder.id)}
            onMove={moveNode}
            onDelete={removeNode}
            onEdit={(node) => navigate(`/edit?nodeId=${node.id}&from=${encodeURIComponent(`/admin/projects/${project.id}`)}`)}
          />
        </aside>

        <section className="admin-tree-preview">
          {selected ? (
            <>
              <div className="article-head">
                <div className="article-bar">
                  <span className="dim" style={{ fontSize: 12 }}>更新于 {String(selected.updated_at).slice(0, 10)}</span>
                  <div className="spacer" />
                  <ArticlePublishControl
                    status={selected.status}
                    busy={busyPublish}
                    onPublish={() => setNodeStatus('published')}
                    onDraft={() => setNodeStatus('draft')}
                  />
                  <Link className="btn btn-sm btn-primary" to={`/edit?nodeId=${selected.id}&from=${encodeURIComponent(`/admin/projects/${project.id}`)}`}>
                    <Icon name="pencil" size={14} />编辑
                  </Link>
                </div>
                <h2 style={{ marginTop: 12 }}>{selected.title}</h2>
              </div>
              <MarkdownView title={selected.title} content={selected.content} stripLeadingTitle emptyHint="_这篇笔记还是空的，点击右上角编辑。_" />
            </>
          ) : (
            <div className="empty">
              <Icon name="file" size={26} className="empty-icon" />
              <span className="empty-title">在左侧新建或选择一篇文章</span>
              <p>支持新建多级文件夹、新建文章、指定目录导入以及拖拽排序。</p>
            </div>
          )}
        </section>
      </div>

      <Dialog open={showImport} onOpenChange={(open) => { if (!importing) setShowImport(open) }}>
        <DialogContent className="study-dialog sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>导入 Markdown 到项目</DialogTitle>
            <DialogDescription>解析 frontmatter 中的 title、order、tags，并按相对路径自动创建多级子文件夹。</DialogDescription>
          </DialogHeader>
          <div className="modal-body">
            <label className="field">
              <span className="field-label">导入到目标文件夹</span>
              <select
                className="select"
                value={importParentId}
                onChange={(e) => setImportParentId(Number(e.target.value))}
                disabled={importing}
              >
                {folderOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>{opt.label}</option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="field-label">导入后的发布状态</span>
              <select
                className="select"
                value={importStatus}
                onChange={(e) => setImportStatus(e.target.value as 'draft' | 'published')}
                disabled={importing}
              >
                <option value="published">直接发布（访客可见）</option>
                <option value="draft">先存草稿（审阅后再发布）</option>
              </select>
            </label>

            <div
              className={`import-dropzone${importDragging ? ' is-dragging' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setImportDragging(true) }}
              onDragLeave={() => setImportDragging(false)}
              onDrop={handleImportDrop}
            >
              <Icon name="upload" size={20} />
              <p>{importDragging ? '松开以解析 Markdown 文件' : '将 .md 文件或整个文件夹拖到这里'}</p>
              <div className="import-dropzone-actions">
                <button type="button" className="btn btn-sm" onClick={() => filesRef.current?.click()} disabled={importing}>
                  <Icon name="file" size={14} />选择文件
                </button>
                <button type="button" className="btn btn-sm" onClick={() => folderRef.current?.click()} disabled={importing}>
                  <Icon name="folder" size={14} />选择文件夹
                </button>
              </div>
              <input
                ref={filesRef}
                type="file"
                multiple
                className="sr-only"
                tabIndex={-1}
                accept=".md,.markdown,.mdx,.txt"
                onChange={async (e) => {
                  const res = await readFromFileList(e.target.files)
                  e.target.value = ''
                  stageImportResult(res)
                }}
              />
              <input
                ref={(el) => {
                  folderRef.current = el
                  if (el) { el.setAttribute('webkitdirectory', ''); el.setAttribute('directory', '') }
                }}
                type="file"
                multiple
                className="sr-only"
                tabIndex={-1}
                onChange={async (e) => {
                  const res = await readFromFileList(e.target.files)
                  e.target.value = ''
                  stageImportResult(res)
                }}
              />
            </div>

            {pendingImport && (
              <div className="file-preview">
                <div className="file-preview-summary">
                  待导入 <strong>{pendingImport.files.length}</strong> 篇 Markdown · <strong>{countFolders(pendingImport.files)}</strong> 个子目录
                  {pendingImport.skipped > 0 ? ` · 跳过 ${pendingImport.skipped} 个其它文件` : ''}
                </div>
                {pendingImport.files.slice(0, 6).map((f) => <div key={f.path}>{f.path}</div>)}
                {pendingImport.files.length > 6 && <div className="dim">还有 {pendingImport.files.length - 6} 篇…</div>}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowImport(false)} disabled={importing}>取消</Button>
            <Button onClick={confirmImport} disabled={importing || !pendingImport?.files.length}>
              {importing ? '导入中…' : `确认导入${pendingImport ? `（${pendingImport.files.length} 篇）` : ''}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
