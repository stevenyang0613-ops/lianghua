import React, { useMemo } from 'react'
import { Card } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import type { ScoreDistributionChartProps } from './types'

export default React.memo(function ScoreDistributionChart({ items }: ScoreDistributionChartProps) {
  const distribution = useMemo(() => {
    if (items.length === 0) return null
    const ranges = [
      { name: '0.9-1.0', min: 0.9, max: 1.0, count: 0 },
      { name: '0.8-0.9', min: 0.8, max: 0.9, count: 0 },
      { name: '0.7-0.8', min: 0.7, max: 0.8, count: 0 },
      { name: '0.6-0.7', min: 0.6, max: 0.7, count: 0 },
      { name: '0.5-0.6', min: 0.5, max: 0.6, count: 0 },
      { name: '0.4-0.5', min: 0.4, max: 0.5, count: 0 },
      { name: '0.3-0.4', min: 0.3, max: 0.4, count: 0 },
      { name: '0.0-0.3', min: 0, max: 0.3, count: 0 },
    ]
    for (const item of items) {
      for (const range of ranges) {
        if (item.score >= range.min && item.score < range.max) {
          range.count++
          break
        }
      }
    }
    return ranges
  }, [items])

  const chartOption = useMemo(() => {
    if (!distribution) return {}
    return {
      tooltip: { trigger: 'axis' as const, axisPointer: { type: 'shadow' as const } },
      grid: { left: 40, right: 20, top: 20, bottom: 40 },
      xAxis: { type: 'category' as const, data: distribution.map(r => r.name), axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value' as const, name: '数量' },
      series: [{
        type: 'bar' as const,
        data: distribution.map((r, i) => ({
          value: r.count,
          itemStyle: { color: i < 3 ? '#52c41a' : i < 5 ? '#1677ff' : '#faad14' },
        })),
        label: { show: true, position: 'top' as const, fontSize: 10 },
      }],
    }
  }, [distribution])

  if (!distribution) return null

  return (
    <Card title={<span><BarChartOutlined /> 评分分布</span>} size="small" style={{ marginBottom: 16 }}>
      <ReactEChartsCore echarts={echarts} option={chartOption} style={{ height: 200 }} opts={{ renderer: 'svg' }} />
    </Card>
  )
})
