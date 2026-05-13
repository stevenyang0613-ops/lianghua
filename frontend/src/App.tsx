import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './Layout'
import Market from './pages/Market'
import Watchlist from './pages/Watchlist'
import Backtest from './pages/Backtest'
import Trade from './pages/Trade'
import Analysis from './pages/Analysis'
import Strategies from './pages/Strategies'
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
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
