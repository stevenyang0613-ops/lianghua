import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './Layout'
import Market from './pages/Market'
import Watchlist from './pages/Watchlist'
import Backtest from './pages/Backtest'
import Trade from './pages/Trade'
import Settings from './pages/Settings'
import { initDefaultUser } from './stores/useUserStore'

export default function App() {
  useEffect(() => {
    initDefaultUser()
  }, [])

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Market />} />
        <Route path="/market" element={<Market />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/trade" element={<Trade />} />
        <Route path="/analysis" element={<div style={{ padding: 24 }}><h2>分析工具</h2></div>} />
        <Route path="/strategies" element={<div style={{ padding: 24 }}><h2>策略管理</h2></div>} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
