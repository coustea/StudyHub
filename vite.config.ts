import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:3001',
      '/rss.xml': { target: 'http://127.0.0.1:3001', changeOrigin: false },
      '/sitemap.xml': { target: 'http://127.0.0.1:3001', changeOrigin: false },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 只把长期不变的运行时单独切出来；编辑器由路由懒加载自动分包，
        // 其余交给 Rollup 按引用关系切，避免手写规则把大依赖并回主块。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('scheduler')) return 'react'
          if (id.includes('react-router') || id.includes('@remix-run')) return 'router'
          return undefined
        },
      },
    },
    chunkSizeWarningLimit: 800,
  },
})
