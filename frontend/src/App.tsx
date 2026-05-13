import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './Layout'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<div style={{ padding: 24 }}><h2>行情总览</h2></div>} />
        <Route path="/market" element={<div style={{ padding: 24 }}><h2>实时行情</h2></div>} />
        <Route path="/backtest" element={<div style={{ padding: 24 }}><h2>回测中心</h2></div>} />
        <Route path="/trade" element={<div style={{ padding: 24 }}><h2>交易终端</h2></div>} />
        <Route path="/analysis" element={<div style={{ padding: 24 }}><h2>分析工具</h2></div>} />
        <Route path="/strategies" element={<div style={{ padding: 24 }}><h2>策略管理</h2></div>} />
        <Route path="/settings" element={<div style={{ padding: 24 }}><h2>系统设置</h2></div>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
