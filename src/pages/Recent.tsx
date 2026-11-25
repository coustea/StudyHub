import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { usePageMeta } from '../site'
import Icon from '../components/Icon'

interface RecentNote {
  id: number
  title: string
  project_id: number
  project_name: string
  tags: string
  updated_at: string
}

export default function Recent() {
  const navigate = useNavigate()
  const [notes, setNotes] = useState<RecentNote[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  usePageMeta('最近更新')

  useEffect(() => {
    api.recent(50)
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
          <p>按更新时间倒序，包含所有你有权限看到的笔记。</p>
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
              <button
                key={note.id}
                className="result-row"
                onClick={() => navigate(`/p/${note.project_id}/n/${note.id}`)}
              >
                <div className="result-title">{note.title}</div>
                <div className="result-meta">
                  <span className="meta-item">{note.project_name}</span>
                  <span className="meta-item">{note.tags || '无标签'}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
