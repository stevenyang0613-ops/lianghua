/**
 * 折线图组件
 */

import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart'

export interface LineChartProps {
  data: Array<{ name?: string; value: number }>
  xData?: string[]
  title?: string
  smooth?: boolean
  area?: boolean
  height?: number | string
  loading?: boolean
  color?: string
}

export function LineChart({
  data,
  xData,
  title,
  smooth = true,
  area = false,
  height = 300,
  loading,
  color = '#1890ff',
}: LineChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const values = data.map(d => d.value)
    const names = xData || data.map(d => d.name || '')

    return {
      title: title ? { text: title, left: 'center' } : undefined,
      tooltip: {
        trigger: 'axis',
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: names,
      },
      yAxis: {
        type: 'value',
      },
      series: [
        {
          type: 'line',
          data: values,
          smooth,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { width: 2, color },
          areaStyle: area ? {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: `${color}66` },
                { offset: 1, color: `${color}11` },
              ],
            },
          } : undefined,
        },
      ],
    }
  }, [data, xData, title, smooth, area, color])

  return <BaseChart option={option} style={{ height }} loading={loading} />
}

export default LineChart
