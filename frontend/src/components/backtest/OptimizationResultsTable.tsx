import { memo, useMemo } from 'react'
import { Card, Row, Col, Statistic, Table, Badge, Tag, Tooltip, Typography } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import type { OptimizationResult, OptimizationResultItem } from '../../services/api'
import { METRIC_OPTIONS } from './BacktestConfigPanel'
import { fmt } from '../../utils/format'

const { Text } = Typography




interface OptimizationResultsTableProps {
  optResult: OptimizationResult
}

const OptimizationResultsTable = memo(function OptimizationResultsTable({
  optResult,
}: OptimizationResultsTableProps) {
  const optParamNames = useMemo(() =>
    optResult && optResult.top_results.length > 0
      ? Object.keys(optResult.top_results[0].params)
      : [] as string[]
  , [optResult])

  const optMetricLabel = useMemo(() =>
    optResult
      ? (METRIC_OPTIONS.find((m) => m.value === optResult.optimize_metric)?.label || optResult.optimize_metric)
      : ''
  , [optResult])

  const optColumns = useMemo(() => [
    { title: '#', dataIndex: 'rank', key: 'rank', width: 40, render: (_: any, __: any, i: number) => i + 1 },
    ...optParamNames.map((name) => ({
      title: name,
      dataIndex: ['params', name],
      key: name,
      width: 80,
      render: (v: number) => <Text strong>{v}</Text>,
    })),
    {
      title: <Tooltip title={optMetricLabel}>目标<i style={{ marginLeft: 4 }}>{optMetricLabel}</i></Tooltip>,
      key: 'target',
      width: 100,
      render: (_: any, record: OptimizationResultItem) => {
        const val = (record as any)[optResult?.optimize_metric ?? ''] ?? 0
        return (
          <Text style={{ color: '#1890ff' }} strong>
            {typeof val === 'number' ? fmt(val) : val}
          </Text>
        )
      },
    },
    { title: '总收益%', dataIndex: 'total_return_pct', key: 'ret', width: 90, render: (v: number) => fmt(v) },
    { title: '年化%', dataIndex: 'annual_return_pct', key: 'ann', width: 80, render: (v: number) => fmt(v) },
    { title: '最大回撤%', dataIndex: 'max_drawdown_pct', key: 'mdd', width: 90, render: (v: number) => <Text style={{ color: '#faad14' }}>{fmt(v)}</Text> },
    { title: 'Sharpe', dataIndex: 'sharpe_ratio', key: 'sharpe', width: 80, render: (v: number) => fmt(v, 3) },
    { title: '胜率%', dataIndex: 'win_rate', key: 'win', width: 70, render: (v: number) => fmt(v, 1) },
    { title: '交易次数', dataIndex: 'total_trades', key: 'trades', width: 70 },
    { title: 'Sortino', dataIndex: 'sortino_ratio', key: 'sortino', width: 80, render: (v: number) => fmt(v, 3) },
    { title: 'Calmar', dataIndex: 'calmar_ratio', key: 'calmar', width: 80, render: (v: number) => fmt(v) },
  ], [optParamNames, optMetricLabel, optResult])

  if (!optResult || optResult.top_results.length === 0) return null

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Badge count={optResult.total_combinations} style={{ backgroundColor: '#1890ff' }} />
            <Text style={{ marginLeft: 8 }}>种参数组合已测试</Text>
          </Col>
          <Col>
            <Tag icon={<ThunderboltOutlined />} color="blue">
              优化目标: {optMetricLabel}
            </Tag>
          </Col>
          <Col>
            <Text type="secondary">
              执行耗时: {fmt((optResult.execution_time_ms ?? 0) / 1000, 1)}s
            </Text>
          </Col>
          <Col>
            <Text type="secondary">
              最优参数: {Object.entries(optResult.best_params)
                .map(([k, v]) => `${k}=${v}`)
                .join(', ')}
            </Text>
          </Col>
        </Row>
      </Card>

      {/* 最优绩效 */}
      {optResult.best_metrics && (
        <Card title="最优参数绩效" size="small" style={{ marginBottom: 12 }}>
          <Row gutter={[16, 16]}>
            <Col span={4}>
              <Statistic title="总收益率" value={optResult.best_metrics.total_return_pct} suffix="%" precision={2}
                valueStyle={{ color: optResult.best_metrics.total_return_pct >= 0 ? '#cf1322' : '#389e0d' }} />
            </Col>
            <Col span={4}>
              <Statistic title="年化收益率" value={optResult.best_metrics.annual_return_pct} suffix="%" precision={2} />
            </Col>
            <Col span={4}>
              <Statistic title="最大回撤" value={optResult.best_metrics.max_drawdown_pct} suffix="%" precision={2} valueStyle={{ color: '#faad14' }} />
            </Col>
            <Col span={4}>
              <Statistic title="Sharpe" value={optResult.best_metrics.sharpe_ratio} precision={3} />
            </Col>
            <Col span={4}>
              <Statistic title="胜率" value={optResult.best_metrics.win_rate} suffix="%" precision={1} />
            </Col>
            <Col span={4}>
              <Statistic title="Sortino" value={optResult.best_metrics.sortino_ratio} precision={3} />
            </Col>
          </Row>
        </Card>
      )}

      {/* 参数组合排名表 */}
      <Card title={`Top ${optResult.top_results.length} 参数组合排名`} size="small">
        <Table
          dataSource={optResult.top_results}
          rowKey={(_: any, i: number | undefined) => String(i ?? 0)}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={optColumns}
          scroll={{ x: optParamNames.length * 80 + 800, y: 350 }} virtual
        />
      </Card>
    </>
  )
})

export default OptimizationResultsTable
