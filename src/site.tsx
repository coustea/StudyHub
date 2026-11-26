import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

export interface SiteMeta {
  name: string
  description: string
  projectCount: number
  noteCount: number
  url: string
}

const DEFAULT_SITE: SiteMeta = {
  name: '笔记库',
  description: '教程、笔记与代码示例，按项目归档。',
  projectCount: 0,
  noteCount: 0,
  url: '',
}

const SiteContext = createContext<SiteMeta>(DEFAULT_SITE)

export function SiteProvider({ children }: { children: ReactNode }) {
  const [site, setSite] = useState<SiteMeta>(DEFAULT_SITE)

  useEffect(() => {
    api.site(true)
      .then((res) => setSite({ ...DEFAULT_SITE, ...res.site }))
      .catch(() => {})
  }, [])

  return <SiteContext.Provider value={site}>{children}</SiteContext.Provider>
}

export function useSite() {
  return useContext(SiteContext)
}

function setMeta(selector: string, attribute: 'name' | 'property', key: string, content: string) {
  let element = document.head.querySelector<HTMLMetaElement>(selector)
  if (!element) {
    element = document.createElement('meta')
    element.setAttribute(attribute, key)
    document.head.appendChild(element)
  }
  element.setAttribute('content', content)
}

/** 为每篇笔记设置标题、描述与 Open Graph，博客分享与搜索收录都依赖这些标签。 */
export function usePageMeta(title?: string, description?: string) {
  const site = useSite()

  useEffect(() => {
    const pageTitle = title ? `${title} · ${site.name}` : `${site.name} · ${site.description}`
    const pageDescription = (description || site.description || '').slice(0, 160)
    document.title = pageTitle
    setMeta('meta[name="description"]', 'name', 'description', pageDescription)
    setMeta('meta[property="og:title"]', 'property', 'og:title', pageTitle)
    setMeta('meta[property="og:description"]', 'property', 'og:description', pageDescription)
    setMeta('meta[property="og:type"]', 'property', 'og:type', title ? 'article' : 'website')
    setMeta('meta[name="twitter:card"]', 'name', 'twitter:card', 'summary')

    let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!canonical) {
      canonical = document.createElement('link')
      canonical.rel = 'canonical'
      document.head.appendChild(canonical)
    }
    canonical.href = `${window.location.origin}${window.location.pathname}`
  }, [title, description, site.name, site.description])
}

/** 注入 BlogPosting 结构化数据，帮助搜索引擎把页面识别为文章。 */
export function useStructuredData(data: Record<string, unknown> | null) {
  useEffect(() => {
    const id = 'page-jsonld'
    const existing = document.getElementById(id)
    if (!data) {
      existing?.remove()
      return
    }
    const script = (existing as HTMLScriptElement) || document.createElement('script')
    script.id = id
    script.setAttribute('type', 'application/ld+json')
    script.textContent = JSON.stringify(data)
    if (!existing) document.head.appendChild(script)
    return () => { document.getElementById(id)?.remove() }
  }, [data])
}
