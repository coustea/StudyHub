// 自定义 rehype 高亮：直接调用 lowlight，只注册用得到的语言。
// 相比 rehype-highlight + refractor 的组合，可以省掉一份重复的语法实现。
import { createLowlight } from 'lowlight'
import { toText } from 'hast-util-to-text'
import { visit } from 'unist-util-visit'
import { highlightAliases, highlightLanguages } from './highlight'
import type { Element, ElementContent, Root } from 'hast'

const lowlight = createLowlight(highlightLanguages)

Object.entries(highlightAliases).forEach(([alias, language]) => {
  try {
    lowlight.registerAlias({ [alias]: [language] })
  } catch {
    // 别名冲突时忽略，主语言名仍然可用
  }
})

function classesOf(node: Element): string {
  const value = node.properties?.className
  if (Array.isArray(value)) return value.join(' ')
  if (typeof value === 'string') return value
  return ''
}

function languageOf(node: Element): string {
  const fromClass = /lang(?:uage)?-([\w+#.-]+)/.exec(classesOf(node))
  if (fromClass) return fromClass[1].toLowerCase()
  const fromData = node.data && (node.data as { language?: unknown }).language
  return typeof fromData === 'string' ? fromData.toLowerCase() : ''
}

export default function rehypeHighlightNotebook() {
  return (tree: Root) => {
    visit(tree, 'element', (node: Element) => {
      if (node.tagName !== 'pre') return
      const code = node.children.find(
        (child): child is Element => child.type === 'element' && child.tagName === 'code',
      )
      if (!code) return
      // 已经高亮过就跳过，避免重复处理
      if (classesOf(code).includes('hljs')) return

      const text = toText(code, { whitespace: 'pre' }).replace(/\n$/, '')
      if (!text.trim()) return

      const language = languageOf(code)
      const supported = language && lowlight.registered(language) ? language : ''

      if (!supported) {
        code.properties = { ...code.properties, className: ['hljs', 'language-plaintext'] }
        return
      }

      try {
        const result = lowlight.highlight(supported, text)
        // lowlight 返回 root，其 children 是完整的 token 序列（可能多个 span + 文本节点）。
        // 之前只取第一个 span 会导致代码被截断成一行。
        const children = result.children.filter(
          (child): child is ElementContent => child.type === 'text' || child.type === 'element',
        )
        if (children.length) {
          code.children = children
        }
        code.properties = {
          ...code.properties,
          className: ['hljs', `language-${supported}`],
        }
      } catch {
        // 高亮失败时保留原始文本，不影响阅读
      }
      return undefined
    })
  }
}
