import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { usePageMeta } from '../site'
import Icon from '../components/Icon'
import { Badge } from '../components/ui/badge'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../components/ui/card'
import type { Project as ProjectType, ReaderNote } from '../types'

interface Overview {
  projects: ProjectType[]
  recent: ReaderNote[]
  tags: { tag: string; count: number }[]
}

const EMPTY: Overview = { projects: [], recent: [], tags: [] }
const formatDate = (value: string) => String(value || '').slice(0, 10)

export default function Home() {
  const { user } = useAuth()
  const isAdmin = user?.username === 'coustea'
  const [data, setData] = useState<Overview>(EMPTY)
  const [projectId, setProjectId] = useState<number>(0)
  const [activeTag, setActiveTag] = useState('')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  usePageMeta()

  useEffect(() => {
    api.overview(true)
      .then((res) => setData({ projects: res.projects || [], recent: res.recent || [], tags: res.tags || [] }))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const filteredNotes = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return data.recent.filter((note) => {
      if (projectId && note.project_id !== projectId) return false
      if (activeTag && !note.tags.split(',').map((t) => t.trim()).includes(activeTag)) return false
      if (needle && !`${note.title} ${note.excerpt} ${note.project_name} ${note.tags}`.toLowerCase().includes(needle)) return false
      return true
    })
  }, [data.recent, projectId, activeTag, query])

  const totalDocs = data.projects.reduce((sum, p) => sum + (p.doc_count || 0), 0)
  const totalFolders = data.projects.reduce((sum, p) => sum + (p.folder_count || 0), 0)
  const spotlight = data.recent[0] || null
  const hasNotes = data.recent.length > 0

  return (
    <div className="page">
      <section className="masthead">
        <div className="masthead-copy">
          <h1 className="masthead-title">
            沉淀工程实践，<br />
            <em>整理可重读的笔记。</em>
          </h1>
          <p className="masthead-lede">
            按专题系统归档技术教程、架构记录与代码示例。摒弃碎片堆砌，以出版级排版与清晰目录结构，让每一篇笔记随时可查、耐得住反复重读。
          </p>
          <div className="masthead-actions">
            {spotlight ? (
              <Link className="btn btn-primary btn-lg" to={`/p/${spotlight.project_id}/n/${spotlight.id}`}>
                <Icon name="book-open" size={16} />开始阅读最新一篇
              </Link>
            ) : isAdmin ? (
              <Link className="btn btn-primary btn-lg" to="/admin">
                <Icon name="pencil" size={16} />前往后台发布笔记
              </Link>
            ) : (
              <Link className="btn btn-primary btn-lg" to="/recent">
                <Icon name="book-open" size={16} />浏览最近更新
              </Link>
            )}
            <Link className="btn btn-lg" to="/search">
              <Icon name="search" size={16} />全文检索
            </Link>
          </div>

          <div className="masthead-colophon" aria-label="站内收录概览">
            <span><strong>{data.projects.length}</strong>个专题</span>
            <span className="sep" aria-hidden="true" />
            <span><strong>{totalDocs}</strong>篇公开笔记</span>
            <span className="sep" aria-hidden="true" />
            <span><strong>{totalFolders}</strong>个章节目录</span>
          </div>
        </div>

        <div className="masthead-side">
          {spotlight ? (
            <Link className="feature-reading" to={`/p/${spotlight.project_id}/n/${spotlight.id}`}>
              <div className="feature-meta">
                <span className="feature-topic">{spotlight.project_name}</span>
                <span>
                  {formatDate(spotlight.updated_at)}
                  {spotlight.reading_minutes ? ` · 约 ${spotlight.reading_minutes} 分钟` : ''}
                </span>
              </div>
              <h2>{spotlight.title}</h2>
              {spotlight.excerpt && <p className="feature-excerpt">{spotlight.excerpt}</p>}
              {spotlight.tags && (
                <div className="project-tags">
                  {spotlight.tags.split(',').map((t) => t.trim()).filter(Boolean).slice(0, 3)
                    .map((tag) => <Badge key={tag} variant="secondary">{tag}</Badge>)}
                </div>
              )}
              <div className="feature-foot">
                <span>阅读全文</span>
                <Icon name="arrow-up-right" size={16} />
              </div>
            </Link>
          ) : (
            <div className="publication-plate">
              <div className="publication-plate-head">
                <span>阅读体例</span>
                <span>EDITION</span>
              </div>
              <ol className="publication-plate-list">
                <li>
                  <span className="plate-num">01</span>
                  <div>
                    <strong>按专题成册</strong>
                    <p>围绕单一技术主题组织多级章节，像翻阅技术专著一样系统阅读。</p>
                  </div>
                </li>
                <li>
                  <span className="plate-num">02</span>
                  <div>
                    <strong>正文与大纲联动</strong>
                    <p>右侧实时定位本页标题层级，代码支持一键复制与 Markdown 导出。</p>
                  </div>
                </li>
                <li>
                  <span className="plate-num">03</span>
                  <div>
                    <strong>多关键词全文检索</strong>
                    <p>按标题、正文与标签即时匹配，随时定位过往记录的技术细节。</p>
                  </div>
                </li>
              </ol>
            </div>
          )}
        </div>
      </section>

      {error && (
        <div className="alert" role="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}

      <section className="section">
        <div className="section-head">
          <h2>最新笔记</h2>
          {hasNotes && (
            <Link className="link-btn" to="/recent" style={{ fontSize: 13 }}>
              查看全部 <Icon name="arrow-up-right" size={13} />
            </Link>
          )}
        </div>

        {hasNotes && (
          <>
            <div className="reader-filter-bar">
              <div className="reader-pills" role="group" aria-label="按专题筛选">
                <button type="button" className={`chip${projectId === 0 ? ' on' : ''}`} onClick={() => setProjectId(0)}>
                  全部专题
                </button>
                {data.projects.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`chip${projectId === p.id ? ' on' : ''}`}
                    onClick={() => setProjectId((cur) => (cur === p.id ? 0 : p.id))}
                  >
                    {p.name}<span className="chip-count">{p.doc_count || 0}</span>
                  </button>
                ))}
              </div>
              <span className="filter-wrap">
                <span className="search-glyph"><Icon name="search" size={15} /></span>
                <input
                  className="filter-input"
                  type="search"
                  placeholder="筛选标题、摘要或标签"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label="筛选笔记"
                />
              </span>
            </div>

            {data.tags.length > 0 && (
              <div className="reader-tags-strip" aria-label="热门标签">
                <span>标签：</span>
                {data.tags.slice(0, 8).map((item) => (
                  <button
                    key={item.tag}
                    type="button"
                    className={`tag${activeTag === item.tag ? ' on' : ''}`}
                    onClick={() => setActiveTag((cur) => (cur === item.tag ? '' : item.tag))}
                  >
                    {item.tag}
                  </button>
                ))}
                {activeTag && (
                  <button type="button" className="link-btn" style={{ fontSize: 12 }} onClick={() => setActiveTag('')}>
                    清除筛选
                  </button>
                )}
              </div>
            )}
          </>
        )}

        {loading && (
          <div className="reader-ledger">
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
          </div>
        )}

        {!loading && filteredNotes.length > 0 && (
          <div className="reader-ledger">
            {filteredNotes.map((note) => (
              <Link key={note.id} to={`/p/${note.project_id}/n/${note.id}`} className="reader-entry">
                <div className="reader-entry-aside">
                  <span className="reader-entry-project">{note.project_name}</span>
                  <span>{formatDate(note.updated_at)}</span>
                  {note.reading_minutes ? <span>约 {note.reading_minutes} 分钟</span> : null}
                </div>
                <div className="reader-entry-main">
                  <h3 className="reader-entry-title">{note.title}</h3>
                  {note.excerpt && <p className="reader-entry-excerpt">{note.excerpt}</p>}
                  {note.tags && (
                    <div className="project-tags">
                      {note.tags.split(',').map((t) => t.trim()).filter(Boolean).slice(0, 4)
                        .map((tag) => <Badge key={tag} variant="secondary">{tag}</Badge>)}
                    </div>
                  )}
                </div>
                <span className="reader-entry-arrow" aria-hidden="true">
                  <Icon name="arrow-up-right" size={16} />
                </span>
              </Link>
            ))}
          </div>
        )}

        {!loading && filteredNotes.length === 0 && (
          <div className="editorial-empty">
            <div className="editorial-empty-copy">
              <h3>{hasNotes ? '没有符合当前筛选条件的笔记' : '尚未发布公开笔记'}</h3>
              <p>
                {hasNotes
                  ? '可以清除筛选条件查看全部最新条目，或使用全文搜索定位更早的记录。'
                  : '新文章在后台设为「已发布」后，将按更新时间自动收录到此处并生成摘要与阅读时长。'}
              </p>
            </div>
            <div className="editorial-empty-actions">
              {hasNotes ? (
                <button type="button" className="btn btn-sm" onClick={() => { setProjectId(0); setActiveTag(''); setQuery('') }}>
                  重置筛选
                </button>
              ) : isAdmin ? (
                <Link className="btn btn-primary btn-sm" to="/admin">进入文章管理</Link>
              ) : (
                <Link className="btn btn-sm" to="/login">管理员登录</Link>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="section">
        <div className="section-head">
          <h2>专题目录</h2>
          <span className="section-count">{data.projects.length} 本</span>
        </div>

        {!loading && data.projects.length > 0 ? (
          <div className="project-list">
            {data.projects.map((project) => (
              <Link key={project.id} to={`/p/${project.id}`} className="project-card-link">
                <Card className="project-card">
                  <CardHeader>
                    <div className="project-mark" aria-hidden="true">{project.name.trim().slice(0, 1)}</div>
                    <CardTitle><h3>{project.name}</h3></CardTitle>
                    <CardDescription>{project.description || '按章节整理的技术学习笔记。'}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {project.tags && project.tags.length > 0 && (
                      <div className="project-tags">
                        {project.tags.slice(0, 4).map((tag) => <Badge key={tag} variant="secondary">{tag}</Badge>)}
                      </div>
                    )}
                  </CardContent>
                  <CardFooter>
                    <span>{project.doc_count || 0} 篇笔记 · {project.folder_count || 0} 个目录</span>
                    <span>{formatDate(project.updated_at)}</span>
                  </CardFooter>
                </Card>
              </Link>
            ))}
          </div>
        ) : !loading && (
          <div className="editorial-empty">
            <div className="editorial-empty-copy">
              <h3>暂无公开专题</h3>
              <p>每个专题对应一本独立的技术手册，支持多级目录树与整包 Markdown 导入。</p>
            </div>
            <div className="editorial-empty-actions">
              {isAdmin ? (
                <Link className="btn btn-sm" to="/admin/projects">管理专题</Link>
              ) : (
                <a className="btn btn-sm" href="/rss.xml"><Icon name="rss" size={14} />订阅 RSS</a>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
