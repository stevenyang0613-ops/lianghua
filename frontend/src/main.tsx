import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import ThemeProvider from './components/ThemeProvider'
import App from './App'
import './global.css'
import { initFirstScreenOptimize } from './utils/firstScreenOptimize'

// 初始化首屏优化
initFirstScreenOptimize()

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
