import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { useSite, usePageMeta } from '../site'
import Icon from '../components/Icon'
import type { AiConfig } from '../types'

export default function Settings() {
  const { user, logout } = useAuth()
  const site = useSite()
  const id = useId()
  const isAdmin = user?.username === 'coustea'

  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [trashCount, setTrashCount] = useState<number | null>(null)

  const [aiConfig, setAiConfig] = useState<AiConfig>({ model: '', baseURL: '', hasApiKey: false, apiKeyHint: '' })
  const [aiKey, setAiKey] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [aiBaseURL, setAiBaseURL] = useState('')
  const [aiSaving, setAiSaving] = useState(false)
  const [aiTesting, setAiTesting] = useState(false)

  usePageMeta('账户与系统设置')

  useEffect(() => {
    if (!user) return
    api.trash().then((res) => setTrashCount(res.total)).catch(() => setTrashCount(null))
    if (isAdmin) {
      api.aiConfig().then(({ config }) => {
        setAiConfig(config)
        setAiModel(config.model)
        setAiBaseURL(config.baseURL)
      }).catch(() => {})
    }
  }, [user, isAdmin])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 3000)
    return () => window.clearTimeout(timer)
  }, [notice])

  const submitPassword = async (event: FormEvent) => {
    event.preventDefault()
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

  const submitAiConfig = async (event: FormEvent) => {
    event.preventDefault()
    if (aiSaving) return
    setError('')
    setAiSaving(true)
    try {
      const { config } = await api.saveAiConfig({
        apiKey: aiKey.trim() || undefined,
        model: aiModel.trim(),
        baseURL: aiBaseURL.trim(),
      })
      setAiConfig(config)
      setAiKey('')
      setNotice('系统 AI 模型配置已保存，编辑器将默认使用该模型。')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setAiSaving(false)
    }
  }

  const clearAiKey = async () => {
    if (!window.confirm('确定清除已保存的 API Key？')) return
    setAiSaving(true)
    setError('')
    try {
      const { config } = await api.saveAiConfig({
        model: aiModel.trim(),
        baseURL: aiBaseURL.trim(),
        clearApiKey: true,
      })
      setAiConfig(config)
      setNotice('已清除保存的 API Key。')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setAiSaving(false)
    }
  }

  const testAiConfig = async () => {
    if (aiTesting) return
    setError('')
    setNotice('')
    setAiTesting(true)
    try {
      const result = await api.testAiConfig({
        apiKey: aiKey.trim() || undefined,
        model: aiModel.trim() || undefined,
        baseURL: aiBaseURL.trim() || undefined,
      })
      setNotice(`${result.hint}（实际请求地址：${result.endpoint}/chat/completions）`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setAiTesting(false)
    }
  }

  if (!user) return null

  return (
    <div className="admin-page">
      <div className="page-title-row">
        <div>
          <h1>账户与系统设置</h1>
          <p>管理管理员账号安全、系统 AI 写作模型与站点运行信息。</p>
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

      {isAdmin && (
        <section id="ai-model" className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-head">
            <h2><Icon name="sparkle" size={16} style={{ display: 'inline', verticalAlign: '-2px', marginRight: 6 }} />系统 AI 模型配置</h2>
            <span className={`badge ${aiConfig.hasApiKey && aiConfig.model ? 'badge-published' : 'badge-draft'}`}>
              {aiConfig.hasApiKey && aiConfig.model ? `已启用 · ${aiConfig.model}` : '未配置'}
            </span>
          </div>
          <p className="field-hint" style={{ marginBottom: 14 }}>
            配置保存在本地 SQLite 数据库中，仅管理员（coustea）可读写。保存后在文章编辑器中打开「AI 辅助写作」会自动生效，无需每次重复输入。
          </p>
          <form onSubmit={submitAiConfig} className="ai-config-form">
            <div className="field">
              <label htmlFor={`${id}-model`} className="field-label">默认模型名称</label>
              <span id={`${id}-model-hint`} className="field-hint">例如 gpt-4o-mini、deepseek-chat 或服务商支持的模型 ID</span>
              <input
                id={`${id}-model`}
                className="input"
                value={aiModel}
                onChange={(e) => setAiModel(e.target.value)}
                placeholder="输入模型 ID"
                maxLength={100}
                required
                spellCheck={false}
                aria-describedby={`${id}-model-hint`}
              />
              <span className="field-error" role="presentation">请填写模型名称（1–100 字符）。</span>
            </div>

            <div className="field">
              <label htmlFor={`${id}-url`} className="field-label">Base URL（可选）</label>
              <span id={`${id}-url-hint`} className="field-hint">
                留空使用 OpenAI 官方地址。讯飞星火填 https://maas-api.cn-huabei-1.xf-yun.com/v2，DeepSeek 填 https://api.deepseek.com/v1；
                粘贴带 /chat/completions 的完整地址也会自动纠正
              </span>
              <input
                id={`${id}-url`}
                className="input"
                type="url"
                value={aiBaseURL}
                onChange={(e) => setAiBaseURL(e.target.value)}
                placeholder="https://api.openai.com/v1"
                maxLength={300}
                pattern="https://.+"
                spellCheck={false}
                aria-describedby={`${id}-url-hint`}
              />
              <span className="field-error" role="presentation">请输入有效的 HTTPS 域名地址，例如 https://api.openai.com/v1。</span>
            </div>

            <div className="field">
              <label htmlFor={`${id}-key`} className="field-label">
                API Key {aiConfig.hasApiKey ? `（已保存：${aiConfig.apiKeyHint}）` : ''}
              </label>
              <span id={`${id}-key-hint`} className="field-hint">
                {aiConfig.hasApiKey ? '留空表示保留当前已保存的密钥；输入新值则覆盖更新' : '仅用于服务端代发 AI 写作请求，页面不会回显明文'}
              </span>
              <input
                id={`${id}-key`}
                className="input"
                type="password"
                autoComplete="off"
                value={aiKey}
                onChange={(e) => setAiKey(e.target.value)}
                placeholder={aiConfig.hasApiKey ? '已配置，留空保持不变' : 'sk-...'}
                maxLength={2048}
                required={!aiConfig.hasApiKey}
                spellCheck={false}
                aria-describedby={`${id}-key-hint`}
              />
              <span className="field-error" role="presentation">首次配置请填写有效的 API Key。</span>
            </div>

            <div className="settings-actions">
              <button className="btn btn-primary btn-sm" type="submit" disabled={aiSaving}>
                {aiSaving ? '保存中…' : '保存模型配置'}
              </button>
              <button className="btn btn-sm" type="button" onClick={testAiConfig} disabled={aiTesting || aiSaving}>
                {aiTesting ? '测试中…' : '测试连接'}
              </button>
              {aiConfig.hasApiKey && (
                <button className="btn btn-sm btn-danger" type="button" onClick={clearAiKey} disabled={aiSaving}>
                  清除已保存 Key
                </button>
              )}
            </div>
          </form>
        </section>
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
            <div><dt>角色</dt><dd>{isAdmin ? '管理员 / 站点所有者' : '普通成员'}</dd></div>
          </dl>
          <button type="button" className="btn btn-sm" onClick={logout}>退出登录</button>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>修改密码</h2>
            <span className="dim">至少 6 位</span>
          </div>
          <form onSubmit={submitPassword}>
            <div className="field">
              <label htmlFor={`${id}-old`} className="field-label">当前密码</label>
              <input id={`${id}-old`} className="input" type="password" autoComplete="current-password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor={`${id}-new`} className="field-label">新密码</label>
              <span id={`${id}-new-hint`} className="field-hint">至少 6 位字符</span>
              <input id={`${id}-new`} className="input" type="password" autoComplete="new-password" minLength={6} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required aria-describedby={`${id}-new-hint`} />
              <span className="field-error" role="presentation">新密码长度不能少于 6 位。</span>
            </div>
            <div className="field">
              <label htmlFor={`${id}-cfm`} className="field-label">确认新密码</label>
              <input id={`${id}-cfm`} className="input" type="password" autoComplete="new-password" minLength={6} value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </div>
            <button className="btn btn-primary btn-sm" type="submit" disabled={saving || !oldPassword || !newPassword || !confirm}>
              {saving ? '保存中…' : '更新密码'}
            </button>
          </form>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>站点</h2>
            <span className="dim">{site.projectCount} 项目 · {site.noteCount} 篇公开</span>
          </div>
          <dl className="settings-list">
            <div><dt>名称</dt><dd>{site.name}</dd></div>
            <div><dt>描述</dt><dd>{site.description}</dd></div>
            <div><dt>站点地址</dt><dd>{site.url || window.location.origin}</dd></div>
            <div><dt>回收站</dt><dd>{trashCount === null ? '—' : `${trashCount} 项待清理`}</dd></div>
          </dl>
          <div className="settings-actions">
            <Link className="btn btn-sm" to="/admin/trash"><Icon name="trash" size={14} />回收站</Link>
            <a className="btn btn-sm" href="/rss.xml"><Icon name="rss" size={14} />RSS</a>
          </div>
        </section>
      </div>
    </div>
  )
}
