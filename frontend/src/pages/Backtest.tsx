import { useState, useEffect } from 'react'
import { Card, Form, Select, InputNumber, DatePicker, Button, Row, Col, Statistic, Table, Spin, message, Typography, Space, Divider, Collapse, Tooltip } from 'antd'
import { PlayCircleOutlined, BarChartOutlined, ReloadOutlined, LineChartOutlined, TableOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchStrategies, runBacktest } from '../services/api'
import type { BacktestResult, StrategyInfo } from '../services/api'

const { Title, Text } = Typography
const { RangePicker } = DatePicker
const { Panel } = Collapse

export default function Backtest() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')
  const [strategyParams, setStrategyParams] = useState<Record<string, number>>({})
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs('2024-01-01'),
    dayjs('2024-12-31'),
  ])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [strategiesLoading, setStrategiesLoading] = useState(true)

  useEffect(() => {
    fetchStrategies()
      .then((list) => {
        setStrategies(list)
        if (list.length > 0) {
          setSelectedStrategy(list[0].id)
          const defaults: Record<string, number> = {}
          for (const p of list[0].params) {
            defaults[p.name] = p.default
          }
          setStrategyParams(defaults)
        }
      })
      .finally(() => setStrategiesLoading(false))
  }, [])

  const currentStrategy = strategies.find((s) => s.id === selectedStrategy)

  const handleStrategyChange = (id: string) => {
    setSelectedStrategy(id)
    setResult(null)
    const s = strategies.find((st) => st.id === id)
    if (s) {
      const defaults: Record<string, number> = {}
      for (const p of s.params) {
        defaults[p.name] = p.default
      }
      setStrategyParams(defaults)
    }
  }

  const handleRun = async () => {
    if (!selectedStrategy || !dateRange[0] || !dateRange[1]) return
    setLoading(true)
    setResult(null)
    try {
      const res = await runBacktest({
        strategy: selectedStrategy,
        params: strategyParams,
        start_date: dateRange[0].format('YYYY-MM-DD'),
        end_date: dateRange[1].format('YYYY-MM-DD'),
      })
      setResult(res)
      message.success('回测完成')
    } catch (e: any) {
      message.error('回测失败: ' + (e.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  const equityOption = result
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
    : null

  return (
    <div style={{ padding: 16 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <BarChartOutlined /> 回测中心
      </Title>

      <Row gutter={16}>
        {/* 配置区 */}
        <Col span={7}>
          <Card title="策略配置" size="small" loading={strategiesLoading}>
            <Form layout="vertical" size="small">
              <Form.Item label="策略">
                <Select value={selectedStrategy} onChange={handleStrategyChange}>
                  {strategies.map((s) => (
                    <Select.Option key={s.id} value={s.id}>
                      {s.name}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>

              {currentStrategy?.description && (
                <Text
                  type="secondary"
                  style={{ fontSize: 12, display: 'block', marginBottom: 12 }}
                >
                  {currentStrategy.description}
                </Text>
              )}

              {currentStrategy?.params.map((p) => (
                <Form.Item key={p.name} label={p.label}>
                  <InputNumber
                    style={{ width: '100%' }}
                    min={p.min_val}
                    max={p.max_val}
                    value={strategyParams[p.name]}
                    onChange={(v) =>
                      setStrategyParams((prev) => ({
                        ...prev,
                        [p.name]: v ?? p.default,
                      }))
                    }
                  />
                </Form.Item>
              ))}

              <Form.Item label="回测区间">
                <RangePicker
                  style={{ width: '100%' }}
                  value={dateRange}
                  onChange={(dates) => {
                    if (dates && dates[0] && dates[1]) {
                      setDateRange([dates[0], dates[1]])
                    }
                  }}
                />
              </Form.Item>

              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleRun}
                loading={loading}
                block
              >
                运行回测
              </Button>
            </Form>
          </Card>
        </Col>

        {/* 结果区 */}
        <Col span={17}>
          {loading ? (
            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                height: 400,
              }}
            >
              <Spin size="large" tip="回测运行中..." />
            </div>
          ) : result ? (
            <>
              {/* 绩效指标卡片 */}
              <Card title="绩效指标" size="small" style={{ marginBottom: 12 }}>
                <Row gutter={[16, 16]}>
                  <Col span={6}>
                    <Statistic
                      title="总收益率"
                      value={result.metrics.total_return_pct}
                      suffix="%"
                      precision={2}
                      valueStyle={{
                        color:
                          result.metrics.total_return_pct >= 0
                            ? '#cf1322'
                            : '#389e0d',
                      }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="年化收益率"
                      value={result.metrics.annual_return_pct}
                      suffix="%"
                      precision={2}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="最大回撤"
                      value={result.metrics.max_drawdown_pct}
                      suffix="%"
                      precision={2}
                      valueStyle={{ color: '#faad14' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="Sharpe"
                      value={result.metrics.sharpe_ratio}
                      precision={3}
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="胜率"
                      value={result.metrics.win_rate}
                      suffix="%"
                      precision={1}
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="盈亏比"
                      value={result.metrics.profit_loss_ratio}
                      precision={2}
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="交易次数"
                      value={result.metrics.total_trades}
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="平均持有"
                      value={result.metrics.avg_hold_days}
                      suffix="天"
                      precision={1}
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="执行耗时"
                      value={result.execution_time_ms}
                      suffix="ms"
                    />
                  </Col>
                  <Col span={4}>
                    <Statistic
                      title="Calmar"
                      value={result.metrics.calmar_ratio}
                      precision={2}
                    />
                  </Col>
                </Row>
              </Card>

              {/* 净值曲线 */}
              <Card title="净值曲线" size="small" style={{ marginBottom: 12 }}>
                {equityOption && (
                  <ReactEChartsCore
                    option={equityOption}
                    style={{ height: 300 }}
                  />
                )}
              </Card>

              {/* 交易明细 */}
              <Collapse ghost>
                <Panel header={`交易明细 (${result.trades.length} 笔)`} key="1">
                  <Table
                    dataSource={result.trades.slice(0, 200)}
                    rowKey={(_, i) => String(i)}
                    size="small"
                    pagination={{ pageSize: 20, showSizeChanger: false }}
                    columns={[
                      {
                        title: '代码',
                        dataIndex: 'code',
                        width: 90,
                        fixed: 'left',
                      },
                      { title: '名称', dataIndex: 'name', width: 90 },
                      { title: '买入日', dataIndex: 'buy_date', width: 100 },
                      { title: '卖出日', dataIndex: 'sell_date', width: 100 },
                      {
                        title: '买入价',
                        dataIndex: 'buy_price',
                        width: 80,
                        render: (v: number) => v.toFixed(2),
                      },
                      {
                        title: '卖出价',
                        dataIndex: 'sell_price',
                        width: 80,
                        render: (v: number) => v.toFixed(2),
                      },
                      {
                        title: '收益率',
                        dataIndex: 'profit_pct',
                        width: 80,
                        render: (v: number) => (
                          <Text
                            style={{
                              color: v >= 0 ? '#cf1322' : '#389e0d',
                            }}
                          >
                            {v.toFixed(2)}%
                          </Text>
                        ),
                      },
                      { title: '持有天数', dataIndex: 'hold_days', width: 80 },
                      {
                        title: '原因',
                        dataIndex: 'reason',
                        width: 120,
                        ellipsis: true,
                      },
                    ]}
                    scroll={{ x: 820, y: 300 }}
                  />
                </Panel>
              </Collapse>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 100, color: '#999' }}>
              <LineChartOutlined style={{ fontSize: 48, marginBottom: 16 }} />
              <div style={{ fontSize: 16 }}>
                选择策略和参数，点击「运行回测」开始测试
              </div>
            </div>
          )}
        </Col>
      </Row>
    </div>
  )
}
