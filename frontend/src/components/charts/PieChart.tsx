/**
 * 饼图组件
 */

import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart'

export interface PieChartProps {
  data: Array<{ name: string; value: number }>
  title?: string
  radius?: string | [string, string]
  center?: [string, string]
  height?: number | string
  loading?: boolean
  colors?: string[]
  showLabel?: boolean
}

const defaultColors = ['#1890ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96']

export function PieChart({
  data,
  title,
  radius = '60%',
  center = ['50%', '50%'],
  height = 300,
  loading,
  colors = defaultColors,
  showLabel = true,
}: PieChartProps) {
  const option = useMemo<EChartsOption>(() => ({
    title: title ? { text: title, left: 'center' } : undefined,
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
    },
    legend: {
      orient: 'vertical',
      left: 'left',
      top: 'middle',
    },
    color: colors,
    series: [
      {
        type: 'pie',
        radius,
        center,
        data: data.map(d => ({ name: d.name, value: d.value })),
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowOffsetX: 0,
            shadowColor: 'rgba(0, 0, 0, 0.5)',
          },
        },
        label: {
          show: showLabel,
          formatter: '{b}: {d}%',
        },
      },
    ],
  }), [data, title, radius, center, colors, showLabel])

  return <BaseChart option={option} style={{ height }} loading={loading} />
}

export default PieChart
