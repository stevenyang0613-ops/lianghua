import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { Segmented, Empty, Spin, Typography, Space } from 'antd'
import { useMarketStore } from '../stores/useMarketStore'
import type { ConvertibleQuote } from '../types'

const { Text } = Typography

interface ChartPanelProps {
  code: string
  name: string
}

type ChartType = 'price' | 'premium_ratio' | 'dual_low'

interface HistoryItem {
  time: string
  price: number
  premium_ratio: number
  dual_low: number
}

export default function ChartPanel({ code, name }: ChartPanelProps) {
  const [chartType, setChartType] = useState<ChartType>('price')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const bonds = useMarketStore((s) => s.bonds)
  const bond = bonds.get(code)

  useEffect(() => {
    const fetchHistory = async () => {
      setLoading(true)
      try {
        const resp = await fetch(`/api/v1/history/${code}?limit=100`)
        const data = await resp.json()
        if (data.history && data.history.length > 0) {
          const mapped: HistoryItem[] = data.history.map((h: { timestamp: string; price: number; premium_ratio: number; dual_low: number }) => ({
            time: new Date(h.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
            price: h.price,
            premium_ratio: h.premium_ratio,
            dual_low: h.dual_low,
          })).reverse()
          setHistory(mapped)
        }
      } catch (e) {
        console.error('Failed to fetch history:', e)
      } finally {
        setLoading(false)
      }
    }
    fetchHistory()
  }, [code])

  const getCurrentValue = (): number => {
    if (!bond) return 0
    switch (chartType) {
      case 'price': return bond.price
      case 'premium_ratio': return bond.premium_ratio
      case 'dual_low': return bond.dual_low
    }
  }

  const changeValue = bond?.change_pct || 0

  const getChartValue = (h: HistoryItem): number => {
    switch (chartType) {
      case 'price': return h.price
      case 'premium_ratio': return h.premium_ratio
      case 'dual_low': return h.dual_low
    }
  }

  const getChartLabel = (): string => {
    switch (chartType) {
      case 'price': return '价格'
      case 'premium_ratio': return '溢价率(%)'
      case 'dual_low': return '双低值'
    }
  }

  const getOption = () => {
    const data = history.map(h => ({
      time: h.time,
      value: getChartValue(h),
    }))

    return {
      tooltip: {
        trigger: 'axis' as const,
        formatter: (params: { name: string; value: number }[]) => {
          const p = params[0]
          return `${p.name}<br/>${getChartLabel()}: ${p.value.toFixed(2)}`
        },
      },
      grid: {
        left: '10%',
        right: '5%',
        top: 30,
        bottom: 30,
      },
      xAxis: {
        type: 'category' as const,
        data: data.map(d => d.time),
        axisLine: { lineStyle: { color: '#ddd' } },
        axisLabel: { fontSize: 10, interval: Math.floor(data.length / 6) },
      },
      yAxis: {
        type: 'value' as const,
        splitLine: { lineStyle: { color: '#eee' } },
        axisLabel: { fontSize: 10 },
      },
      series: [{
        type: 'line' as const,
        data: data.map(d => d.value),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: changeValue >= 0 ? '#cf1322' : '#389e0d' },
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: changeValue >= 0 ? 'rgba(207,19,34,0.3)' : 'rgba(56,158,13,0.3)' },
              { offset: 1, color: 'rgba(255,255,255,0)' },
            ],
          },
        },
      }],
    }
  }

  if (loading) {
    return <Spin style={{ display: 'flex', justifyContent: 'center', marginTop: 60 }} />
  }

  if (history.length === 0) {
    return <Empty description="暂无历史数据" style={{ marginTop: 60 }} />
  }

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Text strong>{name}</Text>
          <Text type="secondary">{code}</Text>
        </Space>
        <Segmented
          size="small"
          value={chartType}
          onChange={(v) => setChartType(v as ChartType)}
          options={[
            { label: '价格', value: 'price' },
            { label: '溢价率', value: 'premium_ratio' },
            { label: '双低', value: 'dual_low' },
          ]}
        />
      </div>

      <div style={{ marginBottom: 8, textAlign: 'center' }}>
        <Text style={{ fontSize: 24, fontWeight: 600, color: changeValue >= 0 ? '#cf1322' : '#389e0d' }}>
          {getCurrentValue().toFixed(2)}
        </Text>
        <Text type="secondary" style={{ marginLeft: 8 }}>
          {changeValue >= 0 ? '+' : ''}{changeValue.toFixed(2)}%
        </Text>
      </div>

      <ReactECharts
        option={getOption()}
        style={{ height: 200 }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}
