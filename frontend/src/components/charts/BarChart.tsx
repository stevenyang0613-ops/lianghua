/**
 * 柱状图组件
 */

import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart'

export interface BarChartProps {
  data: Array<{ name: string; value: number }>
  title?: string
  horizontal?: boolean
  height?: number | string
  loading?: boolean
  color?: string | string[]
  showLabel?: boolean
}

export function BarChart({
  data,
  title,
  horizontal = false,
  height = 300,
  loading,
  color = '#1890ff',
  showLabel = false,
}: BarChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const names = data.map(d => d.name)
    const values = data.map(d => d.value)

    return {
      title: title ? { text: title, left: 'center' } : undefined,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      xAxis: {
        type: horizontal ? 'value' : 'category',
        data: horizontal ? undefined : names,
        axisLabel: horizontal ? undefined : { interval: 0, rotate: 30 },
      },
      yAxis: {
        type: horizontal ? 'category' : 'value',
        data: horizontal ? names : undefined,
      },
      series: [
        {
          type: 'bar',
          data: values,
          itemStyle: {
            color: typeof color === 'string' ? color : undefined,
          },
          label: {
            show: showLabel,
            position: horizontal ? 'right' : 'top',
          },
        },
      ],
      color: typeof color === 'string' ? undefined : color,
    }
  }, [data, title, horizontal, color, showLabel])

  return <BaseChart option={option} style={{ height }} loading={loading} />
}

export default BarChart
