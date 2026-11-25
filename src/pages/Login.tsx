import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { usePageMeta } from '../site'
import Icon from '../components/Icon'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  usePageMeta('登录')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate('/')
    } catch (e: any) {
      setError(e.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-pitch">
        <h1>登录后继续写。</h1>
        <p>这是一个自托管的笔记站：内容存在自己的服务器上，没有第三方同步，也没有推荐算法。</p>
        <ul className="auth-points">
          <li><Icon name="check-circle" size={16} />新建项目、导入 Markdown 文件夹</li>
          <li><Icon name="check-circle" size={16} />发布前先存草稿，访客看不到</li>
          <li><Icon name="check-circle" size={16} />正文支持 GFM 表格、任务列表与代码高亮</li>
        </ul>
      </div>

      <div className="auth-card">
        <h2>站长登录</h2>
        <p className="auth-hint">本站不开放注册，账号由服务器环境变量创建。</p>
        <form onSubmit={submit}>
          <label className="field">
            <span className="field-label">用户名</span>
            <input
              className={`input ${error ? 'input-invalid' : ''}`}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </label>
          <label className="field">
            <span className="field-label">密码</span>
            <input
              className={`input ${error ? 'input-invalid' : ''}`}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <div className="alert" role="alert">
              <Icon name="warning-circle" size={16} />
              <span>{error}</span>
            </div>
          )}
          <button className="btn btn-primary btn-block btn-lg" type="submit" disabled={submitting}>
            {submitting ? <><span className="spinner" style={{ borderTopColor: 'currentColor' }} />登录中…</> : '登录'}
          </button>
        </form>
        <p className="auth-foot">
          <Link className="inline-link" to="/">先随便看看</Link>
        </p>
      </div>
    </div>
  )
}
