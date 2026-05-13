import { useState, useEffect, useCallback } from 'react'
import { Card, Form, Select, InputNumber, DatePicker, Button, Row, Col, Statistic, Table, Spin, message, Typography, Space, Divider, Collapse, Switch, Input, Tag, Tooltip, Badge } from 'antd'
import { PlayCircleOutlined, BarChartOutlined, LineChartOutlined, ThunderboltOutlined, SettingOutlined, FundOutlined, ExperimentOutlined, ReloadOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchStrategies, runBacktest, runOptimization } from '../services/api'
import type { BacktestResult, StrategyInfo, BacktestConfig, OptimizationConfig, OptimizationParamRange, OptimizationResult, OptimizationResultItem } from '../services/api'

const { Title, Text } = Typography
const { RangePicker } = DatePicker
const { Panel } = Collapse

const DEFAULT_CONFIG: BacktestConfig = {
  commission_pct: 0.001,
  slippage_pct: 0.001,
  min_commission: 5,
  risk_free_rate: 0.02,
}

const METRIC_OPTIONS: { value: string; label: string }[] = [
  { value: 'sharpe_ratio', label: 'Sharpe比率' },
  { value: 'total_return_pct', label: '总收益率' },
  { value: 'annual_return_pct', label: '年化收益率' },
  { value: 'calmar_ratio', label: 'Calmar比率' },
  { value: 'sortino_ratio', label: 'Sortino比率' },
  { value: 'win_rate', label: '胜率' },
]

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
  const [optResult, setOptResult] = useState<OptimizationResult | null>(null)
  const [strategiesLoading, setStrategiesLoading] = useState(true)

  // ---- 交易成本参数 ----
  const [config, setConfig] = useState<BacktestConfig>({ ...DEFAULT_CONFIG })

  // ---- 参数优化状态 ----
  const [optEnabled, setOptEnabled] = useState(false)
  const [optMetric, setOptMetric] = useState('sharpe_ratio')
  const [optMaxIter, setOptMaxIter] = useState(100)
  const [optTopN, setOptTopN] = useState(10)
  const [optRanges, setOptRanges] = useState<OptimizationParamRange[]>([])

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

  // 切换策略时自动初始化优化范围
  const handleStrategyChange = (id: string) => {
    setSelectedStrategy(id)
    setResult(null)
    setOptResult(null)
    const s = strategies.find((st) => st.id === id)
    if (s) {
      const defaults: Record<string, number> = {}
      const ranges: OptimizationParamRange[] = []
      for (const p of s.params) {
        defaults[p.name] = p.default
        if (p.type === 'int' || p.type === 'float') {
          ranges.push({
            name: p.name,
            min_val: p.min_val ?? p.default * 0.5,
            max_val: p.max_val ?? p.default * 1.5,
            step: p.type === 'int' ? 1 : Math.round(((p.max_val ?? p.default * 2) - (p.min_val ?? p.default * 0.5)) / 5 * 100) / 100,
          })
        }
      }
      setStrategyParams(defaults)
      setOptRanges(ranges)
    }
  }

  // ---- 运行回测或优化 ----
  const handleRun = async () => {
    if (!selectedStrategy || !dateRange[0] || !dateRange[1]) return
    setLoading(true)
    setResult(null)
    setOptResult(null)

    const payload = {
      strategy: selectedStrategy,
      params: strategyParams,
      start_date: dateRange[0].format('YYYY-MM-DD'),
      end_date: dateRange[1].format('YYYY-MM-DD'),
      config,
      optimization: optEnabled
        ? {
            enabled: true,
            param_ranges: optRanges,
            optimize_metric: optMetric,
            max_iterations: optMaxIter,
            top_n: optTopN,
          } as OptimizationConfig
        : undefined,
    }

    try {
      if (optEnabled) {
        const res = await runOptimization(payload)
        setOptResult(res.result)
        message.success(`参数优化完成，共测试 ${res.result.total_combinations} 种组合`)
      } else {
        const res = await runBacktest(payload)
        setResult(res.result as BacktestResult)
        message.success('回测完成')
      }
    } catch (e: any) {
      message.error('失败: ' + (e.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  // ---- 净值和优化结果 ECharts 配置 ----
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

  // ---- 更新优化范围 ----
  const updateOptRange = useCallback((idx: number, field: keyof OptimizationParamRange, value: number) => {
    setOptRanges((prev) => {
      const next = [...prev]
      next[idx] = { ...next[idx], [field]: value }
      return next
    })
  }, [])

  // ---- 渲染优化结果表格 ----
  const renderOptResultsTable = () => {
    if (!optResult || optResult.top_results.length === 0) return null

    const metricLabel = METRIC_OPTIONS.find((m) => m.value === optResult.optimize_metric)?.label || optResult.optimize_metric

    // 从第一条结果提取参数名列表
    const paramNames = optResult.top_results.length > 0
      ? Object.keys(optResult.top_results[0].params)
      : []

    const columns = [
      { title: '#', dataIndex: 'rank', key: 'rank', width: 40, render: (_: any, __: any, i: number) => i + 1 },
      ...paramNames.map((name) => ({
        title: name,
        dataIndex: ['params', name],
        key: name,
        width: 80,
        render: (v: number) => <Text strong>{v}</Text>,
      })),
      {
        title: <Tooltip title={metricLabel}>目标<i style={{ marginLeft: 4 }}>{metricLabel}</i></Tooltip>,
        key: 'target',
        width: 100,
        render: (_: any, record: OptimizationResultItem) => {
          const val = (record as any)[optResult.optimize_metric] ?? 0
          return (
            <Text style={{ color: '#1890ff' }} strong>
              {typeof val === 'number' ? val.toFixed(2) : val}
            </Text>
          )
        },
      },
      { title: '总收益%', dataIndex: 'total_return_pct', key: 'ret', width: 90, render: (v: number) => v.toFixed(2) },
      { title: '年化%', dataIndex: 'annual_return_pct', key: 'ann', width: 80, render: (v: number) => v.toFixed(2) },
      { title: '最大回撤%', dataIndex: 'max_drawdown_pct', key: 'mdd', width: 90, render: (v: number) => <Text style={{ color: '#faad14' }}>{v.toFixed(2)}</Text> },
      { title: 'Sharpe', dataIndex: 'sharpe_ratio', key: 'sharpe', width: 80, render: (v: number) => v.toFixed(3) },
      { title: '胜率%', dataIndex: 'win_rate', key: 'win', width: 70, render: (v: number) => v.toFixed(1) },
      { title: '交易次数', dataIndex: 'total_trades', key: 'trades', width: 70 },
      { title: 'Sortino', dataIndex: 'sortino_ratio', key: 'sortino', width: 80, render: (v: number) => v.toFixed(3) },
      { title: 'Calmar', dataIndex: 'calmar_ratio', key: 'calmar', width: 80, render: (v: number) => v.toFixed(2) },
    ]

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
                优化目标: {metricLabel}
              </Tag>
            </Col>
            <Col>
              <Text type="secondary">
                执行耗时: {(optResult.execution_time_ms / 1000).toFixed(1)}s
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
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={{ pageSize: 10, showSizeChanger: false }}
            columns={columns}
            scroll={{ x: paramNames.length * 80 + 800, y: 350 }}
          />
        </Card>
      </>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <BarChartOutlined /> 回测中心
      </Title>

      <Row gutter={16}>
        {/* 配置区 */}
        <Col span={8}>
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
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
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
                      setStrategyParams((prev) => ({ ...prev, [p.name]: v ?? p.default }))
                    }
                  />
                </Form.Item>
              ))}

              <Form.Item label="回测区间">
                <RangePicker
                  style={{ width: '100%' }}
                  value={dateRange}
                  onChange={(dates) => {
                    if (dates && dates[0] && dates[1]) setDateRange([dates[0], dates[1]])
                  }}
                />
              </Form.Item>

              <Divider style={{ margin: '8px 0' }} />

              {/* 交易成本参数 */}
              <Collapse ghost style={{ marginBottom: 8 }}>
                <Panel header={<span><SettingOutlined /> 交易成本参数</span>} key="cost">
                  <Form.Item label="佣金率" tooltip="每笔交易佣金比例">
                    <InputNumber
                      style={{ width: '100%' }}
                      min={0} max={0.03}
                      step={0.0001}
                      value={config.commission_pct}
                      onChange={(v) => setConfig((prev) => ({ ...prev, commission_pct: v ?? 0.001 }))}
                    />
                  </Form.Item>
                  <Form.Item label="滑点率" tooltip="买卖价格滑点比例">
                    <InputNumber
                      style={{ width: '100%' }}
                      min={0} max={0.05}
                      step={0.0001}
                      value={config.slippage_pct}
                      onChange={(v) => setConfig((prev) => ({ ...prev, slippage_pct: v ?? 0.001 }))}
                    />
                  </Form.Item>
                  <Form.Item label="最低佣金(元)" tooltip="单笔最低佣金">
                    <InputNumber
                      style={{ width: '100%' }}
                      min={0}
                      value={config.min_commission}
                      onChange={(v) => setConfig((prev) => ({ ...prev, min_commission: v ?? 5 }))}
                    />
                  </Form.Item>
                  <Form.Item label="无风险利率" tooltip="年化无风险利率, 用于Sharpe/Sortino计算">
                    <InputNumber
                      style={{ width: '100%' }}
                      min={0} max={0.1}
                      step={0.005}
                      value={config.risk_free_rate}
                      onChange={(v) => setConfig((prev) => ({ ...prev, risk_free_rate: v ?? 0.02 }))}
                    />
                  </Form.Item>
                </Panel>
              </Collapse>

              {/* 参数优化开关 */}
              <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                <ExperimentOutlined />
                <Switch checked={optEnabled} onChange={setOptEnabled} checkedChildren="优化开" unCheckedChildren="优化关" />
                <Text type="secondary" style={{ fontSize: 12 }}>参数优化</Text>
              </div>

              {optEnabled && (
                <Collapse ghost defaultActiveKey="opt" style={{ marginBottom: 8 }}>
                  <Panel header={<span><ThunderboltOutlined /> 优化设置</span>} key="opt">
                    <Form.Item label="优化目标">
                      <Select value={optMetric} onChange={setOptMetric}>
                        {METRIC_OPTIONS.map((m) => (
                          <Select.Option key={m.value} value={m.value}>{m.label}</Select.Option>
                        ))}
                      </Select>
                    </Form.Item>
                    <Form.Item label="最大迭代">
                      <InputNumber style={{ width: '100%' }} min={1} max={10000} value={optMaxIter}
                        onChange={(v) => setOptMaxIter(v ?? 100)} />
                    </Form.Item>
                    <Form.Item label="Top N">
                      <InputNumber style={{ width: '100%' }} min={1} max={100} value={optTopN}
                        onChange={(v) => setOptTopN(v ?? 10)} />
                    </Form.Item>
                    <Divider style={{ margin: '8px 0' }} />
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                      参数搜索范围:
                    </Text>
                    {optRanges.map((r, idx) => (
                      <div key={r.name} style={{ marginBottom: 8, padding: 8, background: '#f5f5f5', borderRadius: 4 }}>
                        <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>{r.name}</Text>
                        <Row gutter={4}>
                          <Col span={8}>
                            <InputNumber size="small" style={{ width: '100%' }} placeholder="min"
                              value={r.min_val}
                              onChange={(v) => updateOptRange(idx, 'min_val', v ?? 0)} />
                          </Col>
                          <Col span={8}>
                            <InputNumber size="small" style={{ width: '100%' }} placeholder="max"
                              value={r.max_val}
                              onChange={(v) => updateOptRange(idx, 'max_val', v ?? 0)} />
                          </Col>
                          <Col span={8}>
                            <InputNumber size="small" style={{ width: '100%' }} placeholder="step"
                              value={r.step}
                              onChange={(v) => updateOptRange(idx, 'step', v ?? 1)} />
                          </Col>
                        </Row>
                      </div>
                    ))}
                  </Panel>
                </Collapse>
              )}

              <Button
                type="primary"
                icon={optEnabled ? <ThunderboltOutlined /> : <PlayCircleOutlined />}
                onClick={handleRun}
                loading={loading}
                block
              >
                {optEnabled ? '运行参数优化' : '运行回测'}
              </Button>
            </Form>
          </Card>
        </Col>

        {/* 结果区 */}
        <Col span={16}>
          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
              <Spin size="large" tip={optEnabled ? '参数优化中...' : '回测运行中...'} />
            </div>
          ) : optResult ? (
            renderOptResultsTable()
          ) : result ? (
            <>
              {/* 绩效指标卡片 */}
              <Card title="绩效指标" size="small" style={{ marginBottom: 12 }}>
                <Row gutter={[16, 16]}>
                  <Col span={6}>
                    <Statistic title="总收益率" value={result.metrics.total_return_pct} suffix="%" precision={2}
                      valueStyle={{ color: result.metrics.total_return_pct >= 0 ? '#cf1322' : '#389e0d' }} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="年化收益率" value={result.metrics.annual_return_pct} suffix="%" precision={2} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="最大回撤" value={result.metrics.max_drawdown_pct} suffix="%" precision={2} valueStyle={{ color: '#faad14' }} />
                  </Col>
                  <Col span={6}>
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
                </Row>
              </Card>

              {/* 净值曲线 */}
              <Card title="净值曲线" size="small" style={{ marginBottom: 12 }}>
                {equityOption && (
                  <ReactEChartsCore option={equityOption} style={{ height: 300 }} />
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
                      { title: '代码', dataIndex: 'code', width: 90, fixed: 'left' },
                      { title: '名称', dataIndex: 'name', width: 90 },
                      { title: '买入日', dataIndex: 'buy_date', width: 100 },
                      { title: '卖出日', dataIndex: 'sell_date', width: 100 },
                      { title: '买入价', dataIndex: 'buy_price', width: 80, render: (v: number) => v.toFixed(2) },
                      { title: '卖出价', dataIndex: 'sell_price', width: 80, render: (v: number) => v.toFixed(2) },
                      {
                        title: '收益率', dataIndex: 'profit_pct', width: 80,
                        render: (v: number) => (
                          <Text style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>{v.toFixed(2)}%</Text>
                        ),
                      },
                      { title: '持有天数', dataIndex: 'hold_days', width: 80 },
                      { title: '原因', dataIndex: 'reason', width: 120, ellipsis: true },
                    ]}
                    scroll={{ x: 820, y: 300 }}
                  />
                </Panel>
              </Collapse>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 100, color: '#999' }}>
              <BarChartOutlined style={{ fontSize: 48, marginBottom: 16 }} />
              <div style={{ fontSize: 16 }}>
                选择策略和参数，点击「{optEnabled ? '运行参数优化' : '运行回测'}」开始测试
              </div>
            </div>
          )}
        </Col>
      </Row>
    </div>
  )
}
