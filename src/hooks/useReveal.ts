import { useEffect, useRef } from 'react'

/**
 * 进入视口时淡入。一次性的，不重复触发，也不监听 scroll。
 * 依赖 IntersectionObserver，prefers-reduced-motion 由 CSS 直接跳过。
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>(delay = 0) {
  const ref = useRef<T | null>(null)

  useEffect(() => {
    const element = ref.current
    if (!element || typeof IntersectionObserver === 'undefined') return
    element.classList.add('reveal')
    if (delay) element.style.setProperty('--reveal-delay', `${delay}ms`)

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        entry.target.classList.add('is-in')
        observer.unobserve(entry.target)
      })
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 })

    observer.observe(element)
    return () => observer.disconnect()
  }, [delay])

  return ref
}
