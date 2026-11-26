import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { AiConfig } from '../types'

type Mode = 'draft' | 'continue' | 'rewrite'
type Selection = { start: number; end: number; source: string }

export default function MarkdownAssistant({ title, content, textareaRef, onApply }: {
  title: string
  content: string
  textareaRef: { current: HTMLTextAreaElement | null }
  onApply: (markdown: string, range?: { start: number; end: number }) => void
}) {
  const id = useId()
  const [saved, setSaved] = useState<AiConfig | null>(null)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [baseURL, setBaseURL] = useState('')
  const [mode, setMode] = useState<Mode>('draft')
  const [prompt, setPrompt] = useState('')
  const [output, setOutput] = useState('')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    api.aiConfig().then(({ config }) => setSaved(config)).catch(() => {})
  }, [])

  const hasSystemConfig = Boolean(saved?.hasApiKey && saved?.model)
  const showManualFields = !hasSystemConfig || overrideOpen

  const generate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy) return
    const area = textareaRef.current
    const start = area?.selectionStart ?? 0
    const end = area?.selectionEnd ?? 0
    const selected = content.slice(start, end)
    if (mode === 'rewrite' && !selected.trim()) {
      setError('请先在正文中选中需要改写的内容')
      return
    }
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await api.generateMarkdown({
        apiKey: apiKey.trim() || undefined,
        model: model.trim() || undefined,
        baseURL: baseURL.trim() || undefined,
        mode,
        prompt: prompt.trim(),
        title,
        context: mode === 'rewrite' ? selected : mode === 'continue' ? content.slice(-12000) : '',
      })
      setOutput(result.markdown)
      setSelection(mode === 'rewrite' ? { start, end, source: content } : null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  const apply = () => {
    if (selection && content !== selection.source) {
      setError('正文已变化，请重新生成改写结果')
      return
    }
    onApply(output, selection || undefined)
    setOutput('')
    setSelection(null)
    setError('')
    setNotice('已加入正文，检查后记得保存笔记。')
  }

  return (
    <details className="ai-assistant">
      <summary>AI 辅助写作{hasSystemConfig ? `（${saved?.model}）` : ''}</summary>
      <form action="/api/ai/markdown" method="post" onSubmit={generate} aria-label="AI 辅助写作">
        <div className="ai-config-bar">
          {hasSystemConfig ? (
            <>
              <span className="ai-hint">
                当前使用系统模型 <strong>{saved?.model}</strong>（Key: {saved?.apiKeyHint}）。
              </span>
              <div style={{ display: 'flex', gap: 10 }}>
                <button type="button" className="link-btn" onClick={() => setOverrideOpen((open) => !open)}>
                  {overrideOpen ? '收起临时覆盖' : '临时切换模型'}
                </button>
                <Link className="link-btn" to="/admin/settings#ai-model">系统模型设置</Link>
              </div>
            </>
          ) : (
            <span className="ai-hint">
              尚未配置系统默认模型，可前往 <Link className="inline-link" to="/admin/settings#ai-model">系统模型设置</Link> 持久化保存，或在下方临时填写。
            </span>
          )}
        </div>

        <div className="ai-fields">
          {showManualFields && (
            <>
              <div className="ai-field">
                <label htmlFor={`${id}-key`}>API Key{hasSystemConfig ? '（留空沿用系统配置）' : ''}</label>
                <input id={`${id}-key`} name="apiKey" type="password" className="input" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                  maxLength={2048} required={!hasSystemConfig} spellCheck={false} />
              </div>
              <div className="ai-field">
                <label htmlFor={`${id}-model`}>模型名称{hasSystemConfig ? '（可选）' : ''}</label>
                <input id={`${id}-model`} name="model" className="input" value={model} onChange={(e) => setModel(e.target.value)}
                  placeholder={saved?.model || '输入可用的模型 ID'} maxLength={100} required={!hasSystemConfig} spellCheck={false} />
              </div>
              <div className="ai-field">
                <label htmlFor={`${id}-url`}>Base URL（可选）</label>
                <input id={`${id}-url`} name="baseURL" type="url" className="input" value={baseURL} onChange={(e) => setBaseURL(e.target.value)}
                  placeholder={saved?.baseURL || '默认使用 OpenAI 官方地址'} maxLength={300} pattern="https://.+" spellCheck={false} />
              </div>
            </>
          )}
          <div className="ai-field">
            <label htmlFor={`${id}-mode`}>写作方式</label>
            <select id={`${id}-mode`} name="mode" className="select" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              <option value="draft">写一段新内容</option>
              <option value="continue">接着现有正文续写</option>
              <option value="rewrite">改写选中的正文</option>
            </select>
          </div>
          <div className="ai-field ai-prompt">
            <label htmlFor={`${id}-prompt`}>写作要求</label>
            <textarea id={`${id}-prompt`} name="prompt" className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder="例如：用 Go 的代码示例解释 context 取消机制" maxLength={2000} required rows={3} />
          </div>
        </div>
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? '生成中…' : '生成 Markdown'}</button>
      </form>
      {error && <p className="ai-message ai-error" role="alert">{error}</p>}
      {notice && <p className="ai-message" role="status">{notice}</p>}
      {output && (
        <div className="ai-output">
          <label htmlFor={`${id}-output`}>生成结果</label>
          <textarea id={`${id}-output`} className="textarea" value={output} readOnly rows={10} />
          <button type="button" className="btn btn-primary" onClick={apply} disabled={busy}>
            {selection ? '替换选中内容' : '追加到正文'}
          </button>
        </div>
      )}
    </details>
  )
}
