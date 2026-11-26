import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { useSite } from '../site'
import { useTheme } from '../theme'
import Icon, { type IconName } from './Icon'

const NAV_ITEMS: { to: string; label: string; icon: IconName; exact?: boolean }[] = [
  { to: '/admin', label: '文章管理', icon: 'file', exact: true },
  { to: '/admin/projects', label: '项目管理', icon: 'folder' },
  { to: '/admin/daily', label: '今日学习', icon: 'calendar' },
  { to: '/admin/trash', label: '回收站', icon: 'trash' },
  { to: '/admin/settings#ai-model', label: '系统模型', icon: 'sparkle' },
  { to: '/admin/settings', label: '账户与站点', icon: 'gear', exact: true },
]

export default function AdminLayout() {
  const { user, logout } = useAuth()
  const site = useSite()
  const { resolved, toggle } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => { setDrawerOpen(false) }, [location.pathname, location.hash])

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setDrawerOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  const isCurrent = (item: typeof NAV_ITEMS[number]) => {
    if (item.to.includes('#')) {
      const [path, hash] = item.to.split('#')
      return location.pathname === path && location.hash === `#${hash}`
    }
    if (item.to === '/admin/settings') {
      return location.pathname === '/admin/settings' && location.hash !== '#ai-model'
    }
    return item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to)
  }

  return (
    <div className="admin-shell">
      <a className="skip-link" href="#admin-main">跳到主工作区</a>

      <header className="admin-mobile-bar">
        <Link to="/admin" className="brand">
          <span className="brand-mark" aria-hidden="true">{site.name.trim().slice(0, 1) || '笔'}</span>
          <span className="brand-name">{site.name} · 后台</span>
        </Link>
        <div className="topbar-actions">
          <Link className="btn btn-sm" to="/">阅读站</Link>
          <button
            type="button"
            className="icon-btn"
            aria-label={drawerOpen ? '关闭导航' : '打开导航'}
            aria-expanded={drawerOpen}
            aria-controls="admin-sidebar"
            onClick={() => setDrawerOpen((open) => !open)}
          >
            <Icon name={drawerOpen ? 'x' : 'list'} size={18} />
          </button>
        </div>
      </header>

      <aside id="admin-sidebar" className={`admin-sidebar${drawerOpen ? ' is-open' : ''}`}>
        <div className="admin-brand">
          <Link to="/admin" className="brand">
            <span className="brand-mark" aria-hidden="true">{site.name.trim().slice(0, 1) || '笔'}</span>
            <span className="brand-name">{site.name}</span>
          </Link>
          <span className="badge">管理后台</span>
        </div>

        <nav className="admin-nav" aria-label="后台导航">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="admin-nav-link"
              aria-current={isCurrent(item) ? 'page' : undefined}
            >
              <Icon name={item.icon} size={16} aria-hidden="true" />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className="admin-sidebar-foot">
          <Link to="/" className="admin-nav-link">
            <Icon name="book-open" size={16} aria-hidden="true" />
            <span>访问阅读站</span>
            <Icon name="arrow-up-right" size={14} style={{ marginLeft: 'auto' }} aria-hidden="true" />
          </Link>
          <div className="admin-foot-row">
            <span className="admin-user-label" title={user?.username}>{user?.display_name || user?.username}</span>
            <button
              type="button"
              className="icon-btn"
              onClick={toggle}
              aria-label={`切换到${resolved === 'dark' ? '浅色' : '深色'}模式`}
              title={`切换到${resolved === 'dark' ? '浅色' : '深色'}模式`}
            >
              <Icon name={resolved === 'dark' ? 'sun' : 'moon'} size={16} />
            </button>
            <button
              type="button"
              className="icon-btn"
              aria-label="退出登录"
              title="退出登录"
              onClick={() => { logout(); navigate('/') }}
            >
              <Icon name="sign-out" size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className="admin-main" id="admin-main" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
