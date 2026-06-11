import React, { useMemo } from 'react'
import { Card, Row, Col, DatePicker, InputNumber, Button, Statistic, Progress, Table, Tag, Empty, Space, Typography } from 'antd'
import { ThunderboltOutlined, TrophyOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { BacktestPanelProps } from './types'
import BacktestChartCard from './BacktestChartCard'
import StrategyCompareCard from './StrategyCompareCard'
import RiskAnalysisCard from './RiskAnalysisCard'

const { Text } = Typography

const scoreColor = (v: number) => {
  if (v >= 0.7) return '#52c41a'
  if (v >= 0.5) return '#1677ff'
  if (v >= 0.3) return '#faad14'
  return '#ff4d4f'
}

export default React.memo(function BacktestPanel({
  backtestParams, backtestLoading, backtestResults, backtestSummary,
  backtestChartData, topPerformers, performersSummary,
  strategyResults, strategyLoading, riskMetrics, riskLoading,
  onParamsChange, onRunBacktest, onLoadTopPerformers,
  onRunStrategyCompare, onRunRiskAnalysis,
}: BacktestPanelProps) {
  const backtestColumns = useMemo(() => [
    { title: '开始日期', dataIndex: 'date', width: 120 },
    { title: '结束日期', dataIndex: 'end_date', width: 120 },
    { title: '标的数', dataIndex: 'top_n', width: 80 },
    { title: '平均收益', dataIndex: 'avg_return_pct', width: 100, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v?.toFixed(2)}%</span> },
    { title: '胜率', dataIndex: 'win_rate', width: 100, render: (v: number) => <Progress percent={v} size="small" strokeColor={v >= 50 ? '#52c41a' : '#ff4d4f'} /> },
    { title: '最高收益', dataIndex: 'max_return', width: 100, render: (v: number) => <Tag color="red">{v?.toFixed(2)}%</Tag> },
    { title: '最低收益', dataIndex: 'min_return', width: 100, render: (v: number) => <Tag color="green">{v?.toFixed(2)}%</Tag> },
  ], [])

  const performersColumns = useMemo(() => [
    { title: '排名', dataIndex: 'rank', width: 60, render: (v: number) => <Text strong style={{ color: v <= 5 ? '#faad14' : undefined }}>#{v}</Text> },
    { title: '代码', dataIndex: 'code', width: 100 },
    { title: '名称', dataIndex: 'name', width: 120 },
    { title: '评分', dataIndex: 'score', width: 80, render: (v: number) => <Text style={{ color: scoreColor(v) }}>{v?.toFixed(3)}</Text> },
    { title: '起始价', dataIndex: 'start_price', width: 80, render: (v: number) => v?.toFixed(2) },
    { title: '结束价', dataIndex: 'end_price', width: 80, render: (v: number) => v?.toFixed(2) },
    { title: '收益率', dataIndex: 'return_pct', width: 100, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v >= 0 ? '+' : ''}{v?.toFixed(2)}%</span> },
    { title: '结果', dataIndex: 'is_winner', width: 80, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '盈利' : '亏损'}</Tag> },
  ], [])

  return (
    <div style={{ padding: 16 }}>
      <Card size="small" title="回测参数" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={4}>
            <Text>开始日期</Text>
            <DatePicker value={dayjs(backtestParams.startDate)} onChange={d => onParamsChange({ ...backtestParams, startDate: d?.format('YYYY-MM-DD') || '' })} style={{ width: '100%' }} />
          </Col>
          <Col span={4}>
            <Text>结束日期</Text>
            <DatePicker value={dayjs(backtestParams.endDate)} onChange={d => onParamsChange({ ...backtestParams, endDate: d?.format('YYYY-MM-DD') || '' })} style={{ width: '100%' }} />
          </Col>
          <Col span={3}>
            <Text>Top N</Text>
            <InputNumber min={5} max={50} value={backtestParams.topN} onChange={v => onParamsChange({ ...backtestParams, topN: v ?? 20 })} style={{ width: '100%' }} />
          </Col>
          <Col span={3}>
            <Text>持有天数</Text>
            <InputNumber min={1} max={30} value={backtestParams.holdDays} onChange={v => onParamsChange({ ...backtestParams, holdDays: v ?? 5 })} style={{ width: '100%' }} />
          </Col>
          <Col span={4} style={{ display: 'flex', alignItems: 'flex-end' }}>
            <Space>
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={onRunBacktest} loading={backtestLoading}>运行回测</Button>
              <Button icon={<TrophyOutlined />} onClick={onLoadTopPerformers}>最佳表现</Button>
            </Space>
          </Col>
        </Row>
      </Card>
      {backtestSummary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}><Card size="small"><Statistic title="回测期数" value={backtestSummary.total_periods} suffix="期" /></Card></Col>
          <Col span={8}><Card size="small"><Statistic title="平均收益" value={backtestSummary.avg_return_pct?.toFixed(2)} suffix="%" valueStyle={{ color: backtestSummary.avg_return_pct >= 0 ? '#cf1322' : '#3f8600' }} /></Card></Col>
          <Col span={8}><Card size="small"><Statistic title="平均胜率" value={backtestSummary.avg_win_rate?.toFixed(1)} suffix="%" valueStyle={{ color: backtestSummary.avg_win_rate >= 50 ? '#52c41a' : '#ff4d4f' }} /></Card></Col>
        </Row>
      )}
      {performersSummary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}><Card size="small"><Statistic title="总标的数" value={performersSummary.total} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="盈利标的" value={performersSummary.winners} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="胜率" value={performersSummary.win_rate?.toFixed(1)} suffix="%" /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="平均收益" value={performersSummary.avg_return_pct?.toFixed(2)} suffix="%" /></Card></Col>
        </Row>
      )}
      <BacktestChartCard chartData={backtestChartData} />
      {backtestResults && backtestResults.length > 0 && (
        <Card size="small" title="回测结果">
          <Table dataSource={backtestResults} rowKey="date" size="small" pagination={{ pageSize: 10 }} columns={backtestColumns} scroll={{ x: 750 }} />
        </Card>
      )}
      {topPerformers && topPerformers.length > 0 && (
        <Card size="small" title="表现最佳标的" style={{ marginTop: 16 }}>
          <Table dataSource={topPerformers} rowKey="code" size="small" pagination={{ pageSize: 10 }} columns={performersColumns} scroll={{ x: 700 }} />
        </Card>
      )}
      {!backtestResults && !topPerformers && (
        <Empty description="请设置参数并运行回测" style={{ padding: 40 }} />
      )}

      <StrategyCompareCard strategyResults={strategyResults} strategyLoading={strategyLoading} onRunStrategyCompare={onRunStrategyCompare} />
      <RiskAnalysisCard riskMetrics={riskMetrics} riskLoading={riskLoading} onRunRiskAnalysis={onRunRiskAnalysis} />
    </div>
  )
})
