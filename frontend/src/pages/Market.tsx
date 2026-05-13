import { useEffect, useState, useCallback } from 'react'
import { Typography, Space, message } from 'antd'
import MarketTable from '../components/MarketTable'
import { useMarketStore } from '../stores/useMarketStore'
import { useAppStore } from '../stores/useAppStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { fetchAllQuotes } from '../services/api'
import type { ConvertibleQuote } from '../types'

const { Title } = Typography

export default function Market() {
  const [loading, setLoading] = useState(true)
  const { allBonds, setAllBonds, updateQuotes } = useMarketStore()
  const setSelectedBond = useAppStore((s) => s.setSelectedBond)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)

  const onWsMessage = useCallback((quotes: ConvertibleQuote[]) => {
    updateQuotes(quotes)
    setBackendConnected(true)
  }, [updateQuotes, setBackendConnected])

  useWebSocket(onWsMessage)

  useEffect(() => {
    fetchAllQuotes()
      .then((res) => {
        setAllBonds(res.bonds)
        setLoading(false)
        setBackendConnected(true)
      })
      .catch((err) => {
        console.error('Failed to fetch quotes:', err)
        setLoading(false)
        setBackendConnected(false)
        message.error('连接后端失败，请检查服务是否启动')
      })
  }, [setAllBonds, setBackendConnected])

  useEffect(() => {
    return () => setSelectedBond(null)
  }, [setSelectedBond])

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ marginBottom: 12, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>实时行情</Title>
        <span style={{ color: '#888' }}>共 {allBonds.length} 只可转债</span>
      </Space>
      <MarketTable bonds={allBonds} loading={loading} onRowClick={(code) => setSelectedBond(code)} />
    </div>
  )
}
