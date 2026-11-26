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
import './shadcn.css'
import './styles.css'

// 首屏前定好主题，避免深色模式闪白
initTheme()

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
