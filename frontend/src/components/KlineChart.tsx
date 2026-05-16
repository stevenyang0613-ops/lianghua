/**
 * K线图组件
 * 使用 ECharts 实现专业K线图
 */

import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Spin, Empty, Space, Button, Select } from 'antd'

echarts.use([
  CandlestickChart,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
])
import { ZoomInOutlined, ZoomOutOutlined, ReloadOutlined } from '@ant-design/icons'

interface KlineData {
  date: string
  open: number
  close: number
  low: number
  high: number
  volume: number
}

interface KlineChartProps {
  data: KlineData[]
  code: string
  name: string
  loading?: boolean
  height?: number
}

export default function KlineChart({ data, loading, height = 500 }: KlineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('day')
  const [showMA, setShowMA] = useState(true)
  const [maPeriods, setMaPeriods] = useState([5, 10, 20, 60])

  // Resize listener (separate from data effect)
  useEffect(() => {
    const handleResize = () => chartInstance.current?.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  // Chart data update effect
  useEffect(() => {
    if (!chartRef.current || !data.length) return

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, 'dark')
    }

    const dates = data.map(d => d.date)
    const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
    const volumes = data.map(d => d.volume)

    // 计算均线
    const calculateMA = (period: number) => {
      const result: (number | null)[] = []
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push(null)
        } else {
          const sum = data.slice(i - period + 1, i + 1).reduce((acc, d) => acc + d.close, 0)
          result.push(+(sum / period).toFixed(2))
        }
      }
      return result
    }

    const maLines = maPeriods.map((p: number) => ({
      name: `MA${p}`,
      type: 'line' as const,
      data: calculateMA(p),
      smooth: true,
      lineStyle: { width: 1 },
      symbol: 'none',
    }))

    const option: any = {
      backgroundColor: 'transparent',
      animation: false,
      legend: {
        data: showMA ? maPeriods.map((p: number) => `MA${p}`) : [],
        top: 10,
        left: 'center',
        textStyle: { color: '#aaa' },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(0,0,0,0.8)',
        borderColor: '#333',
        textStyle: { color: '#fff' },
        formatter: (params: any) => {
          const data = params[0]
          const ohlcData = data.data
          return `
            <div style="font-weight:bold;margin-bottom:4px">${data.name}</div>
            <div>开: ${ohlcData[1]}</div>
            <div>收: ${ohlcData[2]}</div>
            <div>低: ${ohlcData[3]}</div>
            <div>高: ${ohlcData[4]}</div>
            <div>量: ${volumes[data.dataIndex]?.toLocaleString()}</div>
          `
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: { backgroundColor: '#777' },
      },
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 70,
          end: 100,
        },
        {
          show: true,
          xAxisIndex: [0, 1],
          type: 'slider',
          bottom: 10,
          start: 70,
          end: 100,
          height: 20,
          borderColor: '#333',
          backgroundColor: '#1a1a2e',
          fillerColor: 'rgba(24,144,255,0.2)',
          handleStyle: { color: '#1890ff' },
          textStyle: { color: '#aaa' },
        },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { color: '#aaa' },
          splitLine: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { show: false },
          splitLine: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
      ],
      yAxis: [
        {
          scale: true,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { color: '#aaa' },
          splitLine: { lineStyle: { color: '#222' } },
          min: (value: { min: number; max: number }) => value.min * 0.99,
          max: (value: { min: number; max: number }) => value.max * 1.01,
        },
        {
          scale: true,
          gridIndex: 1,
          splitNumber: 2,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { color: '#aaa' },
          splitLine: { lineStyle: { color: '#222' } },
        },
      ],
      grid: [
        {
          left: 60,
          right: 60,
          top: 50,
          height: '60%',
        },
        {
          left: 60,
          right: 60,
          top: '75%',
          height: '15%',
        },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          itemStyle: {
            color: '#ef5350',
            color0: '#26a69a',
            borderColor: '#ef5350',
            borderColor0: '#26a69a',
          },
        },
        ...(showMA ? maLines : []),
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes.map((v, i) => ({
            value: v,
            itemStyle: {
              color: data[i].close >= data[i].open ? '#ef5350' : '#26a69a',
            },
          })),
        },
      ],
    }

    chartInstance.current.setOption(option, true)
  }, [data, showMA, maPeriods])

  // 清理
  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  const handleZoomIn = () => {
    const option = chartInstance.current?.getOption() as any
    if (option?.dataZoom?.[0]) {
      const start = Math.max(0, (option.dataZoom[0].start || 70) - 10)
      const end = Math.min(100, (option.dataZoom[0].end || 100) - 5)
      chartInstance.current?.dispatchAction({
        type: 'dataZoom',
        start,
        end,
      })
    }
  }

  const handleZoomOut = () => {
    const option = chartInstance.current?.getOption() as any
    if (option?.dataZoom?.[0]) {
      const start = Math.max(0, (option.dataZoom[0].start || 70) + 5)
      const end = Math.min(100, (option.dataZoom[0].end || 100) + 10)
      chartInstance.current?.dispatchAction({
        type: 'dataZoom',
        start,
        end,
      })
    }
  }

  const handleReset = () => {
    chartInstance.current?.dispatchAction({
      type: 'dataZoom',
      start: 70,
      end: 100,
    })
  }

  if (loading) {
    return <Spin style={{ display: 'flex', justifyContent: 'center', padding: 100 }} />
  }

  if (!data.length) {
    return <Empty description="暂无K线数据" style={{ padding: 100 }} />
  }

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <Select value={period} onChange={setPeriod} style={{ width: 80 }} options={[
            { value: 'day', label: '日K' },
            { value: 'week', label: '周K' },
            { value: 'month', label: '月K' },
          ]} />
          <Select
            mode="multiple"
            value={showMA ? maPeriods : []}
            onChange={(v) => {
              if (v.length === 0) {
                setShowMA(false)
              } else {
                setShowMA(true)
                setMaPeriods(v as number[])
              }
            }}
            style={{ width: 180 }}
            placeholder="选择均线"
            options={[5, 10, 20, 30, 60, 120].map(v => ({ value: v, label: `MA${v}` }))}
          />
        </Space>
        <Space>
          <Button icon={<ZoomInOutlined />} onClick={handleZoomIn} />
          <Button icon={<ZoomOutOutlined />} onClick={handleZoomOut} />
          <Button icon={<ReloadOutlined />} onClick={handleReset} />
        </Space>
      </div>
      <div ref={chartRef} style={{ height, borderRadius: 8, background: '#1a1a2e' }} />
    </div>
  )
}
