import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { usePageMeta } from '../site'
import Icon from '../components/Icon'

interface RecentNote {
  id: number
  title: string
  project_id: number
  project_name: string
  tags: string
  excerpt?: string
  reading_minutes?: number
  updated_at: string
}

export default function Recent() {
  const [notes, setNotes] = useState<RecentNote[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  usePageMeta('最近更新')

  useEffect(() => {
    api.recent(50, true)
      .then((res) => setNotes(res.notes))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  // 按日期分组，避免一长串无差别的行
  const groups = notes.reduce<Record<string, RecentNote[]>>((acc, note) => {
    const day = String(note.updated_at).slice(0, 10)
    acc[day] = acc[day] || []
    acc[day].push(note)
    return acc
  }, {})

  return (
    <div className="page">
      <div className="page-title-row">
        <div>
          <h1>最近更新</h1>
          <p>按更新时间倒序，浏览最新发布的公开笔记。</p>
        </div>
        <Link className="btn btn-sm" to="/search">
          <Icon name="search" size={14} />搜索全部
        </Link>
      </div>

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}

      {loading && (
        <div>
          {[0, 1, 2, 3, 4].map((row) => (
            <div className="skeleton-row" key={row} style={{ gridTemplateColumns: '1fr 100px' }}>
              <div>
                <div className="skeleton skeleton-title" style={{ width: `${58 - row * 4}%` }} />
                <div className="skeleton skeleton-text" style={{ width: '34%' }} />
              </div>
              <div className="skeleton skeleton-side" />
            </div>
          ))}
        </div>
      )}

      {!loading && notes.length === 0 && (
        <div className="empty">
          <Icon name="clock" size={26} className="empty-icon" />
          <span className="empty-title">还没有笔记</span>
          <p>发布第一篇之后，这里会按日期列出来。</p>
        </div>
      )}

      {!loading && Object.entries(groups).map(([day, items]) => (
        <section className="result-section" key={day}>
          <div className="result-head">
            <h2>{day}</h2>
            <span>{items.length}</span>
          </div>
          <div className="result-list">
            {items.map((note) => (
              <Link
                key={note.id}
                to={`/p/${note.project_id}/n/${note.id}`}
                className="result-row"
              >
                <div className="result-row-body">
                  <div className="result-title">{note.title}</div>
                  {note.excerpt && <div className="result-desc">{note.excerpt}</div>}
                  <div className="result-meta">
                    <span className="meta-item result-project">{note.project_name}</span>
                    {note.reading_minutes ? <span className="meta-item">约 {note.reading_minutes} 分钟</span> : null}
                    {note.tags && <span className="meta-item">{note.tags}</span>}
                  </div>
                </div>
                <span className="result-arrow" aria-hidden="true">
                  <Icon name="arrow-up-right" size={15} />
                </span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
