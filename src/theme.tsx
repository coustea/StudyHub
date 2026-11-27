import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'notes_theme'

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return mode
}

function paint(mode: ThemeMode) {
  const root = document.documentElement
  const resolved = resolveTheme(mode)
  root.dataset.theme = resolved
  root.dataset.themeMode = mode
  root.style.colorScheme = resolved
  return resolved
}

/** 在首屏渲染前调用，避免深色模式用户看到白屏闪烁。 */
export function initTheme() {
  const stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
  const mode: ThemeMode = stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'dark'
  paint(mode)
  return mode
}

interface ThemeValue {
  mode: ThemeMode
  resolved: ResolvedTheme
  setMode: (mode: ThemeMode) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'dark'
  })
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(mode))

  const setMode = useCallback((next: ThemeMode) => {
    localStorage.setItem(STORAGE_KEY, next)
    setModeState(next)
    setResolved(paint(next))
  }, [])

  const toggle = useCallback(() => {
    setMode(resolveTheme(mode) === 'dark' ? 'light' : 'dark')
  }, [mode, setMode])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      if (mode !== 'system') return
      setResolved(paint('system'))
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [mode])

  const value = useMemo(() => ({ mode, resolved, setMode, toggle }), [mode, resolved, setMode, toggle])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const value = useContext(ThemeContext)
  if (!value) throw new Error('useTheme 必须在 ThemeProvider 中使用')
  return value
}
