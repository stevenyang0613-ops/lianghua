/**
 * 深度图组件
 */
import React, { useRef, useEffect, useMemo } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

export interface DepthLevel {
  price: number
  quantity: number
}

export interface DepthData {
  bids: DepthLevel[] // 买单深度
  asks: DepthLevel[] // 卖单深度
  timestamp: number
}

export interface DepthChartProps {
  data: DepthData
  symbol: string
  height?: number
  theme?: 'light' | 'dark'
  showCumulative?: boolean
  pricePrecision?: number
  quantityPrecision?: number
}

const DepthChart: React.FC<DepthChartProps> = ({
  data,
  symbol,
  height = 400,
  theme = 'dark',
  showCumulative = true,
  pricePrecision = 2,
  quantityPrecision = 2,
}) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  // 处理深度数据
  const processedData = useMemo(() => {
    // 按价格排序
    const sortedBids = [...data.bids].sort((a, b) => b.price - a.price) // 从高到低
    const sortedAsks = [...data.asks].sort((a, b) => a.price - b.price) // 从低到高

    // 计算累计量
    let cumBidQty = 0
    const cumulativeBids = sortedBids.map(level => {
      cumBidQty += level.quantity
      return {
        price: level.price,
        quantity: level.quantity,
        cumulative: cumBidQty,
      }
    })

    let cumAskQty = 0
    const cumulativeAsks = sortedAsks.map(level => {
      cumAskQty += level.quantity
      return {
        price: level.price,
        quantity: level.quantity,
        cumulative: cumAskQty,
      }
    })

    // 找出中间价（最近的买卖价）
    const bestBid = sortedBids[0]?.price || 0
    const bestAsk = sortedAsks[0]?.price || 0
    const midPrice = (bestBid + bestAsk) / 2

    return {
      bids: cumulativeBids,
      asks: cumulativeAsks,
      midPrice,
      maxBidQty: cumBidQty,
      maxAskQty: cumAskQty,
    }
  }, [data])

  // 构建图表配置
  const option = useMemo<EChartsOption>(() => {
    const isDark = theme === 'dark'
    const bgColor = isDark ? '#1a1a2e' : '#ffffff'
    const textColor = isDark ? '#a0a0a0' : '#666666'
    const axisLineColor = isDark ? '#2a2a3e' : '#e0e0e0'
    const bidColor = '#26a69a'
    const askColor = '#ef5350'

    const bidPrices = processedData.bids.map(d => d.price.toFixed(pricePrecision))
    const bidQuantities = processedData.bids.map(d => d.quantity)
    const bidCumulative = processedData.bids.map(d => d.cumulative)

    const askPrices = processedData.asks.map(d => d.price.toFixed(pricePrecision))
    const askQuantities = processedData.asks.map(d => d.quantity)
    const askCumulative = processedData.asks.map(d => d.cumulative)

    const series: any[] = [
      {
        name: '买单量',
        type: 'bar',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: bidQuantities,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: bidColor },
            { offset: 1, color: 'rgba(38, 166, 154, 0.3)' },
          ]),
        },
        barWidth: '60%',
      },
      {
        name: '卖单量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 0,
        data: askQuantities,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: askColor },
            { offset: 1, color: 'rgba(239, 83, 80, 0.3)' },
          ]),
        },
        barWidth: '60%',
      },
    ]

    if (showCumulative) {
      series.push(
        {
          name: '买单累计',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 1,
          data: bidCumulative,
          smooth: true,
          lineStyle: { width: 2, color: bidColor },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: 'rgba(38, 166, 154, 0.1)' },
              { offset: 1, color: 'rgba(38, 166, 154, 0.3)' },
            ]),
          },
          symbol: 'none',
        },
        {
          name: '卖单累计',
          type: 'line',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: askCumulative,
          smooth: true,
          lineStyle: { width: 2, color: askColor },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: 'rgba(239, 83, 80, 0.3)' },
              { offset: 1, color: 'rgba(239, 83, 80, 0.1)' },
            ]),
          },
          symbol: 'none',
        }
      )
    }

    return {
      backgroundColor: bgColor,
      animation: false,
      title: {
        text: `${symbol} 深度图`,
        left: 'center',
        top: 10,
        textStyle: { color: textColor, fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: isDark ? 'rgba(30, 30, 50, 0.9)' : 'rgba(255, 255, 255, 0.9)',
        textStyle: { color: isDark ? '#fff' : '#333' },
        formatter: (params: any) => {
          const bidParam = params.find((p: any) => p.seriesName === '买单量')
          const askParam = params.find((p: any) => p.seriesName === '卖单量')
          let html = ''

          if (bidParam) {
            html += `<div style="color: ${bidColor}">买: ${bidParam.value.toFixed(quantityPrecision)}</div>`
          }
          if (askParam) {
            html += `<div style="color: ${askColor}">卖: ${askParam.value.toFixed(quantityPrecision)}</div>`
          }

          return html
        },
      },
      legend: {
        data: ['买单量', '卖单量', ...(showCumulative ? ['买单累计', '卖单累计'] : [])],
        bottom: 0,
        textStyle: { color: textColor },
      },
      grid: [
        {
          left: '3%',
          right: '52%',
          top: '15%',
          bottom: '15%',
        },
        {
          left: '52%',
          right: '3%',
          top: '15%',
          bottom: '15%',
        },
      ],
      xAxis: [
        {
          type: 'category',
          data: bidPrices.reverse(),
          axisLine: { lineStyle: { color: axisLineColor } },
          axisLabel: {
            color: textColor,
            rotate: 45,
            fontSize: 10,
          },
          splitLine: { show: false },
        },
        {
          type: 'category',
          data: askPrices,
          gridIndex: 1,
          axisLine: { lineStyle: { color: axisLineColor } },
          axisLabel: {
            color: textColor,
            rotate: 45,
            fontSize: 10,
          },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          type: 'value',
          axisLine: { lineStyle: { color: axisLineColor } },
          axisLabel: { color: textColor, fontSize: 10 },
          splitLine: { lineStyle: { color: axisLineColor, type: 'dashed' } },
        },
        {
          type: 'value',
          axisLine: { show: false },
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      ],
      series,
    }
  }, [processedData, symbol, theme, showCumulative, pricePrecision, quantityPrecision])

  // 初始化图表
  useEffect(() => {
    if (!chartRef.current) return

    chartInstance.current = echarts.init(chartRef.current, theme)

    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [theme])

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

export default DepthChart
