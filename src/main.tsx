import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource-variable/geist'
import '@fontsource-variable/jetbrains-mono'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { AuthProvider } from './auth'
import { SiteProvider } from './site'
import { ThemeProvider, initTheme } from './theme'
import './styles.css'

// 首屏前定好主题，避免深色模式闪白
initTheme()

// 旧版 HashRouter 的链接形如 /#/p/1，进入时重写成 /p/1，避免已分享的链接失效
if (window.location.hash.startsWith('#/')) {
  window.history.replaceState(null, '', window.location.hash.slice(1))
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ErrorBoundary>
        <BrowserRouter>
          <AuthProvider>
            <SiteProvider>
              <App />
            </SiteProvider>
          </AuthProvider>
        </BrowserRouter>
      </ErrorBoundary>
    </ThemeProvider>
  </React.StrictMode>,
)
