import { memo, useMemo } from 'react'
import { Card, Row, Col, Statistic, Table, Collapse, Skeleton, Spin, Typography, Alert } from 'antd'
import { BarChartOutlined, WarningOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import type { BacktestResult } from '../../services/api'
import { fmt } from '../../utils/format'

const { Text } = Typography
const { Panel } = Collapse




interface BacktestResultsPanelProps {
  result: BacktestResult | null
  loading: boolean
  optEnabled: boolean
  dataWarning?: string
}

const BacktestResultsPanel = memo(function BacktestResultsPanel({
  result,
  loading,
  optEnabled,
  dataWarning,
}: BacktestResultsPanelProps) {
  const equityOption = useMemo(() => result
    ? {
        tooltip: { trigger: 'axis' as const },
        grid: { left: 60, right: 20, top: 40, bottom: 40 },
        xAxis: {
          type: 'category' as const,
          data: result.equity_curve.map((e) => e.date),
          axisLabel: { rotate: 45, fontSize: 10 },
        },
        yAxis: {
          type: 'value' as const,
          name: '净值',
          axisLabel: { formatter: '{value}' },
        },
        series: [
          {
            type: 'line',
            data: result.equity_curve.map((e) => e.value),
            smooth: true,
            lineStyle: { color: '#1890ff', width: 2 },
            areaStyle: { color: 'rgba(24,144,255,0.1)' },
            showSymbol: false,
          },
        ],
      }
    : null, [result])

  const tradeColumns = useMemo(() => [
    { title: '代码', dataIndex: 'code', width: 90, fixed: 'left' as const },
    { title: '名称', dataIndex: 'name', width: 90 },
    { title: '买入日', dataIndex: 'buy_date', width: 100 },
    { title: '卖出日', dataIndex: 'sell_date', width: 100 },
    { title: '买入价', dataIndex: 'buy_price', width: 80, render: (v: number) => fmt(v) },
    { title: '卖出价', dataIndex: 'sell_price', width: 80, render: (v: number) => fmt(v) },
    {
      title: '收益率', dataIndex: 'profit_pct', width: 80,
      render: (v: number) => (
        <Text style={{ color: v == null ? undefined : (v >= 0 ? '#cf1322' : '#389e0d') }}>{fmt(v)}%</Text>
      ),
    },
    { title: '持有天数', dataIndex: 'hold_days', width: 80 },
    { title: '原因', dataIndex: 'reason', width: 120, ellipsis: true },
  ], [])

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <Card title="绩效指标" size="small" style={{ marginBottom: 12 }}>
          <Row gutter={[16, 16]}>
            {[1,2,3,4,5,6,7,8,9,10].map(i => <Col span={i <= 6 ? 4 : 3} key={i}><Skeleton active title={{ width: '80%' }} paragraph={{ rows: 1, width: '50%' }} /></Col>)}
          </Row>
        </Card>
        <Card title="净值曲线" size="small" style={{ marginBottom: 12 }}>
          <Skeleton.Node active style={{ width: '100%', height: 300 }}>
            <div />
          </Skeleton.Node>
        </Card>
        <Card title="交易明细" size="small">
          <Skeleton paragraph={{ rows: 5 }} active />
        </Card>
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Spin /> <Text type="secondary" style={{ marginLeft: 8 }}>{optEnabled ? '参数优化中...' : '回测运行中...'}</Text>
        </div>
      </div>
    )
  }

  if (!result) {
    return (
      <div style={{ textAlign: 'center', padding: 100, color: '#999' }}>
        <BarChartOutlined style={{ fontSize: 48, marginBottom: 16 }} />
        <div style={{ fontSize: 16 }}>
          选择策略和参数，点击「{optEnabled ? '运行参数优化' : '运行回测'}」开始测试
        </div>
      </div>
    )
  }

  return (
    <>
      {dataWarning && (
        <Alert
          message="数据不足"
          description={dataWarning}
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ marginBottom: 12 }}
        />
      )}
      {/* 绩效指标卡片 */}
      <Card title="绩效指标" size="small" style={{ marginBottom: 12 }}>
        <Row gutter={[16, 16]}>
          <Col span={8}>
            <Statistic title="总收益率" value={result.metrics.total_return_pct} suffix="%" precision={2}
              valueStyle={{ color: result.metrics.total_return_pct >= 0 ? '#cf1322' : '#389e0d' }} />
          </Col>
          <Col span={8}>
            <Statistic title="年化收益率" value={result.metrics.annual_return_pct} suffix="%" precision={2} />
          </Col>
          <Col span={8}>
            <Statistic title="最大回撤" value={result.metrics.max_drawdown_pct} suffix="%" precision={2} valueStyle={{ color: '#faad14' }} />
          </Col>
          <Col span={4}>
            <Statistic title="Sharpe" value={result.metrics.sharpe_ratio} precision={3} />
          </Col>
          <Col span={4}>
            <Statistic title="胜率" value={result.metrics.win_rate} suffix="%" precision={1} />
          </Col>
          <Col span={4}>
            <Statistic title="盈亏比" value={result.metrics.profit_loss_ratio} precision={2} />
          </Col>
          <Col span={4}>
            <Statistic title="交易次数" value={result.metrics.total_trades} />
          </Col>
          <Col span={4}>
            <Statistic title="平均持有" value={result.metrics.avg_hold_days} suffix="天" precision={1} />
          </Col>
          <Col span={4}>
            <Statistic title="执行耗时" value={result.execution_time_ms} suffix="ms" />
          </Col>
          <Col span={4}>
            <Statistic title="Calmar" value={result.metrics.calmar_ratio} precision={2} />
          </Col>
          <Col span={4}>
            <Statistic title="Sortino" value={result.metrics.sortino_ratio} precision={3} />
          </Col>
        </Row>
      </Card>

      {/* 数据来源 */}
      {result.strategy_name && (
        <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8 }}>
          数据来源: {result.strategy_name}
        </Typography.Text>
      )}

      {/* 净值曲线 */}
      <Card title="净值曲线" size="small" style={{ marginBottom: 12 }}>
        {equityOption && (
          <ReactEChartsCore echarts={echarts} option={equityOption} style={{ height: 300 }} />
        )}
      </Card>

      {/* 月度收益 */}
      {result.monthly_returns && result.monthly_returns.length > 0 && (
        <Card title="月度收益" size="small" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {result.monthly_returns.map((m, i) => (
              <div key={i} style={{ 
                padding: '4px 8px', 
                borderRadius: 4, 
                backgroundColor: m.return_pct >= 0 ? '#f6ffed' : '#fff2f0',
                fontSize: 12 
              }}>
                {m.year}-{String(m.month).padStart(2, '0')}: {m.return_pct >= 0 ? '+' : ''}{m.return_pct.toFixed(1)}%
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 交易明细 */}
      <Collapse ghost>
        <Panel header={`交易明细 (${result.trades.length} 笔)`} key="1">
          <Table
            dataSource={result.trades.slice(0, 200)}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            columns={tradeColumns}
            scroll={{ x: 820, y: 300 }} virtual
          />
        </Panel>
      </Collapse>
    </>
  )
})

export default BacktestResultsPanel
