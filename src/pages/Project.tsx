import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { usePageMeta, useSite, useStructuredData } from '../site'
import { readFromFileList } from '../lib/folder'
import MarkdownView from '../components/MarkdownView'
import Icon from '../components/Icon'
import type { NoteNode, Project as ProjectType } from '../types'

interface TreeNode extends NoteNode {
  children: TreeNode[]
}

function buildTree(nodes: NoteNode[]): TreeNode[] {
  const map = new Map<number, TreeNode>()
  nodes.forEach((node) => map.set(node.id, { ...node, children: [] }))
  const roots: TreeNode[] = []
  nodes.forEach((node) => {
    const item = map.get(node.id)!
    if (node.parent_id && map.has(node.parent_id)) map.get(node.parent_id)!.children.push(item)
    else roots.push(item)
  })
  return roots
}

function headingId(text: string) {
  return text.trim().toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5\s-]/g, '')
    .replace(/\s+/g, '-')
}

function TreeItem({ node, depth, selectedId, onSelect, owner, onAdd, onDelete }: {
  node: TreeNode
  depth: number
  selectedId: string | null
  onSelect: (id: number) => void
  owner: boolean
  onAdd: (parentId: number, kind: 'folder' | 'doc') => void
  onDelete: (node: NoteNode) => void
}) {
  const [open, setOpen] = useState(true)
  const isFolder = node.kind === 'folder'
  const active = selectedId === String(node.id)
  return (
    <div>
      <div
        className={`tree-row ${active ? 'active' : ''}`}
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => (isFolder ? setOpen(!open) : onSelect(node.id))}
        role="button"
        tabIndex={0}
        aria-current={active ? 'page' : undefined}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return
          event.preventDefault()
          if (isFolder) setOpen(!open)
          else onSelect(node.id)
        }}
      >
        <span className="tree-icon">
          <Icon name={isFolder ? (open ? 'folder-open' : 'folder') : 'file'} size={14} />
        </span>
        <span className="tree-title">{node.title}</span>
        {node.status === 'draft' && <span className="tree-draft" title="草稿" />}
        {owner && (
          <span className="tree-actions">
            {isFolder && (
              <button
                title="在此新建笔记"
                aria-label={`在 ${node.title} 下新建笔记`}
                onClick={(event) => { event.stopPropagation(); onAdd(node.id, 'doc') }}
              >
                <Icon name="plus" size={13} />
              </button>
            )}
            <button
              className="is-danger"
              title="删除"
              aria-label={`删除 ${node.title}`}
              onClick={(event) => { event.stopPropagation(); onDelete(node) }}
            >
              <Icon name="x" size={13} />
            </button>
          </span>
        )}
      </div>
      {isFolder && open && node.children.map((child) => (
        <TreeItem
          key={child.id}
          node={child}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
          owner={owner}
          onAdd={onAdd}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}

export default function Project() {
  const { id, nodeId } = useParams()
  const { user } = useAuth()
  const site = useSite()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // 兼容旧的 ?node= 链接，新链接统一走 /p/:id/n/:nodeId
  const selectedId = nodeId || searchParams.get('node')

  const [project, setProject] = useState<ProjectType | null>(null)
  const [nodes, setNodes] = useState<NoteNode[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showImport, setShowImport] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [activeTag, setActiveTag] = useState('')
  const [activeHeading, setActiveHeading] = useState('')
  const [formName, setFormName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formSort, setFormSort] = useState(0)
  const [notice, setNotice] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const folderRef = useRef<HTMLInputElement | null>(null)

  const load = useCallback(() => api.getProject(id!).then((res) => {
    setProject(res.project)
    setNodes(res.nodes)
  }), [id])

  useEffect(() => {
    setLoading(true)
    setError('')
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [load])

  // 标签面板只统计「本项目」的标签。
  // 之前直接用了 /api/tags（全站聚合），打开一个空项目也会列出一堆别的项目的标签，
  // 点进去还会把目录树过滤成空。
  const tags = useMemo(() => {
    const counter = new Map<string, number>()
    nodes.forEach((node) => {
      if (node.kind !== 'doc') return
      node.tags.split(',').map((tag) => tag.trim()).filter(Boolean).forEach((tag) => {
        counter.set(tag, (counter.get(tag) || 0) + 1)
      })
    })
    return [...counter.entries()]
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
  }, [nodes])

  const sourceTree = useMemo(() => buildTree(nodes), [nodes])
  const selected = nodes.find((n) => n.id === Number(selectedId) && n.kind === 'doc') || null

  const tree = useMemo(() => {
    if (!activeTag) return sourceTree
    const keep = new Set<number>()
    const mark = (node: NoteNode) => {
      keep.add(node.id)
      if (node.parent_id) {
        const parent = nodes.find((n) => n.id === node.parent_id)
        if (parent) mark(parent)
      }
    }
    nodes.forEach((node) => {
      if (node.kind === 'doc' && node.tags.split(',').map((t) => t.trim()).includes(activeTag)) mark(node)
    })
    const filter = (items: TreeNode[]): TreeNode[] => items
      .filter((item) => keep.has(item.id))
      .map((item) => ({ ...item, children: filter(item.children) }))
    return filter(sourceTree)
  }, [activeTag, nodes, sourceTree])

  const flatDocs = useMemo(() => {
    const result: NoteNode[] = []
    const walk = (items: TreeNode[]) => items.forEach((item) => {
      if (item.kind === 'doc') result.push(item)
      else walk(item.children)
    })
    walk(sourceTree)
    return result
  }, [sourceTree])

  const currentIndex = selected ? flatDocs.findIndex((doc) => doc.id === selected.id) : -1
  const prevDoc = currentIndex > 0 ? flatDocs[currentIndex - 1] : null
  const nextDoc = currentIndex >= 0 && currentIndex < flatDocs.length - 1 ? flatDocs[currentIndex + 1] : null

  const readingMinutes = useMemo(() => {
    if (!selected) return 0
    const text = selected.content || ''
    const cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length
    const words = text.replace(/[\u4e00-\u9fa5]/g, ' ').split(/\s+/).filter(Boolean).length
    return Math.max(1, Math.round(cjk / 400 + words / 200))
  }, [selected])

  const plainExcerpt = useMemo(() => {
    if (!selected) return project?.description || ''
    return selected.content
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
      .replace(/[#>*`_~|-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 150)
  }, [selected, project])

  usePageMeta(selected ? selected.title : project?.name, plainExcerpt)

  const jsonLd = useMemo(() => {
    if (!selected || !project) return null
    return {
      '@context': 'https://schema.org',
      '@type': 'BlogPosting',
      headline: selected.title,
      description: plainExcerpt,
      datePublished: selected.created_at,
      dateModified: selected.updated_at,
      articleSection: project.name,
      keywords: selected.tags,
      author: { '@type': 'Organization', name: site.name },
      mainEntityOfPage: `${window.location.origin}${window.location.pathname}`,
    }
  }, [selected, project, plainExcerpt, site.name])
  useStructuredData(jsonLd)

  useEffect(() => {
    if (!selectedId && nodes.length) {
      const first = nodes.find((n) => n.kind === 'doc')
      if (first) navigate(`/p/${id}/n/${first.id}`, { replace: true })
    }
  }, [nodes, selectedId, id, navigate])

  const owner = !!(user && project && user.id === project.owner_id)

  const headings = useMemo(() => {
    if (!selected) return [] as { level: number; text: string; id: string }[]
    const result: { level: number; text: string; id: string }[] = []
    let inCode = false
    for (const line of selected.content.split('\n')) {
      if (line.trim().startsWith('```')) { inCode = !inCode; continue }
      if (inCode) continue
      const match = line.match(/^(#{1,3})\s+(.*)$/)
      if (match) {
        const text = match[2].replace(/\*\*|`|\[|\]\([^)]*\)/g, '').trim()
        result.push({ level: match[1].length, text, id: headingId(text) })
      }
    }
    return result
  }, [selected])

  // 目录高亮用 IntersectionObserver，不用 scroll 事件
  useEffect(() => {
    if (!headings.length) { setActiveHeading(''); return }
    const targets = headings
      .map((heading) => document.getElementById(heading.id))
      .filter((node): node is HTMLElement => Boolean(node))
    if (!targets.length) return

    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (visible.length) setActiveHeading(visible[0].target.id)
    }, { rootMargin: '-76px 0px -66% 0px', threshold: [0, 1] })

    targets.forEach((target) => observer.observe(target))
    return () => observer.disconnect()
  }, [headings, selected])

  // 切换笔记时回到正文顶部
  useEffect(() => {
    if (!selected) return
    window.scrollTo({ top: 0, behavior: 'auto' })
    setSidebarOpen(false)
  }, [selected?.id])

  const addNode = (parentId: number, kind: 'folder' | 'doc') => {
    navigate(`/edit?projectId=${project!.id}&parentId=${parentId}&kind=${kind}`)
  }

  const removeNode = async (node: NoteNode) => {
    if (!window.confirm(`删除「${node.title}」${node.kind === 'folder' ? '及其全部子内容' : ''}？可以在回收站里恢复。`)) return
    try {
      await api.deleteNode(node.id)
      if (selectedId === String(node.id)) navigate(`/p/${project!.id}`, { replace: true })
      await load()
    } catch (e: any) { setError(e.message) }
  }

  const togglePublish = async () => {
    if (!project) return
    try {
      await api.updateProject(project.id, { status: project.status === 'published' ? 'draft' : 'published' })
      await load()
      setNotice(project.status === 'published' ? '项目已转为草稿' : '项目已发布')
    } catch (e: any) { setError(e.message) }
  }

  const toggleNodePublish = async () => {
    if (!selected) return
    try {
      await api.updateNode(selected.id, { status: selected.status === 'published' ? 'draft' : 'published' })
      await load()
      setNotice(selected.status === 'published' ? '这篇已转为草稿' : '这篇已发布')
    } catch (e: any) { setError(e.message) }
  }

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  const breadcrumb = useMemo(() => {
    if (!selected) return [] as NoteNode[]
    const chain: NoteNode[] = []
    let current: NoteNode | undefined = selected
    const seen = new Set<number>()
    while (current && !seen.has(current.id)) {
      seen.add(current.id)
      chain.unshift(current)
      current = current.parent_id ? nodes.find((n) => n.id === current!.parent_id) : undefined
    }
    return chain
  }, [selected, nodes])

  const exportMarkdown = () => {
    if (!selected || !project) return
    const frontMatter = `---\ntitle: ${selected.title}\ntags: [${selected.tags}]\norder: ${selected.sort_order}\nstatus: ${selected.status}\n---\n\n`
    const blob = new Blob([frontMatter + selected.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${selected.title.replace(/[\\/:*?"<>|]/g, '_')}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const openSettings = () => {
    if (!project) return
    setFormName(project.name)
    setFormDescription(project.description)
    setFormSort(project.sort_order)
    setShowSettings(true)
  }

  const saveSettings = async () => {
    if (!project) return
    try {
      await api.updateProject(project.id, {
        name: formName,
        description: formDescription,
        sort_order: formSort,
      })
      setShowSettings(false)
      await load()
      setNotice('项目信息已保存')
    } catch (e: any) { setError(e.message) }
  }

  const removeProject = async () => {
    if (!project) return
    if (!window.confirm(`确定删除项目「${project.name}」及其全部笔记？此操作不可撤销。`)) return
    try {
      await api.deleteProject(project.id)
      navigate('/')
    } catch (e: any) { setError(e.message) }
  }

  const readFiles = async (list: FileList | null) => {
    if (!list || !list.length || !project) return
    const result = await readFromFileList(list)
    if (!result.files.length) { setError('请选择 .md / .markdown / .mdx / .txt 文件'); return }
    try {
      const res = await api.importFiles({
        projectId: project.id,
        parentId: 0,
        status: 'published',
        files: result.files,
      })
      setShowImport(false)
      setError('')
      await load()
      const skipped = result.skipped + (res.skipped || 0)
      setNotice(`已导入 ${res.imported} 篇笔记${skipped ? `，跳过 ${skipped} 个非笔记文件` : ''}`)
    } catch (e: any) { setError(e.message) }
  }

  if (loading) {
    return (
      <div className="project-page">
        <div className="project-head">
          <div style={{ width: '100%', maxWidth: 520 }}>
            <div className="skeleton" style={{ height: 12, width: 90, marginBottom: 14 }} />
            <div className="skeleton" style={{ height: 30, width: '62%' }} />
            <div className="skeleton" style={{ height: 12, width: '88%', marginTop: 14 }} />
          </div>
        </div>
        <div className="workspace">
          <aside className="side-panel">
            {[0, 1, 2, 3, 4].map((row) => (
              <div className="skeleton" key={row} style={{ height: 26, marginBottom: 8, width: `${92 - row * 6}%` }} />
            ))}
          </aside>
          <div className="article">
            <div className="skeleton" style={{ height: 13, width: 120, marginBottom: 16 }} />
            <div className="skeleton" style={{ height: 28, width: '72%', marginBottom: 24 }} />
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <div className="skeleton" key={row} style={{ height: 12, marginBottom: 12, width: `${94 - (row % 3) * 9}%` }} />
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (error && !project) {
    return (
      <div className="page">
        <div className="empty">
          <Icon name="warning-circle" size={28} className="empty-icon" />
          <span className="empty-title">打不开这个项目</span>
          <p>{error}</p>
          <Link className="btn" to="/">回到项目列表</Link>
        </div>
      </div>
    )
  }

  if (!project) {
    return (
      <div className="page">
        <div className="empty">
          <Icon name="folder" size={28} className="empty-icon" />
          <span className="empty-title">项目不存在</span>
          <p>它可能已被删除，或者还没有发布。</p>
          <Link className="btn" to="/">回到项目列表</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="project-page">
      <div className="project-head">
        <div className="project-head-main">
          <Link to="/" className="back-link"><Icon name="arrow-left" size={13} />全部项目</Link>
          {/* 选中笔记时页面主标题是笔记标题，项目名降级成普通文字，
              否则一页里会有两个 h1，读屏软件和搜索引擎都分不清谁是主标题 */}
          {selected
            ? <div className="project-name">{project.name}</div>
            : <h1>{project.name}</h1>}
          {project.description && <p className="project-desc">{project.description}</p>}
          <div className="project-facts">
            <span className="fact">
              <Icon name="file" size={13} />
              {project.doc_count ?? nodes.filter((node) => node.kind === 'doc').length} 篇笔记
            </span>
            <span className="fact">
              <Icon name="folder" size={13} />
              {project.folder_count ?? nodes.filter((node) => node.kind === 'folder').length} 个目录
            </span>
            <span className="fact">
              <Icon name="clock" size={13} />
              更新于 {String(project.updated_at).slice(0, 10)}
            </span>
            <span className="fact">
              <span className={`badge ${project.status === 'published' ? 'badge-published' : 'badge-draft'}`}>
                {project.status === 'published' ? '已发布' : '草稿'}
              </span>
            </span>
          </div>
        </div>
        <div className="head-actions">
          <button
            className="btn btn-sm nav-toggle"
            onClick={() => setSidebarOpen((open) => !open)}
            style={{ display: 'inline-flex' }}
            aria-expanded={sidebarOpen}
          >
            <Icon name="list" size={15} />目录
          </button>
          {owner && (
            <>
              <button className="btn" onClick={() => addNode(0, 'doc')}>
                <Icon name="plus" size={15} />新建笔记
              </button>
              <button className="btn" onClick={() => setShowImport(true)}>
                <Icon name="upload" size={15} />导入
              </button>
              <button className="btn" onClick={togglePublish}>
                {project.status === 'published' ? '转为草稿' : '发布项目'}
              </button>
              <button className="icon-btn" onClick={openSettings} aria-label="项目设置" title="项目设置">
                <Icon name="gear" size={17} />
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
          <button className="link-btn" style={{ marginLeft: 'auto', fontSize: 12 }} onClick={() => setError('')}>关闭</button>
        </div>
      )}
      {notice && (
        <div className="alert alert-info">
          <Icon name="check-circle" size={16} />
          <span>{notice}</span>
        </div>
      )}

      <div className="workspace">
        <aside className="side-panel">
          <div className="tag-panel">
            <div className="panel-label">
              <span>标签</span>
              {activeTag && (
                <button className="link-btn" style={{ fontSize: 11 }} onClick={() => setActiveTag('')}>重置</button>
              )}
            </div>
            <div className="tag-chips">
              <button className={`chip ${activeTag === '' ? 'on' : ''}`} onClick={() => setActiveTag('')}>全部</button>
              {tags.map((tag) => (
                <button
                  key={tag.tag}
                  className={`chip ${activeTag === tag.tag ? 'on' : ''}`}
                  onClick={() => setActiveTag(activeTag === tag.tag ? '' : tag.tag)}
                >
                  {tag.tag}<span className="chip-count">{tag.count}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="panel-label">
            <span>目录</span>
            <span className="count">{flatDocs.length}</span>
          </div>
          <div className="tree-scroll">
            {tree.length ? tree.map((node) => (
              <TreeItem
                key={node.id}
                node={node}
                depth={0}
                selectedId={selectedId}
                onSelect={(targetId) => navigate(`/p/${project.id}/n/${targetId}`)}
                owner={owner}
                onAdd={addNode}
                onDelete={removeNode}
              />
            )) : <div className="dim" style={{ padding: '10px 8px', fontSize: 12.5 }}>还没有内容</div>}
          </div>

          {owner && (
            <div className="side-foot">
              <button className="link-btn" style={{ fontSize: 12.5 }} onClick={() => addNode(0, 'folder')}>
                <Icon name="plus" size={13} />新建文件夹
              </button>
            </div>
          )}
        </aside>

        <article className="article">
          {selected ? (
            <>
              <div className="article-head">
                <div className="breadcrumb">
                  <Link to={`/p/${project.id}`}>{project.name}</Link>
                  {breadcrumb.slice(1).map((crumb) => (
                    <span key={crumb.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <span className="sep">/</span>
                      <span>{crumb.title}</span>
                    </span>
                  ))}
                </div>
                <h1>{selected.title}</h1>
                <div className="article-meta">
                  <span className="meta-item">更新于 {String(selected.updated_at).slice(0, 10)}</span>
                  <span className="meta-item">约 {readingMinutes} 分钟</span>
                  {selected.tags && selected.tags.split(',').filter(Boolean).length > 0 && (
                    <span className="meta-item">标签 {selected.tags}</span>
                  )}
                  {selected.status === 'draft' && (
                    <span className="meta-item"><span className="badge badge-draft">草稿</span></span>
                  )}
                </div>
                <div className="article-bar">
                  <button className="btn btn-sm btn-quiet" onClick={exportMarkdown}>
                    <Icon name="upload" size={14} style={{ transform: 'rotate(180deg)' }} />导出 MD
                  </button>
                  <div className="spacer" />
                  {owner && (
                    <>
                      <button className="btn btn-sm" onClick={toggleNodePublish}>
                        {selected.status === 'published' ? '转为草稿' : '发布此篇'}
                      </button>
                      <button className="btn btn-sm btn-primary" onClick={() => navigate(`/edit?nodeId=${selected.id}`)}>
                        <Icon name="pencil" size={14} />编辑
                      </button>
                    </>
                  )}
                </div>
              </div>
              <MarkdownView
                title={selected.title}
                content={selected.content}
                stripLeadingTitle
                emptyHint="_这篇笔记还是空的，点编辑写点什么。_"
              />
              <nav className="article-nav" aria-label="上下篇">
                {prevDoc ? (
                  <Link to={`/p/${project.id}/n/${prevDoc.id}`} className="nav-item prev">
                    <span className="nav-label"><Icon name="arrow-left" size={12} />上一篇</span>
                    <span className="nav-title">{prevDoc.title}</span>
                  </Link>
                ) : <span className="nav-placeholder" aria-hidden="true" />}
                {nextDoc ? (
                  <Link to={`/p/${project.id}/n/${nextDoc.id}`} className="nav-item next">
                    <span className="nav-label">下一篇<Icon name="arrow-up-right" size={12} /></span>
                    <span className="nav-title">{nextDoc.title}</span>
                  </Link>
                ) : <span className="nav-placeholder" aria-hidden="true" />}
              </nav>
            </>
          ) : (
            <div className="empty" style={{ border: 0, background: 'transparent' }}>
              <Icon name="book-open" size={28} className="empty-icon" />
              <span className="empty-title">{nodes.length ? '选一篇开始读' : '这个项目还没有笔记'}</span>
              <p>
                {nodes.length
                  ? '从左侧目录里点一篇笔记，正文会显示在这里。'
                  : owner
                    ? '先写第一篇笔记，或者把一个 Markdown 文件夹导入进来。'
                    : '作者还没有发布内容。'}
              </p>
              {owner && !nodes.length && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-primary btn-sm" onClick={() => addNode(0, 'doc')}>新建笔记</button>
                  <button className="btn btn-sm" onClick={() => setShowImport(true)}>导入 Markdown</button>
                </div>
              )}
            </div>
          )}
        </article>

        <aside className="toc-panel side-panel">
          <div className="panel-label">
            <span>本页目录</span>
            <span className="count">{headings.length}</span>
          </div>
          <div className="tree-scroll">
            {headings.length ? headings.map((heading, index) => (
              <button
                key={`${heading.id}-${index}`}
                className={`toc-item level-${heading.level} ${activeHeading === heading.id ? 'active' : ''}`}
                onClick={() => document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
              >
                {heading.text}
              </button>
            )) : <div className="dim" style={{ padding: '8px', fontSize: 12 }}>这篇没有标题层级</div>}
          </div>
        </aside>
      </div>

      {showSettings && (
        <div className="modal-backdrop" onClick={() => setShowSettings(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="项目设置" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>项目设置</h2>
                <p>改名、改描述、调整排序，或者删除整个项目。</p>
              </div>
              <button className="icon-btn" onClick={() => setShowSettings(false)} aria-label="关闭">
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="modal-body">
              <label className="field">
                <span className="field-label">项目名称</span>
                <input className="input" value={formName} onChange={(e) => setFormName(e.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">项目描述</span>
                <textarea className="textarea" value={formDescription} onChange={(e) => setFormDescription(e.target.value)} rows={3} />
              </label>
              <label className="field">
                <span className="field-label">排序</span>
                <input className="input" type="number" value={formSort} onChange={(e) => setFormSort(Number(e.target.value))} />
                <span className="field-hint">数字小的排在前面。</span>
              </label>
            </div>
            <div className="modal-actions">
              <button className="btn btn-danger btn-sm" onClick={removeProject}>
                <Icon name="trash" size={14} />删除项目
              </button>
              <div className="spacer" />
              <button className="btn" onClick={() => setShowSettings(false)}>取消</button>
              <button className="btn btn-primary" onClick={saveSettings}>保存</button>
            </div>
          </div>
        </div>
      )}

      {showImport && (
        <div className="modal-backdrop" onClick={() => setShowImport(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="导入 Markdown" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>导入 Markdown</h2>
                <p>解析 frontmatter 里的 title、order、tags，按相对路径重建目录。</p>
              </div>
              <button className="icon-btn" onClick={() => setShowImport(false)} aria-label="关闭">
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="modal-body">
              <label className="field">
                <span className="field-label">选择文件</span>
                <input
                  className="input"
                  type="file"
                  multiple
                  accept=".md,.markdown,.mdx,.txt"
                  onChange={(e) => { readFiles(e.target.files); e.target.value = '' }}
                />
                <span className="field-hint">单次最多 300 个文件，单个不超过 2MB。</span>
              </label>
              <label className="field">
                <span className="field-label">或者选择整个文件夹</span>
                <input
                  className="input"
                  ref={(element) => {
                    folderRef.current = element
                    if (element) {
                      element.setAttribute('webkitdirectory', '')
                      element.setAttribute('directory', '')
                    }
                  }}
                  type="file"
                  multiple
                  onChange={(e) => { readFiles(e.target.files); e.target.value = '' }}
                />
                <span className="field-hint">会自动跳过 node_modules、隐藏目录与非 Markdown 文件。</span>
              </label>
            </div>
            <div className="modal-actions">
              <div className="spacer" />
              <button className="btn" onClick={() => setShowImport(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
