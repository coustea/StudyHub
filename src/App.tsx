import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { useSite } from './site'
import { useTheme } from './theme'
import Icon from './components/Icon'
import Home from './pages/Home'
import Project from './pages/Project'
import Login from './pages/Login'
import Search from './pages/Search'
import Recent from './pages/Recent'
import Daily from './pages/Daily'
import Trash from './pages/Trash'
import Settings from './pages/Settings'

// 编辑器体积大（Markdown 预览带语法高亮），只有站长用得到，按需加载
const Editor = lazy(() => import('./pages/Editor'))

function ThemeToggle() {
  const { resolved, toggle } = useTheme()
  const next = resolved === 'dark' ? '浅色' : '深色'
  return (
    <button
      type="button"
      className="icon-btn"
      onClick={toggle}
      aria-label={`切换到${next}模式`}
      title={`切换到${next}模式`}
    >
      <Icon name={resolved === 'dark' ? 'sun' : 'moon'} size={18} />
    </button>
  )
}

export default function App() {
  const { user, ready, logout } = useAuth()
  const site = useSite()
  const navigate = useNavigate()
  const location = useLocation()
  const [keyword, setKeyword] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement | null>(null)

  // 斜杠聚焦搜索框，输入框里不拦截
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target && (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      )
      if (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault()
        if (window.matchMedia('(max-width: 860px)').matches) {
          navigate('/search')
          return
        }
        searchRef.current?.focus()
      }
      if (event.key === 'Escape' && document.activeElement === searchRef.current) {
        searchRef.current?.blur()
      }
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

  if (!ready) {
    return (
      <div className="shell">
        <div className="loading-line" style={{ justifyContent: 'center' }}>
          <span className="spinner" /> 正在加载…
        </div>
      </div>
    )
  }

  const isActive = (path: string) => path === '/'
    ? location.pathname === '/'
    : location.pathname.startsWith(path)

  const submitSearch = () => {
    if (!keyword.trim()) return
    navigate(`/search?q=${encodeURIComponent(keyword.trim())}`)
    setKeyword('')
  }

  return (
    <div className="shell">
      {/* 键盘用户按第一下 Tab 就能跳过整条导航，直达正文 */}
      <a className="skip-link" href="#main-content">跳到正文</a>

      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label={`${site.name} 首页`}>
            <span className="brand-mark" aria-hidden="true">{site.name.trim().slice(0, 1) || '笔'}</span>
            <span className="brand-name">{site.name}</span>
          </Link>

          <nav className="topnav" aria-label="主导航">
            <Link to="/" className={isActive('/') ? 'active' : ''}>项目</Link>
            <Link to="/daily" className={isActive('/daily') ? 'active' : ''}>今日学习</Link>
            <Link to="/recent" className={isActive('/recent') ? 'active' : ''}>最近更新</Link>
            <Link to="/search" className={isActive('/search') ? 'active' : ''}>搜索</Link>
          </nav>

          <div className="topbar-spacer" />

          <form
            className="top-search"
            role="search"
            onSubmit={(event) => { event.preventDefault(); submitSearch() }}
          >
            <span className="search-glyph"><Icon name="search" size={15} /></span>
            <input
              ref={searchRef}
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索标题、正文、标签"
              aria-label="全文搜索"
            />
            <kbd>/</kbd>
          </form>

          <div className="topbar-actions">
            <ThemeToggle />
            {user ? (
              <>
                <Link
                  to="/settings"
                  className={`user-chip${isActive('/settings') ? ' active' : ''}`}
                  title="账户设置"
                >
                  {user.display_name || user.username}
                </Link>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="退出登录"
                  title="退出登录"
                  onClick={() => { logout(); navigate('/') }}
                >
                  <Icon name="sign-out" size={18} />
                </button>
              </>
            ) : (
              <Link className="btn btn-sm" to="/login">登录</Link>
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
          <Link to="/"><Icon name="book-open" size={17} />项目</Link>
          <Link to="/daily"><Icon name="calendar" size={17} />今日学习</Link>
          <Link to="/recent"><Icon name="clock" size={17} />最近更新</Link>
          <Link to="/search"><Icon name="search" size={17} />搜索</Link>
          {user && <Link to="/trash"><Icon name="trash" size={17} />回收站</Link>}
          {user && <Link to="/settings"><Icon name="gear" size={17} />账户设置</Link>}
          {user ? (
            <button type="button" onClick={() => { logout(); navigate('/') }}>
              <Icon name="sign-out" size={17} />退出登录
            </button>
          ) : (
            <Link to="/login"><Icon name="sign-out" size={17} />登录</Link>
          )}
        </div>
      )}

      <main className="main" id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/p/:id" element={<Project />} />
          <Route path="/p/:id/n/:nodeId" element={<Project />} />
          <Route path="/search" element={<Search />} />
          <Route path="/recent" element={<Recent />} />
          <Route path="/daily" element={<Daily />} />
          <Route path="/trash" element={<Trash />} />
          <Route path="/settings" element={user ? <Settings /> : <Navigate to="/login" replace />} />
          <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
          <Route path="/edit" element={user ? (
            <Suspense fallback={<div className="loading-line"><span className="spinner" />正在加载编辑器…</div>}>
              <Editor />
            </Suspense>
          ) : <Navigate to="/login" replace />} />
          <Route path="*" element={
            <div className="page">
              <div className="empty">
                <Icon name="warning-circle" size={28} className="empty-icon" />
                <span className="empty-title">页面不存在</span>
                <p>这个地址没有对应的内容，可能链接已经改动。</p>
                <Link className="btn" to="/">回到项目列表</Link>
              </div>
            </div>
          } />
        </Routes>
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <strong>{site.name}</strong>
            <p>{site.description}</p>
          </div>
          <nav className="footer-links" aria-label="页脚导航">
            <Link to="/daily">今日学习</Link>
            <Link to="/search">全文搜索</Link>
            <Link to="/recent">最近更新</Link>
            {user && <Link to="/trash">回收站</Link>}
            {user && <Link to="/settings">账户设置</Link>}
            <a href="/rss.xml"><Icon name="rss" size={14} style={{ display: 'inline', verticalAlign: '-2px' }} /> RSS</a>
            <a href="/sitemap.xml">站点地图</a>
          </nav>
          <div className="footer-meta">
            <span>{site.projectCount} 个项目 · {site.noteCount} 篇笔记</span>
            <span>Markdown 写作 · SQLite 本地存储</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
