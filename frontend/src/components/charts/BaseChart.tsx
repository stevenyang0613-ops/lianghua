/**
 * 基础图表组件
 * 封装 ECharts 常用功能
 */

import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  CandlestickChart,
  RadarChart,
  GaugeChart,
} from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
  VisualMapComponent,
  ToolboxComponent,
} from 'echarts/components'
import type { EChartsOption, ECharts } from 'echarts'

// 注册必要的组件
echarts.use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  CandlestickChart,
  RadarChart,
  GaugeChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
  VisualMapComponent,
  ToolboxComponent,
])

export interface BaseChartProps {
  option: EChartsOption
  style?: React.CSSProperties
  className?: string
  loading?: boolean
  theme?: 'light' | 'dark' | string
  onChartReady?: (chart: ECharts) => void
  onResize?: () => void
}

export function BaseChart({
  option,
  style,
  className,
  loading,
  theme = 'light',
  onChartReady,
}: BaseChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ECharts | null>(null)
  const [isReady, setIsReady] = useState(false)

  // 初始化图表
  useEffect(() => {
    if (!containerRef.current) return

    const chart = echarts.init(containerRef.current, theme)
    chartRef.current = chart as unknown as ECharts
    setIsReady(true)
    onChartReady?.(chart as unknown as ECharts)

    return () => {
      chart.dispose()
      chartRef.current = null
    }
  }, [theme, onChartReady])

  // 更新配置
  useEffect(() => {
    if (chartRef.current && isReady) {
      chartRef.current.setOption(option, true)
    }
  }, [option, isReady])

  // 响应式
  useEffect(() => {
    const handleResize = () => {
      chartRef.current?.resize()
    }

    const resizeObserver = new ResizeObserver(handleResize)
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current)
    }

    window.addEventListener('resize', handleResize)

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  // 显示/隐藏加载状态
  useEffect(() => {
    if (chartRef.current) {
      if (loading) {
        chartRef.current.showLoading('default', {
          text: '加载中...',
          color: '#1890ff',
          maskColor: 'rgba(255, 255, 255, 0.8)',
        })
      } else {
        chartRef.current.hideLoading()
      }
    }
  }, [loading])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height: '100%', minHeight: 200, ...style }}
    />
  )
}

/**
 * 导出图片
 */
export function exportChartImage(chart: ECharts, filename = 'chart'): void {
  const url = chart.getDataURL({
    type: 'png',
    pixelRatio: 2,
    backgroundColor: '#fff',
  })

  const link = document.createElement('a')
  link.download = `${filename}.png`
  link.href = url
  link.click()
}

// useChartInstance 需要在 BaseChart 内部调用，这里作为类型导出
export type { ECharts } from 'echarts'

export default BaseChart
