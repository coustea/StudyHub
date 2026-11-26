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
  const [showPassword, setShowPassword] = useState(false)
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
      navigate(username.trim() === 'coustea' ? '/admin' : '/')
    } catch (e: any) {
      setError(e.message)
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-pitch" aria-label="后台说明">
        <h1>登录后管理你的笔记库。</h1>
        <p className="auth-lede">
          自托管技术刊物与知识工作台：正文留在自己的服务器上，写作、目录编排与公开发布清晰分离。
        </p>
        <ol className="publication-plate-list auth-index">
          <li>
            <span className="plate-num">01</span>
            <div>
              <strong>文章与草稿管理</strong>
              <p>支持批量发布、转草稿与回收站恢复，未发布内容对访客完全不可见。</p>
            </div>
          </li>
          <li>
            <span className="plate-num">02</span>
            <div>
              <strong>专题目录与整包导入</strong>
              <p>可视化拖拽整理多级目录树，支持直接上传 Markdown 文件夹成册。</p>
            </div>
          </li>
          <li>
            <span className="plate-num">03</span>
            <div>
              <strong>系统 AI 写作模型</strong>
              <p>在后台统一配置接口地址、模型与密钥，编辑器内随时辅助写作。</p>
            </div>
          </li>
        </ol>
      </section>

      <section className="auth-card" aria-labelledby="login-heading">
        <div className="auth-card-head">
          <h2 id="login-heading">管理员登录</h2>
          <p className="auth-hint">本站不开放公开注册，账号由服务器配置生成。</p>
        </div>

        <form onSubmit={submit}>
          <div className="field">
            <label className="field-label" htmlFor="login-username">用户名</label>
            <input
              id="login-username"
              name="username"
              type="text"
              className={`input auth-input ${error ? 'input-invalid' : ''}`}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="输入管理员用户名"
              autoComplete="username"
              spellCheck={false}
              autoCapitalize="none"
              autoCorrect="off"
              enterKeyHint="next"
              autoFocus
              required
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="login-password">密码</label>
            <div className="password-wrap">
              <input
                id="login-password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                className={`input auth-input ${error ? 'input-invalid' : ''}`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入登录密码"
                autoComplete="current-password"
                enterKeyHint="done"
                required
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
                aria-pressed={showPassword}
                title={showPassword ? '隐藏密码' : '显示密码'}
              >
                <Icon name={showPassword ? 'eye-slash' : 'eye'} size={17} />
              </button>
            </div>
          </div>

          {error && (
            <div className="alert" role="alert">
              <Icon name="warning-circle" size={16} />
              <span>{error}</span>
            </div>
          )}

          <button className="btn btn-primary btn-block btn-lg" type="submit" disabled={submitting}>
            {submitting ? <><span className="spinner" style={{ borderTopColor: 'currentColor' }} />正在验证…</> : '登录管理后台'}
          </button>
        </form>

        <div className="auth-foot">
          <Link className="back-link" to="/">
            <Icon name="arrow-left" size={13} />返回阅读首页
          </Link>
        </div>
      </section>
    </div>
  )
}
