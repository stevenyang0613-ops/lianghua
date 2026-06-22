import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import ThemeProvider from './components/ThemeProvider'
import App from './App'
import './global.css'
import { initFirstScreenOptimize } from './utils/firstScreenOptimize'

// 初始化首屏优化
initFirstScreenOptimize()

// Global error handlers for debugging
window.addEventListener('error', (event) => {
  console.error('[Global Error]', event.error?.message || event.message, event.error?.stack)
  if ((window as any).electronAPI) {
    console.error('[Global Error] Sending to main process...')
  }
  // 阻止错误继续传播，避免触发全局页面崩溃
  event.preventDefault()
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason)
  // 阻止未处理的 Promise rejection 继续传播，避免连锁崩溃
  event.preventDefault()
})

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('#root element not found in DOM')
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <ThemeProvider>
      <HashRouter>
        <App />
      </HashRouter>
    </ThemeProvider>
  </React.StrictMode>
)
