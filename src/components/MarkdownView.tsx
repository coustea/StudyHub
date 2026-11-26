import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import rehypeHighlightNotebook from '../lib/rehypeHighlight'
import CodeBlock from './CodeBlock'

interface Props {
  title?: string
  content: string
  emptyHint?: string
  /**
   * 阅读页已经把标题渲染成 h1，正文里若再出现同名的一级标题会重复。
   * 传 true 时去掉开头那个和标题同名的一级标题。
   */
  stripLeadingTitle?: boolean
}

function stripDuplicateTitle(markdown: string, title?: string): string {
  if (!title) return markdown
  const lines = markdown.replace(/^\s+/, '').split('\n')
  const first = lines[0]?.trim() || ''
  const heading = /^#\s+(.*)$/.exec(first)
  if (!heading) return markdown
  const normalize = (value: string) => value
    .replace(/[*_`~]/g, '')
    .replace(/\s+/g, '')
    .toLowerCase()
  if (normalize(heading[1]) !== normalize(title)) return markdown
  // 连同标题后的空行一起去掉
  let index = 1
  while (index < lines.length && !lines[index].trim()) index += 1
  return lines.slice(index).join('\n')
}

/**
 * 阅读页与编辑器预览共用同一条 Markdown 管线：
 * 同一份语法高亮实现，避免编辑器再打包一份 refractor。
 */
export default function MarkdownView({ title, content, emptyHint, stripLeadingTitle }: Props) {
  const body = useMemo(() => {
    const raw = content || emptyHint || '_这篇笔记还是空的。_'
    return stripLeadingTitle ? stripDuplicateTitle(raw, title) : raw
  }, [content, emptyHint, stripLeadingTitle, title])

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSlug, rehypeHighlightNotebook]}
        components={{
          pre: CodeBlock,
          table: ({ children }) => (
            <div className="table-scroll" role="region" aria-label="表格内容" tabIndex={0}>
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  )
}
