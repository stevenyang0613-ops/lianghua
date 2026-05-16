/**
 * 时间序列图组件
 */
import React, { useRef, useEffect, useMemo, useCallback } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

export interface TimeSeriesPoint {
  time: number
  value: number
  name?: string
}

export interface TimeSeriesSeries {
  name: string
  data: TimeSeriesPoint[]
  color?: string
  type?: 'line' | 'bar' | 'area'
  yAxisIndex?: number
}

export interface TimeSeriesChartProps {
  series: TimeSeriesSeries[]
  title?: string
  height?: number
  theme?: 'light' | 'dark'
  showLegend?: boolean
  showDataZoom?: boolean
  yAxis?: {
    name?: string
    min?: number
    max?: number
  }[]
  markPoints?: {
    seriesName: string
    points: { time: number; value: number; name: string }[]
  }[]
  markLines?: {
    seriesName: string
    lines: { value: number; name: string }[]
  }[]
  onPointClick?: (data: { seriesName: string; time: number; value: number }) => void
}

const TimeSeriesChart: React.FC<TimeSeriesChartProps> = ({
  series,
  title,
  height = 400,
  theme = 'dark',
  showLegend = true,
  showDataZoom = true,
  yAxis = [],
  markPoints = [],
  markLines = [],
  onPointClick,
}) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  // 合并所有时间点
  const allTimes = useMemo(() => {
    const timeSet = new Set<number>()
    series.forEach(s => {
      s.data.forEach(point => {
        timeSet.add(point.time)
      })
    })
    return Array.from(timeSet).sort((a, b) => a - b)
  }, [series])

  // 时间格式化
  const formatTime = useCallback((timestamp: number) => {
    const date = new Date(timestamp)
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }, [])

  // 构建图表配置
  const option = useMemo<EChartsOption>(() => {
    const isDark = theme === 'dark'
    const bgColor = isDark ? '#1a1a2e' : '#ffffff'
    const textColor = isDark ? '#a0a0a0' : '#666666'
    const axisLineColor = isDark ? '#2a2a3e' : '#e0e0e0'

    const times = allTimes.map(formatTime)

    // 构建系列数据
    const chartSeries = series.map(s => {
      const dataMap = new Map(s.data.map(d => [d.time, d.value]))
      const data = allTimes.map(time => dataMap.get(time) ?? null)

      const seriesItem: any = {
        name: s.name,
        type: s.type === 'bar' ? 'bar' : 'line',
        data,
        yAxisIndex: s.yAxisIndex || 0,
        smooth: s.type !== 'bar',
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 2 },
        itemStyle: s.color ? { color: s.color } : undefined,
      }

      if (s.type === 'area') {
        seriesItem.areaStyle = { opacity: 0.3 }
      }

      // 添加标记点
      const mp = markPoints.find(m => m.seriesName === s.name)
      if (mp) {
        seriesItem.markPoint = {
          data: mp.points.map(p => ({
            name: p.name,
            coord: [formatTime(p.time), p.value],
            itemStyle: { color: '#ef5350' },
          })),
          symbol: 'pin',
          symbolSize: 40,
        }
      }

      // 添加标记线
      const ml = markLines.find(m => m.seriesName === s.name)
      if (ml) {
        seriesItem.markLine = {
          data: ml.lines.map(l => ({
            name: l.name,
            yAxis: l.value,
            lineStyle: { color: '#ffa726', type: 'dashed' },
            label: { formatter: l.name },
          })),
          symbol: 'none',
        }
      }

      return seriesItem
    })

    // 构建Y轴
    const yAxisConfig = yAxis.length > 0 ? yAxis : [{ name: '' }]
    const chartYAxis = yAxisConfig.map((axis, index) => ({
      type: 'value' as const,
      name: axis.name,
      nameTextStyle: { color: textColor },
      min: axis.min ?? 'dataMin',
      max: axis.max ?? 'dataMax',
      axisLine: { lineStyle: { color: axisLineColor } },
      axisLabel: { color: textColor },
      splitLine: {
        lineStyle: { color: axisLineColor, type: 'dashed' },
      },
      position: index === 0 ? 'left' : 'right',
    }))

    const baseOption: EChartsOption = {
      backgroundColor: bgColor,
      animation: false,
      title: title
        ? {
            text: title,
            left: 'center',
            top: 10,
            textStyle: { color: textColor, fontSize: 14 },
          }
        : undefined,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: isDark ? 'rgba(30, 30, 50, 0.9)' : 'rgba(255, 255, 255, 0.9)',
        textStyle: { color: isDark ? '#fff' : '#333' },
        formatter: (params: any) => {
          if (!Array.isArray(params)) return ''
          let html = `<div style="font-weight:bold">${params[0].axisValue}</div>`
          params.forEach((p: any) => {
            if (p.value !== null) {
              html += `<div>${p.marker} ${p.seriesName}: ${p.value?.toFixed(4) || '-'}</div>`
            }
          })
          return html
        },
      },
      legend: showLegend
        ? {
            data: series.map(s => s.name),
            bottom: 0,
            textStyle: { color: textColor },
          }
        : undefined,
      grid: {
        left: yAxisConfig.length > 1 ? '8%' : '5%',
        right: yAxisConfig.length > 1 ? '8%' : '5%',
        top: title ? '18%' : '10%',
        bottom: showLegend ? '15%' : '10%',
      },
      xAxis: {
        type: 'category',
        data: times,
        axisLine: { lineStyle: { color: axisLineColor } },
        axisLabel: { color: textColor, rotate: 45 },
        splitLine: { show: false },
      },
      yAxis: chartYAxis,
      series: chartSeries,
    }

    // 添加数据缩放
    if (showDataZoom) {
      (baseOption as any).dataZoom = [
        {
          type: 'inside',
          start: 80,
          end: 100,
        },
        {
          type: 'slider',
          start: 80,
          end: 100,
          bottom: showLegend ? '12%' : '3%',
          textStyle: { color: textColor },
          borderColor: axisLineColor,
          fillerColor: isDark ? 'rgba(64, 158, 255, 0.2)' : 'rgba(64, 158, 255, 0.1)',
          handleStyle: { color: '#409eff' },
        },
      ]
    }

    return baseOption
  }, [series, title, theme, showLegend, showDataZoom, yAxis, markPoints, markLines, allTimes, formatTime])

  // 初始化图表
  useEffect(() => {
    if (!chartRef.current) return

    chartInstance.current = echarts.init(chartRef.current, theme)

    // 点击事件
    if (onPointClick) {
      chartInstance.current.on('click', (params: any) => {
        if (params.componentType === 'series') {
          const time = allTimes[params.dataIndex]
          onPointClick({
            seriesName: params.seriesName,
            time,
            value: params.value,
          })
        }
      })
    }

    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [theme, onPointClick, allTimes])

  // 更新数据
  useEffect(() => {
    if (chartInstance.current) {
      chartInstance.current.setOption(option, true)
    }
  }, [option])

  // 响应式调整
  useEffect(() => {
    const handleResize = () => {
      chartInstance.current?.resize()
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return (
    <div
      ref={chartRef}
      style={{
        width: '100%',
        height: `${height}px`,
      }}
    />
  )
}

export default TimeSeriesChart
