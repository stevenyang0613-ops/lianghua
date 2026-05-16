import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import ThemeProvider from './components/ThemeProvider'
import App from './App'
import './global.css'
import { initFirstScreenOptimize } from './utils/firstScreenOptimize'

// 初始化首屏优化
initFirstScreenOptimize()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <HashRouter>
        <App />
      </HashRouter>
    </ThemeProvider>
  </React.StrictMode>
)
