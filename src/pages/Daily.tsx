import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { usePageMeta } from '../site'
import { useReveal } from '../hooks/useReveal'
import Icon from '../components/Icon'

interface DailyNote {
  id: number
  title: string
  project_id: number
  project_name: string
  tags: string
  status: 'draft' | 'published'
  created_at: string
  updated_at: string
}

interface DailyResponse {
  date: string
  todayCount: number
  streak: number
  activeDays: number
  notes: DailyNote[]
  calendar: { date: string; count: number }[]
}

const EMPTY: DailyResponse = {
  date: '',
  todayCount: 0,
  streak: 0,
  activeDays: 0,
  notes: [],
  calendar: [],
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
// 一年视角：53 周正好铺满正文宽度，也看得出一整年的节奏
const HEAT_DAYS = 364

function localToday(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function shiftDate(date: string, delta: number): string {
  const value = new Date(`${date}T00:00:00`)
  value.setDate(value.getDate() + delta)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

/** 2026-11-22 → 11月22日 周六；今天显示成「今天」 */
function prettyDate(date: string, today: string): string {
  if (!date) return ''
  if (date === today) return '今天'
  const value = new Date(`${date}T00:00:00`)
  const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][value.getDay()]
  return `${value.getMonth() + 1} 月 ${value.getDate()} 日 · ${weekday}`
}

function longDate(date: string): string {
  if (!date) return ''
  const [year, month, day] = date.split('-')
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`
}

export default function Daily() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const today = localToday()
  const requested = searchParams.get('date') || today
  const date = /^\d{4}-\d{2}-\d{2}$/.test(requested) ? requested : today

  const [data, setData] = useState<DailyResponse>(EMPTY)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const heatRef = useRef<HTMLDivElement | null>(null)
  const heroRef = useReveal<HTMLDivElement>()
  const listRef = useReveal<HTMLDivElement>(80)

  usePageMeta(date === today ? '今日学习' : `${date} 的学习`)

  useEffect(() => {
    setLoading(true)
    api.daily(date, HEAT_DAYS + 1)
      .then((res) => setData({ ...EMPTY, ...res }))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [date])

  // 一年视图会横向溢出，默认滚到最右，让「这一周」始终可见
  useEffect(() => {
    const element = heatRef.current
    if (element) element.scrollLeft = element.scrollWidth
  }, [date, data.calendar])

  const startNote = async () => {
    if (creating) return
    setCreating(true)
    try {
      const res = await api.dailyNew({ date })
      navigate(`/edit?nodeId=${res.node.id}`)
    } catch (e: any) {
      setError(e.message)
      setCreating(false)
    }
  }

  const go = (target: string) => {
    if (target === today) setSearchParams({})
    else setSearchParams({ date: target })
  }

  // 热力图：按周分列（周一到周日），最后一列是当前这一周
  const heat = useMemo(() => {
    const counts = new Map(data.calendar.map((item) => [item.date, item.count]))
    const end = date
    const start = shiftDate(end, -(HEAT_DAYS - 1))
    // 把起点对齐到周一，保证每列正好七天
    const startDate = new Date(`${start}T00:00:00`)
    const offset = (startDate.getDay() + 6) % 7
    const aligned = shiftDate(start, -offset)
    const days: { date: string; count: number; future: boolean }[] = []
    let cursor = aligned
    while (cursor <= end) {
      days.push({ date: cursor, count: counts.get(cursor) || 0, future: false })
      cursor = shiftDate(cursor, 1)
    }
    // 补齐最后一周
    while (days.length % 7 !== 0) {
      days.push({ date: '', count: -1, future: true })
    }
    const weeks: typeof days[] = []
    for (let index = 0; index < days.length; index += 7) weeks.push(days.slice(index, index + 7))
    // 月份标签：某一周第一天所在月份与上一列不同时，标记为新月份；相邻太近的跳过，避免叠字
    let lastLabel = -99
    const months = weeks.map((week, index) => {
      const first = week.find((day) => day.date)?.date
      if (!first) return ''
      const month = Number(first.slice(5, 7))
      const previous = index > 0 ? weeks[index - 1].find((day) => day.date)?.date : ''
      const changed = index === 0 || (previous && Number(previous.slice(5, 7)) !== month)
      if (!changed) return ''
      if (index - lastLabel < 3) return ''
      lastLabel = index
      return `${month} 月`
    })
    return { weeks, months }
  }, [data.calendar, date])

  const maxCount = Math.max(1, ...data.calendar.map((item) => item.count))
  const heatLevel = (count: number) => {
    if (count <= 0) return 0
    const ratio = count / maxCount
    if (ratio > 0.75) return 4
    if (ratio > 0.5) return 3
    if (ratio > 0.25) return 2
    return 1
  }

  const grouped = useMemo(() => {
    const map = new Map<string, DailyNote[]>()
    for (const note of data.notes) {
      const key = note.project_name || '未命名项目'
      map.set(key, [...(map.get(key) || []), note])
    }
    return [...map.entries()]
  }, [data.notes])

  const monthCount = useMemo(() => {
    const prefix = date.slice(0, 7)
    return data.calendar
      .filter((item) => item.date.startsWith(prefix))
      .reduce((sum, item) => sum + item.count, 0)
  }, [data.calendar, date])

  return (
    <div className="admin-page">
      <div className="page-title-row">
        <div>
          <h1>今日学习</h1>
          <p>每天写下的代码笔记都记在这里。写一篇就算打卡，连续天数会一直累加。</p>
        </div>
        <div className="head-actions">
          <button className="btn btn-sm" onClick={() => go(shiftDate(date, -1))} aria-label="前一天">
            <Icon name="arrow-left" size={14} />前一天
          </button>
          <button className="btn btn-sm" onClick={() => go(today)} disabled={date === today}>今天</button>
          <button
            className="btn btn-sm"
            onClick={() => go(shiftDate(date, 1))}
            disabled={date >= today}
            aria-label="后一天"
          >
            后一天<Icon name="arrow-up-right" size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}

      <section className="daily-hero" ref={heroRef}>
        <div className="daily-date">
          <span className="daily-date-main">{prettyDate(date, today)}</span>
          <span className="daily-date-sub">{longDate(date)}</span>
        </div>
        <div className="daily-stats">
          <div className="daily-stat">
            <strong>{loading ? '—' : data.todayCount}</strong>
            <span>当天笔记</span>
          </div>
          <div className="daily-stat">
            <strong>{loading ? '—' : data.streak}</strong>
            <span>连续天数</span>
          </div>
          <div className="daily-stat">
            <strong>{loading ? '—' : data.activeDays}</strong>
            <span>累计打卡</span>
          </div>
          <div className="daily-stat">
            <strong>{loading ? '—' : monthCount}</strong>
            <span>本月笔记</span>
          </div>
        </div>
        {user && (
          <div className="daily-actions">
            <button className="btn btn-primary" onClick={startNote} disabled={creating}>
              <Icon name="note-pencil" size={15} />{creating ? '正在新建…' : (date === today ? '写今天的学习笔记' : '补写这天的笔记')}
            </button>
            <Link className="btn" to="/admin/projects">
              <Icon name="folder" size={15} />从项目里新建
            </Link>
          </div>
        )}
      </section>

      <section className="section">
        <div className="section-head">
          <h2>打卡记录</h2>
          <span className="section-count">最近 {HEAT_DAYS} 天</span>
        </div>
        <div className="heatmap-wrap">
          <div className="heatmap-legend">
            <span>少</span>
            {[0, 1, 2, 3, 4].map((level) => (
              <i key={level} className={`heat-cell level-${level}`} aria-hidden="true" />
            ))}
            <span>多</span>
          </div>
          <div className="heatmap" ref={heatRef}>
            <div className="heatmap-weekdays" aria-hidden="true">
              {WEEKDAYS.map((day) => <span key={day}>{day}</span>)}
            </div>
            <div className="heatmap-body">
              <div className="heatmap-months" aria-hidden="true">
                {heat.months.map((label, index) => (
                  label
                    ? <span className="heatmap-month" key={`m-${index}`} style={{ left: index * 19 }}>{label}</span>
                    : null
                ))}
              </div>
              <div className="heatmap-grid">
                {heat.weeks.map((week, index) => (
                  <div className="heatmap-week" key={index}>
                    {week.map((day, dayIndex) => (
                      day.future || !day.date
                        ? <i className="heat-cell level-empty" key={`e-${index}-${dayIndex}`} />
                        : (
                          <button
                            key={day.date}
                            className={`heat-cell level-${heatLevel(day.count)}${day.date === date ? ' is-current' : ''}`}
                            title={`${day.date} · ${day.count} 篇`}
                            aria-label={`${day.date} 写了 ${day.count} 篇`}
                            onClick={() => go(day.date)}
                          />
                        )
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="section" ref={listRef}>
        <div className="section-head">
          <h2>{date === today ? '今天写了什么' : '这天的笔记'}</h2>
          <span className="section-count">{data.notes.length} 篇</span>
        </div>

        {loading && (
          <div>
            {[0, 1].map((row) => (
              <div className="skeleton-row" key={row} style={{ gridTemplateColumns: '1fr 90px' }}>
                <div>
                  <div className="skeleton skeleton-title" style={{ width: `${52 - row * 8}%` }} />
                  <div className="skeleton skeleton-text" style={{ width: '30%' }} />
                </div>
                <div className="skeleton skeleton-side" />
              </div>
            ))}
          </div>
        )}

        {!loading && data.notes.length === 0 && (
          <div className="empty">
            <Icon name="calendar" size={26} className="empty-icon" />
            <span className="empty-title">
              {date === today ? '今天还没有记录' : '这天没有写笔记'}
            </span>
            <p>
              {date === today
                ? '哪怕只记一行今天学到的东西，也比什么都不留好。'
                : '可以跳到别的日期看看，或者直接补写这一天的。'}
            </p>
            {user && (
              <button className="btn btn-primary btn-sm" onClick={startNote} disabled={creating}>
                {date === today ? '开始写今天的第一篇' : '补写这天的笔记'}
              </button>
            )}
          </div>
        )}

        {!loading && grouped.map(([projectName, notes]) => (
          <div className="daily-group" key={projectName}>
            <div className="daily-group-head">
              <span>{projectName}</span>
              <span className="dim">{notes.length}</span>
            </div>
            <div className="result-list">
              {notes.map((note) => (
                <button
                  key={note.id}
                  className="result-row"
                  onClick={() => navigate(`/p/${note.project_id}/n/${note.id}`)}
                >
                  <div className="result-title">{note.title}</div>
                  <div className="result-meta">
                    <span className="meta-item">{String(note.updated_at).slice(11, 16)}</span>
                    {note.tags && <span className="meta-item">{note.tags}</span>}
                    {note.status === 'draft' && <span className="meta-item">草稿</span>}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}
