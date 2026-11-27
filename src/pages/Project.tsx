import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { usePageMeta, useSite, useStructuredData } from '../site'
import MarkdownView from '../components/MarkdownView'
import ProjectFileTree from '../components/ProjectFileTree'
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

export default function Project() {
  const { id, nodeId } = useParams()
  const { user } = useAuth()
  const site = useSite()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const isAdmin = user?.username === 'coustea'
  const preview = isAdmin && searchParams.get('preview') === '1'
  const previewSuffix = preview ? '?preview=1' : ''

  const [project, setProject] = useState<ProjectType | null>(null)
  const [nodes, setNodes] = useState<NoteNode[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [activeTag, setActiveTag] = useState('')
  const [activeHeading, setActiveHeading] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [tocCompact, setTocCompact] = useState(true)
  const [showBackTop, setShowBackTop] = useState(false)

  const load = useCallback(() => api.getProject(id!, !preview).then((res) => {
    setProject(res.project)
    setNodes(res.nodes)
  }), [id, preview])

  useEffect(() => {
    setLoading(true)
    setError('')
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [load])

  const tags = useMemo(() => {
    const counter = new Map<string, number>()
    nodes.forEach((node) => {
      if (node.kind !== 'doc') return
      node.tags.split(',').map((t) => t.trim()).filter(Boolean).forEach((t) => counter.set(t, (counter.get(t) || 0) + 1))
    })
    return [...counter.entries()].map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
  }, [nodes])

  const sourceTree = useMemo(() => buildTree(nodes), [nodes])
  const selected = nodes.find((n) => n.id === Number(nodeId) && n.kind === 'doc') || null

  const visibleNodes = useMemo(() => {
    if (!activeTag) return nodes
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
    return nodes.filter((node) => keep.has(node.id))
  }, [activeTag, nodes])

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
    if (!nodeId && nodes.length) {
      const first = nodes.find((n) => n.kind === 'doc')
      if (first) navigate(`/p/${id}/n/${first.id}${previewSuffix}`, { replace: true })
    }
  }, [nodes, nodeId, id, navigate, previewSuffix])

  const headings = useMemo(() => {
    if (!selected) return [] as { level: number; text: string; id: string }[]
    const result: { level: number; text: string; id: string }[] = []
    let inCode = false
    for (const [index, line] of selected.content.trimStart().split('\n').entries()) {
      if (line.trim().startsWith('```')) { inCode = !inCode; continue }
      if (inCode) continue
      const match = line.match(/^(#{1,3})\s+(.*)$/)
      if (match) {
        const text = match[2].replace(/\*\*|`|\[|\]\([^)]*\)/g, '').trim()
        if (index === 0 && match[1].length === 1 && headingId(text) === headingId(selected.title)) continue
        result.push({ level: match[1].length, text, id: headingId(text) })
      }
    }
    return result
  }, [selected])

  const hasDeepHeadings = useMemo(() => headings.some((h) => h.level >= 3), [headings])
  const visibleHeadings = useMemo(
    () => (headings.length > 30 && tocCompact && hasDeepHeadings ? headings.filter((h) => h.level <= 2) : headings),
    [headings, tocCompact, hasDeepHeadings],
  )

  useEffect(() => {
    setTocCompact(headings.length > 30)
  }, [selected?.id, headings.length])

  useEffect(() => {
    if (!activeHeading) return
    const activeEl = document.querySelector<HTMLElement>(`.toc-panel [data-toc-id="${CSS.escape(activeHeading)}"]`)
    const scroller = activeEl?.closest<HTMLElement>('.tree-scroll')
    if (!activeEl || !scroller) return
    const targetTop = activeEl.offsetTop - scroller.clientHeight / 2 + activeEl.clientHeight / 2
    scroller.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
  }, [activeHeading])

  useEffect(() => {
    const targets = headings.map((h) => document.getElementById(h.id)).filter((el): el is HTMLElement => Boolean(el))
    if (!headings.length) setActiveHeading('')
    else if (!targets.length) setActiveHeading(headings[0].id)

    let raf = 0
    const sync = () => {
      raf = 0
      setShowBackTop(window.scrollY > 320)
      if (!targets.length) return
      const scrollBottom = window.scrollY + window.innerHeight
      const docHeight = document.documentElement.scrollHeight
      if (docHeight - scrollBottom <= 24) {
        setActiveHeading(targets[targets.length - 1].id)
        return
      }
      let current = targets[0].id
      for (const el of targets) {
        if (el.getBoundingClientRect().top <= 120) current = el.id
        else break
      }
      setActiveHeading(current)
    }
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(sync) }
    sync()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [headings, selected])

  useEffect(() => {
    if (!selected) return
    window.scrollTo({ top: 0, behavior: 'auto' })
    setSidebarOpen(false)
  }, [selected?.id])

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
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="page">
        <div className="empty">
          <Icon name="folder" size={28} className="empty-icon" />
          <span className="empty-title">{error ? '打不开这个专题' : '专题不存在'}</span>
          <p>{error || '它可能已被删除，或者还没有发布。'}</p>
          <Link className="btn" to="/">回到阅读首页</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="project-page">
      {selected && <div className="reading-progress" aria-hidden="true" />}
      {preview && (
        <div className="alert alert-info" role="status">
          <Icon name="book-open" size={16} />
          <span>草稿预览模式 · 当前包含未发布内容，访客不可见</span>
          <Link className="link-btn" style={{ marginLeft: 'auto', fontSize: 12.5 }} to="/admin">返回文章管理</Link>
        </div>
      )}

      <div className={`project-head ${selected ? 'is-reading' : ''}`}>
        <div className="project-head-main">
          <Link to="/" className="back-link"><Icon name="arrow-left" size={13} />笔记首页</Link>
          {selected ? <div className="project-name">{project.name}</div> : <h1>{project.name}</h1>}
          {project.description && <p className="project-desc">{project.description}</p>}
          <div className="project-facts">
            <span className="fact"><Icon name="file" size={13} />{project.doc_count ?? nodes.filter((n) => n.kind === 'doc').length} 篇笔记</span>
            <span className="fact"><Icon name="folder" size={13} />{project.folder_count ?? nodes.filter((n) => n.kind === 'folder').length} 个目录</span>
            <span className="fact"><Icon name="clock" size={13} />更新于 {String(project.updated_at).slice(0, 10)}</span>
          </div>
        </div>
        <div className="head-actions">
          <button
            type="button"
            className="btn btn-sm nav-toggle"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-expanded={sidebarOpen}
            aria-controls="project-navigation"
          >
            <Icon name="list" size={15} />目录
          </button>
          {isAdmin && (
            <Link className="btn btn-sm" to={`/admin/projects/${project.id}`}>
              <Icon name="gear" size={14} />管理目录
            </Link>
          )}
        </div>
      </div>

      <div className="workspace">
        <aside id="project-navigation" className={`side-panel project-nav ${sidebarOpen ? 'is-open' : ''}`} aria-label="专题目录">
          {tags.length > 0 && (
            <div className="tag-panel">
              <div className="panel-label">
                <span>标签</span>
                {activeTag && <button type="button" className="link-btn" style={{ fontSize: 11 }} onClick={() => setActiveTag('')}>重置</button>}
              </div>
              <div className="tag-chips">
                <button type="button" className={`chip ${activeTag === '' ? 'on' : ''}`} onClick={() => setActiveTag('')}>全部</button>
                {tags.map((item) => (
                  <button
                    key={item.tag}
                    type="button"
                    className={`chip ${activeTag === item.tag ? 'on' : ''}`}
                    onClick={() => setActiveTag(activeTag === item.tag ? '' : item.tag)}
                  >
                    {item.tag}<span className="chip-count">{item.count}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <ProjectFileTree
            nodes={visibleNodes}
            selectedId={selected ? selected.id : null}
            owner={false}
            onSelect={(node) => navigate(`/p/${project.id}/n/${node.id}${previewSuffix}`)}
            onCreate={async () => {}}
            onMove={async () => {}}
            onDelete={async () => {}}
            onEdit={() => {}}
          />
        </aside>

        <article className="article">
          {selected ? (
            <>
              <div className="article-head">
                {breadcrumb.length > 1 && (
                  <div className="breadcrumb">
                    <Link to={`/p/${project.id}${previewSuffix}`}>{project.name}</Link>
                    {breadcrumb.slice(1).map((crumb) => (
                      <span key={crumb.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                        <span className="sep">/</span>
                        <span>{crumb.title}</span>
                      </span>
                    ))}
                  </div>
                )}
                <h1>{selected.title}</h1>
                <div className="article-meta">
                  <span className="meta-item">更新于 {String(selected.updated_at).slice(0, 10)}</span>
                  <span className="meta-item">约 {readingMinutes} 分钟</span>
                  {selected.tags.split(',').map((t) => t.trim()).filter(Boolean).map((tag) => (
                    <Link key={tag} className="meta-item" to={`/search?q=${encodeURIComponent(tag)}`}>#{tag}</Link>
                  ))}
                  {selected.status === 'draft' && (
                    <span className="meta-item"><span className="badge badge-draft">草稿</span></span>
                  )}
                </div>
                <div className="article-bar">
                  <button type="button" className="btn btn-sm btn-quiet" onClick={exportMarkdown}>
                    <Icon name="upload" size={14} style={{ transform: 'rotate(180deg)' }} />导出 MD
                  </button>
                  <div className="spacer" />
                  {isAdmin && (
                    <Link className="btn btn-sm" to={`/edit?nodeId=${selected.id}`}>
                      <Icon name="pencil" size={14} />编辑此篇
                    </Link>
                  )}
                </div>
                {visibleHeadings.length > 0 && (
                  <details className="mobile-toc">
                    <summary>
                      <span>本页目录</span>
                      <span className="count">{visibleHeadings.length}{visibleHeadings.length !== headings.length ? `/${headings.length}` : ''}</span>
                    </summary>
                    <div className="mobile-toc-list">
                      {visibleHeadings.map((heading, index) => (
                        <button
                          key={`m-${heading.id}-${index}`}
                          type="button"
                          className={`toc-item level-${heading.level} ${activeHeading === heading.id ? 'active' : ''}`}
                          onClick={(e) => {
                            const details = e.currentTarget.closest('details')
                            if (details) details.open = false
                            setActiveHeading(heading.id)
                            document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                          }}
                        >
                          {heading.text}
                        </button>
                      ))}
                    </div>
                  </details>
                )}
              </div>
              <MarkdownView
                title={selected.title}
                content={selected.content}
                stripLeadingTitle
                emptyHint="_这篇笔记暂无正文。_"
              />
              <nav className="article-nav" aria-label="上下篇">
                {prevDoc ? (
                  <Link to={`/p/${project.id}/n/${prevDoc.id}${previewSuffix}`} className="nav-item prev">
                    <span className="nav-label"><Icon name="arrow-left" size={12} />上一篇</span>
                    <span className="nav-title">{prevDoc.title}</span>
                  </Link>
                ) : <span className="nav-placeholder" aria-hidden="true" />}
                {nextDoc ? (
                  <Link to={`/p/${project.id}/n/${nextDoc.id}${previewSuffix}`} className="nav-item next">
                    <span className="nav-label">下一篇<Icon name="arrow-up-right" size={12} /></span>
                    <span className="nav-title">{nextDoc.title}</span>
                  </Link>
                ) : <span className="nav-placeholder" aria-hidden="true" />}
              </nav>
              <button
                type="button"
                className={`floating-top${showBackTop ? ' is-visible' : ''}`}
                aria-label="回到顶部"
                title="回到顶部"
                tabIndex={showBackTop ? 0 : -1}
                onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              >
                <Icon name="caret-up" size={18} />
              </button>
            </>
          ) : (
            <div className="empty" style={{ border: 0, background: 'transparent' }}>
              <Icon name="book-open" size={28} className="empty-icon" />
              <span className="empty-title">{nodes.length ? '选一篇开始读' : '这个专题还没有笔记'}</span>
              <p>{nodes.length ? '从左侧目录里点一篇笔记，正文会显示在这里。' : '站长还没有发布内容。'}</p>
            </div>
          )}
        </article>

        <aside className="toc-panel side-panel" aria-label="本页目录">
          <div className="panel-label">
            <span>本页目录</span>
            <span className="toc-label-right">
              {headings.length > 30 && hasDeepHeadings && (
                <button type="button" className="link-btn" style={{ fontSize: 11 }} onClick={() => setTocCompact((v) => !v)}>
                  {tocCompact ? '展开全部' : '只看大纲'}
                </button>
              )}
              <span className="count">{visibleHeadings.length}{visibleHeadings.length !== headings.length ? `/${headings.length}` : ''}</span>
            </span>
          </div>
          <div className="tree-scroll">
            {visibleHeadings.length ? visibleHeadings.map((heading, index) => (
              <button
                type="button"
                key={`${heading.id}-${index}`}
                data-toc-id={heading.id}
                className={`toc-item level-${heading.level} ${activeHeading === heading.id ? 'active' : ''}`}
                onClick={() => {
                  setActiveHeading(heading.id)
                  document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
              >
                {heading.text}
              </button>
            )) : <div className="dim" style={{ padding: '8px', fontSize: 12 }}>这篇没有标题层级</div>}
          </div>
        </aside>
      </div>
    </div>
  )
}
