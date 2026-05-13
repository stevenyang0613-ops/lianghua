import { useEffect, useState, useCallback } from 'react'
import { Typography, Space } from 'antd'
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

  const onWsMessage = useCallback((quotes: ConvertibleQuote[]) => updateQuotes(quotes), [updateQuotes])
  useWebSocket(onWsMessage)

  useEffect(() => {
    fetchAllQuotes()
      .then((res) => { setAllBonds(res.bonds); setLoading(false) })
      .catch(() => setLoading(false))
  }, [setAllBonds])

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
