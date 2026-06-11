import React, { useMemo } from 'react'
import { Card, Button, Empty } from 'antd'
import { LineChartOutlined, ExportOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import type { FundPoint } from '../../stores/useTradeStore'
import { exportFundCurve } from '../../utils/export'

interface FundCurveProps {
  fundCurve: FundPoint[]
}

function FundCurve({ fundCurve }: FundCurveProps) {
  const fundCurveOption = useMemo(() => fundCurve.length > 0 ? {
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: any) => {
        const p = params[0]
        const point = fundCurve[p.dataIndex]
        if (!point) return ''
        return `
          <div>时间: ${point.ts}</div>
          <div>总资产: ${(point.total_asset ?? 0).toFixed(2)}</div>
          <div>现金: ${(point.cash ?? 0).toFixed(2)}</div>
          <div>市值: ${(point.market_value ?? 0).toFixed(2)}</div>
          <div>总盈亏: ${point.total_profit >= 0 ? '+' : ''}${(point.total_profit ?? 0).toFixed(2)}</div>
        `
      },
    },
    legend: { data: ['总资产', '现金'], top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: fundCurve.map((p: FundPoint) => p.ts.slice(5, 16)),
      axisLabel: { fontSize: 10, rotate: 30 },
    },
    yAxis: { type: 'value' as const, name: '金额' },
    series: [
      {
        name: '总资产',
        type: 'line',
        data: fundCurve.map((p: FundPoint) => p.total_asset),
        smooth: true,
        lineStyle: { color: '#1890ff', width: 2 },
        areaStyle: { color: 'rgba(24,144,255,0.1)' },
        showSymbol: false,
      },
      {
        name: '现金',
        type: 'line',
        data: fundCurve.map((p: FundPoint) => p.cash),
        smooth: true,
        lineStyle: { color: '#52c41a', width: 1.5, type: 'dashed' },
        showSymbol: false,
      },
    ],
  } : null, [fundCurve])

  return (
    <Card
      size="small"
      title={<span><LineChartOutlined /> 资金曲线</span>}
      extra={
        fundCurve.length > 0 && (
          <Button size="small" icon={<ExportOutlined />} onClick={() => exportFundCurve(fundCurve)}>导出</Button>
        )
      }
    >
      {fundCurve.length > 1 ? (
        fundCurveOption && <ReactEChartsCore echarts={echarts} option={fundCurveOption} style={{ height: 280 }} />
      ) : (
        <Empty description="暂无资金曲线数据" style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default React.memo(FundCurve)
