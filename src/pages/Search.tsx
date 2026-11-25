import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { usePageMeta } from '../site'
import Icon from '../components/Icon'

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>
  // 支持多关键词：按空白切开，每个词都单独高亮。
  // 用一个正则的 alternation 一次切分，避免嵌套替换把已插入的 <mark> 再切一遍。
  const terms = query.split(/\s+/).filter(Boolean)
  if (terms.length === 0) return <>{text}</>
  const escaped = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const parts = String(text).split(new RegExp(`(${escaped.join('|')})`, 'gi'))
  const lower = new Set(terms.map((term) => term.toLowerCase()))
  return (
    <>
      {parts.map((part, index) =>
        lower.has(part.toLowerCase())
          ? <mark key={index}>{part}</mark>
          : <span key={index}>{part}</span>,
      )}
    </>
  )
}

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const query = searchParams.get('q') || ''
  const [input, setInput] = useState(query)
  const [result, setResult] = useState<{ query: string; projects: any[]; notes: any[] } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  usePageMeta(query ? `搜索 ${query}` : '搜索')

  useEffect(() => setInput(query), [query])

  useEffect(() => {
    if (!query) { setResult(null); setLoading(false); return }
    setLoading(true)
    setError('')
    api.search(query)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [query])

  const total = result ? result.projects.length + result.notes.length : 0

  return (
    <div className="page">
      <div className="page-title-row">
        <div>
          <h1>搜索</h1>
          <p>标题、正文与标签一起匹配。用空格分隔多个关键词时，结果需要同时命中全部关键词。</p>
        </div>
      </div>

      <div className="search-hero">
        <form
          className="search-form"
          onSubmit={(e) => { e.preventDefault(); setSearchParams(input.trim() ? { q: input.trim() } : {}) }}
        >
          <span className="search-input-wrap">
            <Icon name="search" size={17} />
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="搜索标题、正文或标签"
              aria-label="搜索关键词"
              autoFocus
            />
          </span>
          <button className="btn btn-primary" type="submit" style={{ height: 46 }}>
            搜索
          </button>
        </form>
      </div>

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}

      {!query && (
        <div className="empty" style={{ marginTop: 32 }}>
          <Icon name="search" size={26} className="empty-icon" />
          <span className="empty-title">输入关键词开始</span>
          <p>也可以直接点首页的标签，跳到对应的搜索结果。</p>
        </div>
      )}

      {loading && (
        <div className="loading-line">
          <span className="spinner" />正在搜索「{query}」…
        </div>
      )}

      {result && !loading && (
        <>
          <p className="result-count">
            找到 <strong>{total}</strong> 条与「{result.query}」相关的结果
          </p>

          {total === 0 && (
            <div className="empty" style={{ marginTop: 16 }}>
              <Icon name="search" size={26} className="empty-icon" />
              <span className="empty-title">没有匹配的内容</span>
              <p>换一个更短的关键词，或者去项目目录里翻一翻。</p>
              <Link className="btn btn-sm" to="/">回到项目列表</Link>
            </div>
          )}

          {result.projects.length > 0 && (
            <section className="result-section">
              <div className="result-head">
                <h2>项目</h2>
                <span>{result.projects.length}</span>
              </div>
              <div className="result-list">
                {result.projects.map((project) => (
                  <Link key={project.id} to={`/p/${project.id}`} className="result-row">
                    <div className="result-title"><Highlight text={project.name} query={query} /></div>
                    <div className="result-desc"><Highlight text={project.description || '暂无描述'} query={query} /></div>
                    <div className="result-meta">
                      <span className="meta-item">项目</span>
                      <span className="meta-item">更新于 {String(project.updated_at).slice(0, 10)}</span>
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {result.notes.length > 0 && (
            <section className="result-section">
              <div className="result-head">
                <h2>笔记</h2>
                <span>{result.notes.length}</span>
              </div>
              <div className="result-list">
                {result.notes.map((note) => (
                  <button
                    key={note.id}
                    className="result-row"
                    onClick={() => navigate(`/p/${note.project_id}/n/${note.id}`)}
                  >
                    <div className="result-title"><Highlight text={note.title} query={query} /></div>
                    <div className="result-desc"><Highlight text={note.excerpt} query={query} /></div>
                    <div className="result-meta">
                      <span className="meta-item">{note.project_name}</span>
                      <span className="meta-item">{note.tags || '无标签'}</span>
                      <span className="meta-item">更新于 {String(note.updated_at).slice(0, 10)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
