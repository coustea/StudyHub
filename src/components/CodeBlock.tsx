import { isValidElement, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import Icon from './Icon'

function detectLanguage(children: ReactNode): string {
  const child = Array.isArray(children) ? children[0] : children
  if (!isValidElement(child)) return ''
  const className = (child.props as { className?: string }).className || ''
  const match = /language-([\w+#-]+)/.exec(className)
  return match ? match[1] : ''
}

export default function CodeBlock({ children }: ComponentProps<'pre'>) {
  const preRef = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)
  const language = detectLanguage(children)

  const copy = async () => {
    const text = (preRef.current?.innerText || '').replace(/\n$/, '')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const area = document.createElement('textarea')
      area.value = text
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="code-block">
      <div className="code-block-actions">
        {language && <span className="code-lang">{language}</span>}
        <button
          type="button"
          className={`code-copy ${copied ? 'copied' : ''}`}
          onClick={copy}
          aria-label={copied ? '已复制' : '复制代码'}
        >
          <Icon name={copied ? 'check' : 'copy'} size={13} />
          <span>{copied ? '已复制' : '复制'}</span>
        </button>
      </div>
      <pre ref={preRef}>{children}</pre>
    </div>
  )
}
