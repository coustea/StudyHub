import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { useSite } from './site'
import { useTheme } from './theme'
import Icon from './components/Icon'
import AdminLayout from './components/AdminLayout'
import Home from './pages/Home'
import Project from './pages/Project'
import Login from './pages/Login'
import Search from './pages/Search'
import Recent from './pages/Recent'
import Daily from './pages/Daily'
import Trash from './pages/Trash'
import Settings from './pages/Settings'
import AdminArticles from './pages/admin/AdminArticles'
import AdminProjects from './pages/admin/AdminProjects'
import AdminProjectTree from './pages/admin/AdminProjectTree'

const Editor = lazy(() => import('./pages/Editor'))

function ThemeToggle() {
  const { resolved, toggle } = useTheme()
  const next = resolved === 'dark' ? '浅色' : '深色'
  return (
    <button type="button" className="icon-btn" onClick={toggle} aria-label={`切换到${next}模式`} title={`切换到${next}模式`}>
      <Icon name={resolved === 'dark' ? 'sun' : 'moon'} size={18} />
    </button>
  )
}

function PublicLayout() {
  const { user } = useAuth()
  const site = useSite()
  const navigate = useNavigate()
  const location = useLocation()
  const [keyword, setKeyword] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement | null>(null)
  const isAdmin = user?.username === 'coustea'

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      if (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault()
        if (window.matchMedia('(max-width: 860px)').matches) { navigate('/search'); return }
        searchRef.current?.focus()
      }
      if (event.key === 'Escape' && document.activeElement === searchRef.current) searchRef.current?.blur()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])

  useEffect(() => { setMenuOpen(false) }, [location.pathname, location.search])

  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const isActive = (path: string) => path === '/'
    ? location.pathname === '/' || location.pathname.startsWith('/p/')
    : location.pathname.startsWith(path)

  const submitSearch = () => {
    if (!keyword.trim()) return
    navigate(`/search?q=${encodeURIComponent(keyword.trim())}`)
    setKeyword('')
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">跳到正文</a>

      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label={`${site.name} 首页`}>
            <span className="brand-mark" aria-hidden="true">{site.name.trim().slice(0, 1) || '拾'}</span>
            <span className="brand-name">{site.name}</span>
          </Link>

          <nav className="topnav" aria-label="主导航">
            <Link to="/" aria-current={isActive('/') ? 'page' : undefined}>笔记</Link>
            <Link to="/recent" aria-current={isActive('/recent') ? 'page' : undefined}>最近更新</Link>
            <Link to="/search" aria-current={isActive('/search') ? 'page' : undefined}>搜索</Link>
          </nav>

          <div className="topbar-spacer" />

          <form className="top-search" role="search" onSubmit={(e) => { e.preventDefault(); submitSearch() }}>
            <span className="search-glyph"><Icon name="search" size={15} /></span>
            <input
              ref={searchRef}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索标题、正文、标签"
              aria-label="全文搜索"
            />
            <kbd>/</kbd>
          </form>

          <div className="topbar-actions">
            <ThemeToggle />
            {isAdmin ? (
              <Link className="btn btn-primary btn-sm topbar-auth-btn" to="/admin">管理后台</Link>
            ) : (
              <Link className="btn btn-sm topbar-auth-btn" to="/login">登录</Link>
            )}
            <button
              type="button"
              className="icon-btn nav-toggle"
              aria-label={menuOpen ? '关闭菜单' : '打开菜单'}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <Icon name={menuOpen ? 'x' : 'list'} size={18} />
            </button>
          </div>
        </div>
      </header>

      {menuOpen && (
        <div className="mobile-sheet">
          <Link to="/" aria-current={isActive('/') ? 'page' : undefined}><Icon name="book-open" size={17} />笔记</Link>
          <Link to="/recent" aria-current={isActive('/recent') ? 'page' : undefined}><Icon name="clock" size={17} />最近更新</Link>
          <Link to="/search" aria-current={isActive('/search') ? 'page' : undefined}><Icon name="search" size={17} />搜索</Link>
          {isAdmin ? (
            <Link to="/admin"><Icon name="pencil" size={17} />管理后台</Link>
          ) : (
            <Link to="/login"><Icon name="sign-out" size={17} />登录</Link>
          )}
        </div>
      )}

      <main className="main" id="main-content" tabIndex={-1}>
        <Outlet />
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <strong>{site.name}</strong>
            <p>{site.description}</p>
          </div>
          <nav className="footer-links" aria-label="页脚导航">
            <Link to="/recent">最近更新</Link>
            <Link to="/search">全文搜索</Link>
            {isAdmin && <Link to="/admin">管理后台</Link>}
            <a href="/rss.xml"><Icon name="rss" size={14} style={{ display: 'inline', verticalAlign: '-2px' }} /> RSS</a>
            <a href="/sitemap.xml">站点地图</a>
          </nav>
          <div className="footer-meta">
            <span>{site.projectCount} 个专题 · {site.noteCount} 篇笔记</span>
            <span>按专题整理 · 随时重读</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

function AuthLayout() {
  const site = useSite()
  return (
    <div className="auth-shell">
      <a className="skip-link" href="#main-content">跳到正文</a>
      <header className="auth-topbar">
        <Link to="/" className="brand" aria-label={`${site.name} 首页`}>
          <span className="brand-mark" aria-hidden="true">{site.name.trim().slice(0, 1) || '拾'}</span>
          <span className="brand-name">{site.name}</span>
        </Link>
        <ThemeToggle />
      </header>
      <main className="auth-main" id="main-content" tabIndex={-1}>
        <Login />
      </main>
    </div>
  )
}

export default function App() {
  const { user, ready } = useAuth()
  const isAdmin = user?.username === 'coustea'

  if (!ready) {
    return (
      <div className="shell">
        <div className="loading-line" style={{ justifyContent: 'center' }}>
          <span className="spinner" /> 正在加载…
        </div>
      </div>
    )
  }

  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/p/:id" element={<Project />} />
        <Route path="/p/:id/n/:nodeId" element={<Project />} />
        <Route path="/search" element={<Search />} />
        <Route path="/recent" element={<Recent />} />
        <Route path="*" element={
          <div className="page">
            <div className="empty">
              <Icon name="warning-circle" size={28} className="empty-icon" />
              <span className="empty-title">页面不存在</span>
              <p>这个地址没有对应的内容，可能链接已经改动。</p>
              <Link className="btn" to="/">回到阅读首页</Link>
            </div>
          </div>
        } />
      </Route>

      <Route path="/login" element={user ? <Navigate to={isAdmin ? '/admin' : '/'} replace /> : <AuthLayout />} />

      <Route path="/admin" element={isAdmin ? <AdminLayout /> : <Navigate to={user ? '/' : '/login'} replace />}>
        <Route index element={<AdminArticles />} />
        <Route path="projects" element={<AdminProjects />} />
        <Route path="projects/:id" element={<AdminProjectTree />} />
        <Route path="daily" element={<Daily />} />
        <Route path="trash" element={<Trash />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      <Route path="/edit" element={user ? (
        <div className="shell">
          <main className="main" id="main-content" tabIndex={-1}>
            <Suspense fallback={<div className="loading-line"><span className="spinner" />正在加载编辑器…</div>}>
              <Editor />
            </Suspense>
          </main>
        </div>
      ) : <Navigate to="/login" replace />} />
    </Routes>
  )
}
