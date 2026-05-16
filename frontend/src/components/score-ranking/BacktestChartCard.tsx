import React, { useMemo } from 'react'
import { Card } from 'antd'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import type { BacktestChartCardProps } from './types'

export default React.memo(function BacktestChartCard({ chartData }: BacktestChartCardProps) {
  const chartOption = useMemo(() => {
    if (!chartData || chartData.dates.length === 0) return {}
    let cumulative = 0
    const cumulativeReturns = chartData.returns.map(r => {
      cumulative += r
      return cumulative
    })
    return {
      tooltip: { trigger: 'axis' as const },
      legend: { data: ['单期收益', '累计收益', '胜率'], top: 0, right: 20 },
      grid: { left: 50, right: 60, top: 40, bottom: 40 },
      xAxis: { type: 'category' as const, data: chartData.dates, axisLabel: { rotate: 45, fontSize: 10 } },
      yAxis: [
        { type: 'value' as const, name: '收益率%', position: 'left' },
        { type: 'value' as const, name: '胜率%', position: 'right', min: 0, max: 100 },
      ],
      series: [
        { name: '单期收益', type: 'bar' as const, data: chartData.returns, itemStyle: { color: (v: number) => v >= 0 ? '#cf1322' : '#3f8600' } },
        { name: '累计收益', type: 'line' as const, data: cumulativeReturns, smooth: true, yAxisIndex: 0, lineStyle: { width: 2 } },
        { name: '胜率', type: 'line' as const, data: chartData.winRates, smooth: true, yAxisIndex: 1, lineStyle: { type: 'dashed', color: '#faad14' } },
      ],
    }
  }, [chartData])

  if (!chartData || chartData.dates.length === 0) return null

  return (
    <Card size="small" title="收益曲线" style={{ marginBottom: 16 }}>
      <ReactEChartsCore echarts={echarts} option={chartOption} style={{ height: 300 }} opts={{ renderer: 'svg' }} />
    </Card>
  )
})
