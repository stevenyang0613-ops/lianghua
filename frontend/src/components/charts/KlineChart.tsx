/**
 * K线图组件
 */

import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart'

export interface KlineData {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
}

export interface KlineChartProps {
  data: KlineData[]
  showVolume?: boolean
  showMA?: number[]
  height?: number | string
  loading?: boolean
}

export function KlineChart({
  data,
  showVolume = true,
  showMA = [5, 10, 20],
  height = 400,
  loading,
}: KlineChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const dates = data.map(d => d.date)
    const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
    const volumes = data.map(d => d.volume)

    // 计算 MA 线
    const maLines: Record<string, number[]> = {}
    for (const period of showMA) {
      maLines[`MA${period}`] = calculateMA(data, period)
    }

    const series: EChartsOption['series'] = [
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
    ]

    // 添加 MA 线
    for (const [name, values] of Object.entries(maLines)) {
      series.push({
        name,
        type: 'line',
        data: values,
        smooth: true,
        lineStyle: { width: 1 },
        symbol: 'none',
      })
    }

    // 添加成交量
    if (showVolume) {
      series.push({
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (params: any) => {
            const idx = params.dataIndex
            return data[idx].close >= data[idx].open ? '#ef5350' : '#26a69a'
          },
        },
      })
    }

    return {
      animation: false,
      legend: {
        data: ['K线', ...Object.keys(maLines), showVolume ? '成交量' : ''].filter(Boolean),
        top: 10,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(255, 255, 255, 0.9)',
        borderColor: '#ddd',
        borderWidth: 1,
        textStyle: { color: '#333' },
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
      },
      grid: showVolume ? [
        { left: '10%', right: '8%', top: '15%', height: '55%' },
        { left: '10%', right: '8%', top: '75%', height: '15%' },
      ] : [
        { left: '10%', right: '8%', top: '15%', bottom: '10%' },
      ],
      xAxis: showVolume ? [
        {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { onZero: false },
          splitLine: { show: false },
          axisLabel: { show: false },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          boundaryGap: false,
          axisLine: { onZero: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: true },
        },
      ] : [
        {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { onZero: false },
        },
      ],
      yAxis: showVolume ? [
        {
          scale: true,
          splitArea: { show: true },
        },
        {
          scale: true,
          gridIndex: 1,
          splitNumber: 2,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
        },
      ] : [
        {
          scale: true,
          splitArea: { show: true },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: showVolume ? [0, 1] : [0],
          start: 80,
          end: 100,
        },
        {
          show: true,
          xAxisIndex: showVolume ? [0, 1] : [0],
          type: 'slider',
          bottom: 10,
          start: 80,
          end: 100,
        },
      ],
      series,
    }
  }, [data, showVolume, showMA])

  return <BaseChart option={option} style={{ height }} loading={loading} />
}

function calculateMA(data: KlineData[], period: number): number[] {
  const result: number[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(NaN as unknown as number)
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j].close
      }
      result.push(+(sum / period).toFixed(2))
    }
  }
  return result
}

export default KlineChart
