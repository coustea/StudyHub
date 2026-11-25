import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { useSite, usePageMeta } from '../site'
import Icon from '../components/Icon'

/** 账户与站点：改密码、看部署信息。单人站点，这里只放真正会用到的东西。 */
export default function Settings() {
  const { user, logout } = useAuth()
  const site = useSite()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [trashCount, setTrashCount] = useState<number | null>(null)

  usePageMeta('账户设置')

  useEffect(() => {
    if (!user) return
    api.trash().then((res) => setTrashCount(res.total)).catch(() => setTrashCount(null))
  }, [user])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 3000)
    return () => window.clearTimeout(timer)
  }, [notice])

  const submit = async () => {
    setError('')
    if (newPassword.length < 6) { setError('新密码至少 6 位'); return }
    if (newPassword !== confirm) { setError('两次输入的新密码不一致'); return }
    setSaving(true)
    try {
      await api.changePassword(oldPassword, newPassword)
      setOldPassword('')
      setNewPassword('')
      setConfirm('')
      setNotice('密码已更新，下次登录请使用新密码。')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!user) {
    return (
      <div className="page">
        <div className="empty">
          <Icon name="sign-out" size={26} className="empty-icon" />
          <span className="empty-title">需要登录</span>
          <p>账户设置只对站长开放。</p>
          <Link className="btn btn-primary btn-sm" to="/login">去登录</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-title-row">
        <div>
          <h1>账户设置</h1>
          <p>单人站点，这里只有账号安全与运行信息。</p>
        </div>
      </div>

      {error && (
        <div className="alert" role="alert">
          <Icon name="warning-circle" size={16} />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="alert alert-info" role="status">
          <Icon name="check-circle" size={16} />
          <span>{notice}</span>
        </div>
      )}

      <div className="settings-grid">
        <section className="panel">
          <div className="panel-head">
            <h2>账号</h2>
            <span className="dim">{user.username}</span>
          </div>
          <dl className="settings-list">
            <div><dt>用户名</dt><dd>{user.username}</dd></div>
            <div><dt>显示名</dt><dd>{user.display_name || user.username}</dd></div>
            <div><dt>角色</dt><dd>站点所有者</dd></div>
          </dl>
          <button className="btn btn-sm" onClick={() => { logout(); }}>退出登录</button>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>修改密码</h2>
            <span className="dim">至少 6 位</span>
          </div>
          <label className="field">
            <span className="field-label">当前密码</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">新密码</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">确认新密码</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
            />
          </label>
          <button
            className="btn btn-primary btn-sm"
            onClick={submit}
            disabled={saving || !oldPassword || !newPassword || !confirm}
          >
            {saving ? '保存中…' : '更新密码'}
          </button>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>站点</h2>
            <span className="dim">{site.projectCount} 项目 · {site.noteCount} 篇</span>
          </div>
          <dl className="settings-list">
            <div><dt>名称</dt><dd>{site.name}</dd></div>
            <div><dt>描述</dt><dd>{site.description}</dd></div>
            <div><dt>站点地址</dt><dd>{site.url || window.location.origin}</dd></div>
            <div><dt>回收站</dt><dd>{trashCount === null ? '—' : `${trashCount} 项待清理`}</dd></div>
          </dl>
          <div className="settings-actions">
            <Link className="btn btn-sm" to="/trash"><Icon name="trash" size={14} />回收站</Link>
            <a className="btn btn-sm" href="/rss.xml"><Icon name="rss" size={14} />RSS</a>
          </div>
          <p className="field-hint" style={{ marginTop: 12 }}>
            站点名称、描述与站点地址由服务器环境变量 <code>SITE_NAME</code> / <code>SITE_DESCRIPTION</code> / <code>SITE_URL</code> 决定，
            改完重启服务即可生效。
          </p>
        </section>
      </div>
    </div>
  )
}
