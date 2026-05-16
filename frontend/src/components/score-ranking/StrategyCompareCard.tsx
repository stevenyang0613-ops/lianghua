import React, { useMemo } from 'react'
import { Card, Table, Tag, Empty, Button, Space, Tooltip, Progress, Typography } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import type { StrategyResult, StrategyCompareCardProps } from './types'

const { Text } = Typography

export default React.memo(function StrategyCompareCard({
  strategyResults, strategyLoading, onRunStrategyCompare,
}: StrategyCompareCardProps) {
  const columns = useMemo(() => [
    { title: '策略名称', dataIndex: 'name', width: 120, render: (v: string) => <Text strong>{v}</Text> },
    { title: '累计收益', dataIndex: 'cumulative_return', width: 100, sorter: (a: StrategyResult, b: StrategyResult) => a.cumulative_return - b.cumulative_return, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600', fontWeight: 'bold' }}>{v?.toFixed(2)}%</span> },
    { title: '平均收益', dataIndex: 'avg_return_pct', width: 100, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v?.toFixed(2)}%</span> },
    { title: '平均胜率', dataIndex: 'avg_win_rate', width: 100, render: (v: number) => <Progress percent={v} size="small" /> },
    { title: '回测期数', dataIndex: 'total_periods', width: 80 },
    { title: '权重配置', key: 'weights', render: (_: unknown, r: StrategyResult) => (
      <Tooltip title={Object.entries(r.weights).map(([k, v]) => `${k}: ${v}`).join(', ')}>
        <Space size={2}>
          <Tag style={{ fontSize: 10 }}>双低{r.weights.dual_low}</Tag>
          <Tag style={{ fontSize: 10 }}>溢价{r.weights.premium}</Tag>
          <Tag style={{ fontSize: 10 }}>动量{r.weights.momentum}</Tag>
        </Space>
      </Tooltip>
    )},
  ], [])

  return (
    <Card size="small" title="策略对比分析" style={{ marginTop: 16 }} extra={
      <Button type="primary" size="small" icon={<BarChartOutlined />} onClick={onRunStrategyCompare} loading={strategyLoading}>对比策略</Button>
    }>
      {strategyResults && strategyResults.length > 0 ? (
        <Table dataSource={strategyResults} rowKey="name" size="small" pagination={false} columns={columns} scroll={{ x: 600 }} />
      ) : <Empty description="点击【对比策略】分析不同策略表现" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
    </Card>
  )
})
