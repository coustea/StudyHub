import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { usePageMeta } from '../site'
import { useReveal } from '../hooks/useReveal'
import { countFolders, readFromDataTransfer, readFromFileList, type FolderReadResult } from '../lib/folder'
import Icon from '../components/Icon'
import type { Project as ProjectType } from '../types'

interface RecentNote {
  id: number
  title: string
  project_id: number
  project_name: string
  tags: string
  updated_at: string
}

interface TagCount { tag: string; count: number }

interface DailySummary {
  date: string
  todayCount: number
  streak: number
  activeDays: number
}

interface Overview {
  site: { name: string; description: string; projectCount: number; noteCount: number; url: string }
  projects: ProjectType[]
  recent: RecentNote[]
  tags: TagCount[]
  daily: DailySummary
}

const EMPTY: Overview = {
  site: { name: '', description: '', projectCount: 0, noteCount: 0, url: '' },
  projects: [],
  recent: [],
  tags: [],
  daily: { date: '', todayCount: 0, streak: 0, activeDays: 0 },
}

function formatDate(value: string): string {
  return String(value || '').slice(0, 10)
}

function firstLine(text: string): string {
  return String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*`_~]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [data, setData] = useState<Overview>(EMPTY)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
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
  const [starting, setStarting] = useState(false)
  const [dragging, setDragging] = useState(false)
  const folderInputRef = useRef<HTMLInputElement | null>(null)

  const heroRef = useReveal<HTMLDivElement>()
  const indexRef = useReveal<HTMLDivElement>(120)
  const duoRef = useReveal<HTMLDivElement>(80)

  usePageMeta()

  const load = () => api.overview().then((res) => {
    setData({
      site: { ...EMPTY.site, ...res.site },
      projects: res.projects || [],
      recent: res.recent || [],
      tags: res.tags || [],
      daily: { ...EMPTY.daily, ...(res.daily || {}) },
    })
  })

  useEffect(() => {
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return data.projects
    return data.projects.filter((project) =>
      `${project.name} ${project.description} ${(project.tags || []).join(' ')}`.toLowerCase().includes(needle))
  }, [data.projects, query])

  const totalDocs = data.projects.reduce((sum, project) => sum + (project.doc_count || 0), 0)
  const totalFolders = data.projects.reduce((sum, project) => sum + (project.folder_count || 0), 0)
  const spotlight = data.recent[0] || null

  const create = async () => {
    if (!name.trim() || creating) return
    setCreating(true)
    try {
      const res = await api.createProject({ name, description, status })
      setShowCreate(false)
      setName('')
      setDescription('')
      navigate(`/p/${res.project.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  const openFolder = (result: FolderReadResult) => {
    if (!result.files.length) {
      setError('这个文件夹里没有找到 Markdown 文件（.md / .mdx / .txt）')
      return
    }
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
    if (!user) return
    const result = await readFromDataTransfer(event.dataTransfer)
    openFolder(result)
  }

  const createFromFolder = async () => {
    if (!folder || !folder.files.length || importing) return
    setImporting(true)
    try {
      const res = await api.createProjectFromFolder({
        name: folderName,
        description: folderDescription,
        status: folderStatus,
        files: folder.files,
      })
      setFolder(null)
      navigate(`/p/${res.project.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setImporting(false)
    }
  }

  const startToday = async () => {
    if (starting) return
    setStarting(true)
    try {
      const res = await api.dailyNew({})
      navigate(`/edit?nodeId=${res.node.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setStarting(false)
    }
  }

  const dailyHint = data.daily.todayCount > 0
    ? `今天已经写了 ${data.daily.todayCount} 篇，连续第 ${data.daily.streak} 天。`
    : data.daily.streak > 0
      ? `今天还没写。已经连续 ${data.daily.streak} 天，别断在这里。`
      : '今天还没开始。写一篇今天的代码学习记录。'

  return (
    <div className="page">
      <section className="hero">
        <div className="hero-copy" ref={heroRef}>
          <h1 className="hero-title">
            写下的是笔记，<br />
            留下的是可以<em>重读</em>的理解。
          </h1>
          <p className="hero-lede">
            教程、读书笔记与代码示例，按项目归档成册。想找什么，用全文搜索；想沿着思路往回走，翻目录。
          </p>
          <div className="hero-actions">
            {user ? (
              <>
                <button className="btn btn-primary btn-lg" onClick={() => setShowCreate(true)}>
                  <Icon name="plus" size={16} />新建项目
                </button>
                <button className="btn btn-lg" onClick={() => folderInputRef.current?.click()}>
                  <Icon name="upload" size={16} />用文件夹建项目
                </button>
              </>
            ) : (
              <>
                <Link className="btn btn-primary btn-lg" to={data.projects[0] ? `/p/${data.projects[0].id}` : '/recent'}>
                  <Icon name="book-open" size={16} />开始阅读
                </Link>
                <Link className="btn btn-lg" to="/search">
                  <Icon name="search" size={16} />搜索全部笔记
                </Link>
              </>
            )}
            <input
              ref={(element) => {
                folderInputRef.current = element
                if (element) {
                  element.setAttribute('webkitdirectory', '')
                  element.setAttribute('directory', '')
                }
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

        <div className="hero-side">
          {spotlight ? (
            <Link className="preview-card" to={`/p/${spotlight.project_id}/n/${spotlight.id}`}>
              <div className="preview-head">
                <span>{spotlight.project_name}</span>
                <span>{formatDate(spotlight.updated_at)}</span>
              </div>
              <div className="preview-body">
                <h3>{spotlight.title}</h3>
                {spotlight.tags && (
                  <div className="project-tags" style={{ marginTop: 10 }}>
                    {spotlight.tags.split(',').map((tag) => tag.trim()).filter(Boolean).slice(0, 3)
                      .map((tag) => <span key={tag} className="tag">{tag}</span>)}
                  </div>
                )}
              </div>
              <div className="preview-foot">
                <Icon name="clock" size={13} />
                <span>最近更新的一篇</span>
                <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--accent)' }}>
                  打开 <Icon name="arrow-up-right" size={13} />
                </span>
              </div>
            </Link>
          ) : (
            <div className="preview-card">
              <div className="preview-head">
                <span>笔记库</span>
                <span>{loading ? '加载中' : '空'}</span>
              </div>
              <div className="preview-body">
                <h3>{loading ? '正在读取内容' : '还没有发布任何笔记'}</h3>
                <p className="preview-text">
                  {loading
                    ? '从本地数据库读取项目与笔记。'
                    : '登录后新建项目，或者直接把一个 Markdown 文件夹拖进页面。'}
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      <div className="shelf">
        <div className="shelf-stats">
          <div className="shelf-stat"><strong>{data.projects.length}</strong><span>个项目</span></div>
          <div className="shelf-stat"><strong>{totalDocs}</strong><span>篇笔记</span></div>
          <div className="shelf-stat"><strong>{totalFolders}</strong><span>个目录</span></div>
        </div>
        {data.tags.length > 0 && (
          <div className="shelf-tags">
            {data.tags.slice(0, 5).map((tag) => (
              <Link key={tag.tag} className="tag" to={`/search?q=${encodeURIComponent(tag.tag)}`}>
                {tag.tag}
              </Link>
            ))}
          </div>
        )}
      </div>

      {user && (
        <section className="today-strip" aria-label="今日学习">
          <div className="today-strip-main">
            <span className="today-strip-kicker">
              <Icon name="flame" size={13} /> 今日学习
            </span>
            <p className="today-strip-text">{dailyHint}</p>
          </div>
          <div className="today-strip-stats">
            <span><strong>{data.daily.todayCount}</strong> 今日</span>
            <span><strong>{data.daily.streak}</strong> 连续</span>
            <span><strong>{data.daily.activeDays}</strong> 累计打卡</span>
          </div>
          <div className="today-strip-actions">
            <button className="btn btn-primary btn-sm" onClick={startToday} disabled={starting}>
              <Icon name="pencil" size={14} />{starting ? '准备中…' : '写今天的笔记'}
            </button>
            <Link className="btn btn-sm" to="/daily">
              <Icon name="calendar" size={14} />打卡日历
            </Link>
          </div>
        </section>
      )}

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}

      <section className="section" ref={indexRef}>
        <div className="section-head">
          <h2>项目</h2>
          <span className="section-count">
            {filtered.length === data.projects.length
              ? `${data.projects.length} 个`
              : `${filtered.length} / ${data.projects.length}`}
          </span>
        </div>

        <div className="index-toolbar">
          <span className="filter-wrap">
            <span className="search-glyph"><Icon name="search" size={15} /></span>
            <input
              className="filter-input"
              placeholder="按名称、描述或标签筛选"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="筛选项目"
            />
          </span>
          {query && (
            <button className="btn btn-quiet btn-sm" onClick={() => setQuery('')}>
              <Icon name="x" size={14} />清除
            </button>
          )}
        </div>

        <div
          className={`project-list ${dragging ? 'dragging' : ''}`}
          onDragOver={(event) => { if (user) { event.preventDefault(); setDragging(true) } }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {loading && (
            <>
              {[0, 1, 2].map((row) => (
                <div className="skeleton-row" key={row}>
                  <div className="skeleton skeleton-mark" />
                  <div>
                    <div className="skeleton skeleton-title" />
                    <div className="skeleton skeleton-text" />
                  </div>
                  <div className="skeleton skeleton-side" />
                </div>
              ))}
            </>
          )}

          {dragging && <div className="drop-veil">松开，按这个文件夹创建项目</div>}

          {!loading && filtered.map((project) => (
            <Link key={project.id} to={`/p/${project.id}`} className="project-row">
              <div className={`project-mark ${project.status === 'draft' ? 'is-draft' : ''}`} aria-hidden="true">
                {project.name.trim().slice(0, 1)}
              </div>
              <div className="project-main">
                <div className="project-title-line">
                  <h3>{project.name}</h3>
                  {project.status === 'draft' && <span className="badge badge-draft">草稿</span>}
                </div>
                <p className="project-desc">{project.description || '这个项目还没有写描述。'}</p>
                {project.tags && project.tags.length > 0 && (
                  <div className="project-tags">
                    {project.tags.map((tag) => <span key={tag} className="tag">{tag}</span>)}
                  </div>
                )}
              </div>
              <div className="project-side">
                <span className="project-count">
                  {project.doc_count || 0}<em>篇</em>
                  <span className="sep">/</span>
                  {project.folder_count || 0}<em>目录</em>
                </span>
                <span className="project-date">{formatDate(project.updated_at)}</span>
              </div>
            </Link>
          ))}

          {!loading && filtered.length === 0 && (
            <div className="empty" style={{ marginTop: 24 }}>
              <Icon name="folder" size={26} className="empty-icon" />
              <span className="empty-title">{query ? '没有匹配的项目' : '还没有项目'}</span>
              <p>
                {query
                  ? '换一个关键词试试，或者清空筛选看全部项目。'
                  : user
                    ? '新建一个项目，或者把 Markdown 文件夹拖到下面的列表里。'
                    : '站长还没有发布项目，稍后再来看看。'}
              </p>
              {query
                ? <button className="btn btn-sm" onClick={() => setQuery('')}>清空筛选</button>
                : user && <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>新建项目</button>}
            </div>
          )}
        </div>
      </section>

      <div className="duo" ref={duoRef}>
        <section>
          <div className="section-head">
            <h2>最近更新</h2>
            <Link className="link-btn" to="/recent" style={{ fontSize: 12.5 }}>
              全部 <Icon name="arrow-up-right" size={13} />
            </Link>
          </div>
          {data.recent.length ? (
            <ul className="recent-list">
              {data.recent.map((note) => (
                <li key={note.id}>
                  <Link className="recent-item" to={`/p/${note.project_id}/n/${note.id}`}>
                    <span className="recent-title">{note.title}</span>
                    <span className="recent-meta">
                      <span className="recent-project">{note.project_name}</span>
                      <span>{formatDate(note.updated_at)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty">
              <span className="empty-title">暂时没有更新</span>
              <p>发布第一篇笔记后，这里会按更新时间列出。</p>
            </div>
          )}
        </section>

        <section>
          <div className="panel">
            <div className="panel-head">
              <h2>标签</h2>
              <span className="dim">{data.tags.length} 个</span>
            </div>
            {data.tags.length ? (
              <div className="tag-cloud">
                {data.tags.map((tag) => (
                  <Link key={tag.tag} className="chip" to={`/search?q=${encodeURIComponent(tag.tag)}`}>
                    {tag.tag}<span className="chip-count">{tag.count}</span>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="dim" style={{ fontSize: 13 }}>笔记加上标签后会汇总到这里。</p>
            )}
            <div style={{ borderTop: '1px solid var(--rule)', marginTop: 18, paddingTop: 14 }}>
              <Link className="link-btn" to="/search" style={{ fontSize: 13 }}>
                <Icon name="search" size={14} />进入全文搜索
              </Link>
            </div>
          </div>
        </section>
      </div>

      <div className="closing">
        <p>
          {spotlight
            ? `从「${firstLine(spotlight.title).slice(0, 42)}」继续读，或者回到项目目录挑一篇。`
            : '这个站点把笔记存在本地 SQLite 里，附件放在 data/uploads，随项目一起备份即可。'}
        </p>
        <div className="closing-links">
          <a href="/rss.xml"><Icon name="rss" size={14} style={{ display: 'inline', verticalAlign: '-2px' }} /> RSS 订阅</a>
          <a href="/sitemap.xml"><Icon name="list" size={14} style={{ display: 'inline', verticalAlign: '-2px' }} /> 站点地图</a>
        </div>
      </div>

      {showCreate && (
        <div className="modal-backdrop" onClick={() => setShowCreate(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="新建项目" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>新建项目</h2>
                <p>一个项目对应一本册子，笔记按目录挂进去。</p>
              </div>
              <button className="icon-btn" onClick={() => setShowCreate(false)} aria-label="关闭">
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="modal-body">
              <label className="field">
                <span className="field-label">项目名称</span>
                <input
                  className="input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                  onKeyDown={(e) => { if (e.key === 'Enter') create() }}
                />
              </label>
              <label className="field">
                <span className="field-label">项目描述</span>
                <textarea
                  className="textarea"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  placeholder="一句话说明这个项目讲什么"
                />
              </label>
              <label className="field">
                <span className="field-label">初始状态</span>
                <select className="select" value={status} onChange={(e) => setStatus(e.target.value as 'draft' | 'published')}>
                  <option value="published">直接发布，访客可见</option>
                  <option value="draft">先存草稿，只有自己可见</option>
                </select>
                <span className="field-hint">发布后仍可以随时转为草稿。</span>
              </label>
            </div>
            <div className="modal-actions">
              <div className="spacer" />
              <button className="btn" onClick={() => setShowCreate(false)}>取消</button>
              <button className="btn btn-primary" onClick={create} disabled={!name.trim() || creating}>
                {creating ? '创建中…' : '创建项目'}
              </button>
            </div>
          </div>
        </div>
      )}

      {folder && (
        <div className="modal-backdrop" onClick={() => setFolder(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="用文件夹创建项目" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>用文件夹创建项目</h2>
                <p>
                  {folder.files.length} 篇 Markdown · {countFolders(folder.files)} 个目录
                  {folder.skipped > 0 ? ` · 跳过 ${folder.skipped} 个其它文件` : ''}
                </p>
              </div>
              <button className="icon-btn" onClick={() => setFolder(null)} aria-label="关闭">
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="modal-body">
              <label className="field">
                <span className="field-label">项目名称</span>
                <input className="input" value={folderName} onChange={(e) => setFolderName(e.target.value)} autoFocus />
              </label>
              <label className="field">
                <span className="field-label">项目描述</span>
                <textarea
                  className="textarea"
                  value={folderDescription}
                  onChange={(e) => setFolderDescription(e.target.value)}
                  rows={2}
                  placeholder="一句话说明这个项目讲什么"
                />
              </label>
              <label className="field">
                <span className="field-label">发布状态</span>
                <select className="select" value={folderStatus} onChange={(e) => setFolderStatus(e.target.value as 'draft' | 'published')}>
                  <option value="published">直接发布，访客可见</option>
                  <option value="draft">先存草稿，只有自己可见</option>
                </select>
              </label>
              <div className="file-preview">
                {folder.files.slice(0, 6).map((file) => <div key={file.path}>{file.path}</div>)}
                {folder.files.length > 6 && <div className="dim">还有 {folder.files.length - 6} 篇…</div>}
              </div>
            </div>
            <div className="modal-actions">
              <div className="spacer" />
              <button className="btn" onClick={() => setFolder(null)} disabled={importing}>取消</button>
              <button className="btn btn-primary" onClick={createFromFolder} disabled={importing || !folderName.trim()}>
                {importing ? '导入中…' : '创建并导入'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
