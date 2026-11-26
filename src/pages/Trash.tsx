import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { usePageMeta } from '../site'
import Icon from '../components/Icon'

interface TrashNode {
  id: number
  title: string
  kind: 'folder' | 'doc'
  project_id: number
  project_name: string
  deleted_at: string
}

function relativeTime(value: string): string {
  const time = new Date(String(value).replace(' ', 'T')).getTime()
  if (!Number.isFinite(time)) return String(value).slice(0, 10)
  const diff = Date.now() - time
  const minute = 60000
  if (diff < minute) return '刚刚'
  if (diff < 60 * minute) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < 24 * 60 * minute) return `${Math.floor(diff / (60 * minute))} 小时前`
  const days = Math.floor(diff / (24 * 60 * minute))
  if (days < 30) return `${days} 天前`
  return String(value).slice(0, 10)
}

export default function Trash() {
  const { user } = useAuth()
  const [nodes, setNodes] = useState<TrashNode[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(0)

  usePageMeta('回收站')

  const load = () => api.trash().then((res) => {
    setNodes(res.nodes)
    setTotal(res.total)
  })

  useEffect(() => {
    if (!user) { setLoading(false); return }
    load().catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [user])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  const restore = async (node: TrashNode) => {
    setBusy(node.id)
    try {
      await api.restoreNode(node.id)
      await load()
      setNotice(`已恢复「${node.title}」`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(0)
    }
  }

  const purge = async (node: TrashNode) => {
    if (!window.confirm(`彻底删除「${node.title}」？删除后无法恢复。`)) return
    setBusy(node.id)
    try {
      await api.purgeNode(node.id)
      await load()
      setNotice('已彻底删除')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(0)
    }
  }

  const empty = async () => {
    if (!window.confirm(`清空回收站里的 ${total} 项内容？此操作无法撤销。`)) return
    try {
      const res = await api.emptyTrash()
      await load()
      setNotice(`已清理 ${res.removed} 项`)
    } catch (e: any) {
      setError(e.message)
    }
  }

  if (!user) {
    return (
      <div className="page">
        <div className="empty">
          <Icon name="trash" size={26} className="empty-icon" />
          <span className="empty-title">回收站只有站长能看</span>
          <p>登录后可以恢复误删的笔记与目录。</p>
          <Link className="btn btn-primary btn-sm" to="/login">去登录</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="admin-page">
      <div className="page-title-row">
        <div>
          <h1>回收站</h1>
          <p>删除的笔记与目录会先放在这里，可以随时恢复；彻底删除后不可找回。</p>
        </div>
        <div className="head-actions">
          <Link className="btn btn-sm" to="/admin">
            <Icon name="arrow-left" size={14} />回到文章管理
          </Link>
          <button className="btn btn-sm btn-danger" onClick={empty} disabled={!total}>
            <Icon name="trash-simple" size={14} />清空回收站
          </button>
        </div>
      </div>

      {error && (
        <div className="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="alert alert-info">
          <Icon name="check-circle" size={16} />
          <span>{notice}</span>
        </div>
      )}

      {loading && (
        <div>
          {[0, 1, 2].map((row) => (
            <div className="skeleton-row" key={row} style={{ gridTemplateColumns: '1fr 120px' }}>
              <div>
                <div className="skeleton skeleton-title" style={{ width: `${46 - row * 6}%` }} />
                <div className="skeleton skeleton-text" style={{ width: '28%' }} />
              </div>
              <div className="skeleton skeleton-side" />
            </div>
          ))}
        </div>
      )}

      {!loading && nodes.length === 0 && (
        <div className="empty">
          <Icon name="trash-simple" size={26} className="empty-icon" />
          <span className="empty-title">回收站是空的</span>
          <p>删除的笔记会先放到这里，所以不用担心手滑。</p>
        </div>
      )}

      {!loading && nodes.length > 0 && (
        <div className="trash-list">
          {nodes.map((node) => (
            <div className="trash-row" key={node.id}>
              <div className="trash-icon">
                <Icon name={node.kind === 'folder' ? 'folder' : 'file'} size={17} />
              </div>
              <div className="trash-main">
                <div className="trash-title">{node.title}</div>
                <div className="trash-meta">
                  <span>{node.project_name}</span>
                  <span>{node.kind === 'folder' ? '目录及其子内容' : '笔记'}</span>
                  <span>{relativeTime(node.deleted_at)}删除</span>
                </div>
              </div>
              <div className="trash-actions">
                <button className="btn btn-sm" onClick={() => restore(node)} disabled={busy === node.id}>
                  <Icon name="arrow-counter-clockwise" size={14} />恢复
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => purge(node)} disabled={busy === node.id}>
                  彻底删除
                </button>
              </div>
            </div>
          ))}
          <div className="trash-foot dim">共 {total} 项，列表只显示顶层内容，恢复目录会连同子内容一起还原。</div>
        </div>
      )}
    </div>
  )
}
