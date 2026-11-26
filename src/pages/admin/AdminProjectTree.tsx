import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api'
import { usePageMeta } from '../../site'
import { readFromFileList } from '../../lib/folder'
import ProjectFileTree from '../../components/ProjectFileTree'
import MarkdownView from '../../components/MarkdownView'
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
  const [showImport, setShowImport] = useState(false)
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
    const timer = window.setTimeout(() => setNotice(''), 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  const selected = nodes.find((n) => n.id === selectedId && n.kind === 'doc') || null

  const createNode = async (parentId: number, kind: 'folder' | 'doc', title: string) => {
    const sortOrder = Math.max(-1, ...nodes.filter((n) => n.parent_id === parentId).map((n) => n.sort_order)) + 1
    const { node } = await api.createNode({ projectId: project!.id, parentId, kind, title, sortOrder, status: kind === 'doc' ? 'draft' : 'published' })
    await load()
    if (kind === 'doc') navigate(`/edit?nodeId=${node.id}&from=${encodeURIComponent(`/admin/projects/${project!.id}`)}`)
    else setNotice(`已创建文件夹「${title}」`)
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

  const toggleNodePublish = async () => {
    if (!selected) return
    const next = selected.status === 'published' ? 'draft' : 'published'
    await api.updateNode(selected.id, { status: next })
    await load()
    setNotice(next === 'published' ? '已发布此篇' : '已转为草稿')
  }

  const readFiles = async (list: FileList | null) => {
    if (!list || !list.length || !project) return
    const result = await readFromFileList(list)
    if (!result.files.length) { setError('请选择 .md / .markdown / .mdx / .txt 文件'); return }
    try {
      const res = await api.importFiles({ projectId: project.id, parentId: 0, status: 'published', files: result.files })
      setShowImport(false)
      setError('')
      await load()
      setNotice(`已导入 ${res.imported} 篇笔记${res.duplicates ? `，跳过 ${res.duplicates} 篇重复路径` : ''}`)
    } catch (e: any) { setError(e.message) }
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
          <p>拖拽调整目录与文章顺序，点击右侧按钮直接编辑或发布。</p>
        </div>
        <div className="head-actions">
          <button type="button" className="btn btn-sm" onClick={() => setShowImport(true)}>
            <Icon name="upload" size={14} />导入 Markdown
          </button>
          <Link className="btn btn-sm" to={`/p/${project.id}${project.status === 'draft' ? '?preview=1' : ''}`}>
            <Icon name="book-open" size={14} />阅读视图
          </Link>
        </div>
      </div>

      {error && <div className="alert" role="alert"><Icon name="warning-circle" size={16} /><span>{error}</span></div>}
      {notice && <div className="alert alert-info" role="status"><Icon name="check-circle" size={16} /><span>{notice}</span></div>}

      <div className="admin-tree-workspace">
        <aside className="side-panel" aria-label="项目目录树">
          <ProjectFileTree
            nodes={nodes}
            selectedId={selectedId}
            owner
            onSelect={(node) => setSelectedId(node.id)}
            onCreate={createNode}
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
                  <span className={`badge ${selected.status === 'published' ? 'badge-published' : 'badge-draft'}`}>
                    {selected.status === 'published' ? '已发布' : '草稿'}
                  </span>
                  <span className="dim" style={{ fontSize: 12 }}>更新于 {String(selected.updated_at).slice(0, 10)}</span>
                  <div className="spacer" />
                  <button type="button" className="btn btn-sm" onClick={toggleNodePublish}>
                    {selected.status === 'published' ? '转为草稿' : '发布此篇'}
                  </button>
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
              <p>支持新建目录、新建文章以及拖拽排序。</p>
            </div>
          )}
        </section>
      </div>

      <Dialog open={showImport} onOpenChange={setShowImport}>
        <DialogContent className="study-dialog sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>导入 Markdown</DialogTitle>
            <DialogDescription>解析 frontmatter 里的 title、order、tags，按相对路径重建目录。</DialogDescription>
          </DialogHeader>
          <div className="modal-body">
            <label className="field">
              <span className="field-label">选择文件</span>
              <input className="input" type="file" multiple accept=".md,.markdown,.mdx,.txt" onChange={(e) => { readFiles(e.target.files); e.target.value = '' }} />
            </label>
            <label className="field">
              <span className="field-label">或者选择整个文件夹</span>
              <input
                className="input"
                ref={(el) => { folderRef.current = el; if (el) { el.setAttribute('webkitdirectory', ''); el.setAttribute('directory', '') } }}
                type="file"
                multiple
                onChange={(e) => { readFiles(e.target.files); e.target.value = '' }}
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowImport(false)}>关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
