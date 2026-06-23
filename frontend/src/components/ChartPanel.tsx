import { useEffect, useMemo, useState } from 'react'
import { Segmented, Empty, Spin, Typography, Space } from 'antd'
import { useMarketStore } from '../stores/useMarketStore'
import { getApiBase } from '../utils/config'
import type { default as EChartsReact } from 'echarts-for-react'

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

let EChartsComponent: typeof EChartsReact | null = null

async function loadECharts() {
  if (!EChartsComponent) {
    const mod = await import('echarts-for-react')
    EChartsComponent = mod.default
  }
  return EChartsComponent
}

export default function ChartPanel({ code, name }: ChartPanelProps) {
  const [chartType, setChartType] = useState<ChartType>('price')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [echartsReady, setEchartsReady] = useState(false)
  const allBonds = useMarketStore((s) => s.allBonds)
  const bond = useMemo(() => allBonds.find(b => b.code === code), [allBonds, code])

  useEffect(() => {
    let mounted = true
    loadECharts().then(() => {
      if (mounted) setEchartsReady(true)
    })
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const fetchHistory = async () => {
      setLoading(true)
      try {
        const baseUrl = getApiBase()
        let data: any = null
        if (window.electronAPI?.httpRequest) {
          const result = await window.electronAPI.httpRequest('GET', `${baseUrl}/api/v1/history/${code}?limit=100`)
          if (result.ok) data = result.data
        } else {
          const resp = await fetch(`${baseUrl}/api/v1/history/${code}?limit=100`, { signal: controller.signal })
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
          data = await resp.json()
        }
        if (data?.history && data.history.length > 0) {
          const mapped: HistoryItem[] = data.history.map((h: { timestamp: string; price: number; premium_ratio: number; dual_low: number }) => ({
            time: new Date(h.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
            price: h.price,
            premium_ratio: h.premium_ratio,
            dual_low: h.dual_low,
          })).reverse()
          setHistory(mapped)
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        console.error('Failed to fetch history')
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }
    fetchHistory()
    return () => controller.abort()
  }, [code])

  const getCurrentValue = (): number => {
    if (!bond) return 0
    switch (chartType) {
      case 'price': return bond.price ?? 0
      case 'premium_ratio': return bond.premium_ratio ?? 0
      case 'dual_low': return bond.dual_low ?? 0
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

  const chartOption = useMemo(() => {
    const data = history.map(h => ({
      time: h.time,
      value: getChartValue(h),
    }))

    return {
      tooltip: {
        trigger: 'axis' as const,
        formatter: (params: { name: string; value: number }[]) => {
          const p = params[0]
          return `${p.name}<br/>${getChartLabel()}: ${(p.value ?? 0).toFixed(2)}`
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
  }, [history, chartType, changeValue])

  if (loading) {
    return <Spin style={{ display: 'flex', justifyContent: 'center', marginTop: 60 }} />
  }

  if (history.length === 0) {
    return <Empty description={'暂无历史数据'} style={{ marginTop: 60 }} />
  }

  if (!echartsReady) {
    return <Spin style={{ display: 'flex', justifyContent: 'center', marginTop: 60 }} />
  }

  const ECh = EChartsComponent!

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
        <Text style={{ fontSize: 24, fontWeight: 600, color: (changeValue ?? 0) >= 0 ? '#cf1322' : '#389e0d' }}>
          {(getCurrentValue() ?? 0).toFixed(2)}
        </Text>
        <Text type="secondary" style={{ marginLeft: 8 }}>
          {(changeValue ?? 0) >= 0 ? '+' : ''}{(changeValue ?? 0).toFixed(2)}%
        </Text>
      </div>

      <ECh
        option={chartOption}
        style={{ height: 200 }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}