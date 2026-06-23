import { useState, useEffect, useCallback } from 'react'
import { Card, Tabs, Spin, Alert, Statistic, Row, Col, Table, Empty } from 'antd'
import { BarChartOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons'
import type { TabsProps } from 'antd'

const STRATEGY_KEYS = [
  { key: 'xuanji_twelve', label: '璇玑十二因子' },
  { key: 'xibu_seven', label: '西部七维' },
  { key: 'fusion', label: '融合策略' },
]

interface BacktestResult {
  strategy_id: string
  strategy_name: string
  optimal_params: Record<string, any>
  data_source: string
  total_rows: number
  n_dates: number
  error?: string
  result?: {
    returns: number
    benchmark_returns: number
    excess_returns: number
    max_drawdown: number
    sharpe_ratio: number
    win_rate: number
    trade_count: number
    total_cost: number
    turnover_rate: number
    daily_values?: { date: string; value: number; cash: number; positions: number }[]
    trades?: { date: string; code: string; action: string; price: number; quantity: number; cost: number }[]
  }
}

export default function BacktestResults() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, BacktestResult>>({})
  const [activeKey, setActiveKey] = useState('xuanji_twelve')

  const fetchResults = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/v1/backtest-results/strategy-results')
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`HTTP ${res.status}: ${text}`)
      }
      const data = await res.json()
      setResults(data.results || {})
    } catch (e: any) {
      setError(e.message || '加载回测结果失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchResults()
  }, [fetchResults])

  const renderResult = (result: BacktestResult | undefined) => {
    if (!result) {
      return <Empty description="暂无数据" />
    }
    if (result.error) {
      return <Alert type="error" message={result.error} />
    }
    if (!result.result) {
      return <Empty description="回测结果为空" />
    }

    const r = result.result
    const profitColor = (r.returns || 0) >= 0 ? '#cf1322' : '#3f8600'

    return (
      <div>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="总收益率"
                value={r.returns || 0}
                precision={2}
                suffix="%"
                prefix={(r.returns || 0) >= 0 ? <RiseOutlined /> : <FallOutlined />}
                valueStyle={{ color: profitColor }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="超额收益"
                value={r.excess_returns || 0}
                precision={2}
                suffix="%"
                valueStyle={{ color: (r.excess_returns || 0) >= 0 ? '#cf1322' : '#3f8600' }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="夏普比率"
                value={r.sharpe_ratio || 0}
                precision={2}
                valueStyle={{ color: (r.sharpe_ratio || 0) >= 0 ? '#cf1322' : '#3f8600' }}
              />
            </Card>
          </Col>
        </Row>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="最大回撤"
                value={r.max_drawdown || 0}
                precision={2}
                suffix="%"
                valueStyle={{ color: '#e74c3c' }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="胜率"
                value={r.win_rate || 0}
                precision={2}
                suffix="%"
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="交易次数"
                value={r.trade_count || 0}
                precision={0}
              />
            </Card>
          </Col>
        </Row>
        <Card size="small" title="策略参数" style={{ marginBottom: 16 }}>
          <Table
            dataSource={Object.entries(result.optimal_params || {}).map(([k, v]) => ({ key: k, param: k, value: v }))}
            columns={[
              { title: '参数', dataIndex: 'param', key: 'param' },
              { title: '值', dataIndex: 'value', key: 'value', render: (v: any) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(2) : String(v) },
            ]}
            pagination={false}
            size="small"
          />
        </Card>
        {r.trades && r.trades.length > 0 && (
          <Card size="small" title="最近交易" style={{ marginBottom: 16 }}>
            <Table
              dataSource={r.trades.slice(0, 20).map((t, i) => ({ ...t, key: i }))}
              columns={[
                { title: '日期', dataIndex: 'date', key: 'date', width: 100 },
                { title: '代码', dataIndex: 'code', key: 'code', width: 80 },
                { title: '操作', dataIndex: 'action', key: 'action', width: 60, render: (v: string) => <span style={{ color: v === 'buy' ? '#cf1322' : '#3f8600' }}>{v === 'buy' ? '买入' : '卖出'}</span> },
                { title: '价格', dataIndex: 'price', key: 'price', width: 80, render: (v: number) => v?.toFixed(2) },
                { title: '数量', dataIndex: 'quantity', key: 'quantity', width: 80 },
              ]}
              pagination={false}
              size="small"
              scroll={{ y: 240 }}
            />
          </Card>
        )}
      </div>
    )
  }

  const items: TabsProps['items'] = STRATEGY_KEYS.map((s) => ({
    key: s.key,
    label: s.label,
    children: renderResult(results[s.key]),
  }))

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={
          <span>
            <BarChartOutlined style={{ marginRight: 8 }} />
            三大策略回测情况
          </span>
        }
        extra={
          <span style={{ color: '#999', fontSize: 12 }}>
            回测区间: 2020-01-01 至今
          </span>
        }
      >
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        <Spin spinning={loading} tip="加载回测结果...">
          <Tabs activeKey={activeKey} onChange={setActiveKey} items={items} />
        </Spin>
      </Card>
    </div>
  )
}
