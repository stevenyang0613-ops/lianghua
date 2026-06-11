/**
 * 璇玑十二因子指增策略页面
 *
 * 璇玑: 古代天文仪器，象征多维度精密分析
 * 12因子: 双低/HV/动量/YTM/期限/质量ROE/质量GPM/质量CAGR/估值PE/估值PB/事件/Delta
 * 5态市场: 极端牛/温和牛/震荡/温和熊/极端熊
 * Alpha源: A1-A12共12个alpha源
 * 目标: 中性年化12.8% / 乐观21.2% / 探索上限24%
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Slider, Select, Space, Button, Progress, Modal, Descriptions,
  Alert, Divider, Tabs, InputNumber, Tooltip, Badge
} from 'antd'
import {
  TrophyOutlined, ReloadOutlined, StarOutlined,
  ExperimentOutlined, ThunderboltOutlined, SafetyOutlined,
  InfoCircleOutlined, RiseOutlined, FallOutlined,
  LineChartOutlined, DashboardOutlined, FundOutlined
} from '@ant-design/icons'
import {
  fetchStrategies, runBacktest,
  type StrategyInfo, type BacktestResult
} from '../services/api'

const { Title, Text } = Typography

const STORAGE_KEY = 'xuanji_index_config'

const MARKET_STATES = [
  { value: 'extreme_bull', label: '极端牛', color: '#ff4d4f', icon: <RiseOutlined /> },
  { value: 'mild_bull', label: '温和牛', color: '#fa8c16', icon: <RiseOutlined /> },
  { value: 'neutral', label: '震荡', color: '#1677ff', icon: <ThunderboltOutlined /> },
  { value: 'mild_bear', label: '温和熊', color: '#52c41a', icon: <FallOutlined /> },
  { value: 'extreme_bear', label: '极端熊', color: '#389e0d', icon: <FallOutlined /> },
]

const ALPHA_SOURCES = [
  { id: 'A1', name: 'AI因子', range: '+1.5~2.5%', status: 'active' },
  { id: 'A2', name: '统计套利', range: '+1~2%', status: 'active' },
  { id: 'A3', name: 'CTA趋势', range: '+0.5~1.5%', status: 'active' },
  { id: 'A4', name: 'T+0高频', range: '+0.3~0.8%', status: 'active' },
  { id: 'A5', name: '事件驱动', range: '+1~2%', status: 'active' },
  { id: 'A6', name: '正股质量', range: '+0.5~1%', status: 'active' },
  { id: 'A7', name: '估值因子', range: '+0.5~1%', status: 'active' },
  { id: 'A8', name: '多时帧动量', range: '+0.3~0.8%', status: 'active' },
  { id: 'A9', name: 'Delta对冲', range: '+0.5~1.5%', status: 'active' },
  { id: 'A10', name: '尾部hedge', range: '回撤-2~4%', status: 'active' },
  { id: 'A11', name: 'Greeks分解', range: '精度提升', status: 'active' },
  { id: 'A12', name: '5态市场', range: '+0.3~0.5%', status: 'active' },
]

const FACTOR_GROUPS = [
  { group: '防守', factors: ['双低值', '历史波动率', '到期收益率', '剩余期限'], color: '#52c41a' },
  { group: '进攻', factors: ['多时帧动量', 'Delta对冲'], color: '#ff4d4f' },
  { group: '质量', factors: ['ROE', '毛利率', '复合增长率', '负债率', '流动比率'], color: '#1677ff' },
  { group: '估值', factors: ['市盈率', '市净率', 'IV-HV差'], color: '#faad14' },
  { group: '事件', factors: ['回购金额', '管理层增持', '下修概率', '强赎预警'], color: '#722ed1' },
]

const MARKET_WEIGHTS_DISPLAY = {
  extreme_bull: { dual_low: 15, momentum: 30, hv: 15, quality: 20, valuation: 10, ytm: 5, event: 3, delta: 2 },
  mild_bull:    { dual_low: 25, momentum: 25, hv: 15, quality: 15, valuation: 10, ytm: 5, event: 3, delta: 2 },
  neutral:      { dual_low: 30, momentum: 10, hv: 20, quality: 20, valuation: 10, ytm: 5, event: 3, delta: 2 },
  mild_bear:    { dual_low: 40, momentum: 5, hv: 25, quality: 15, valuation: 10, ytm: 0, event: 3, delta: 2 },
  extreme_bear: { dual_low: 50, momentum: 0, hv: 30, quality: 10, valuation: 5, ytm: 0, event: 3, delta: 2 },
}

const WEIGHT_LABELS: Record<string, string> = {
  dual_low: '双低', momentum: '动量', hv: 'HV', quality: '质量',
  valuation: '估值', ytm: 'YTM', event: '事件', delta: 'Delta'
}

function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return { topN: 50, marketState: 'mild_bull', holdCount: 20, rebalanceDays: 20 }
}

function saveConfig(config: any) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(config)) } catch { /* ignore */ }
}

export default function XuanjiIndex() {
  const savedConfig = useMemo(() => loadConfig(), [])

  const [loading, setLoading] = useState(false)
  const [topN, setTopN] = useState(savedConfig.topN)
  const [marketState, setMarketState] = useState(savedConfig.marketState)
  const [holdCount, setHoldCount] = useState(savedConfig.holdCount)
  const [rebalanceDays, setRebalanceDays] = useState(savedConfig.rebalanceDays)

  // Backtest states
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null)
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [btStartDate, setBtStartDate] = useState('2024-01-01')
  const [btEndDate, setBtEndDate] = useState('2025-12-31')

  // Active tab
  const [activeTab, setActiveTab] = useState('ranking')

  // Mock ranking data (will be replaced by API call)
  const [rankingData, setRankingData] = useState<any[]>([])

  const marketStateConfig = MARKET_STATES.find(s => s.value === marketState) || MARKET_STATES[1]
  const currentWeights = MARKET_WEIGHTS_DISPLAY[marketState as keyof typeof MARKET_WEIGHTS_DISPLAY]

  // Fetch strategies for backtest
  useEffect(() => {
    fetchStrategies().then(setStrategies).catch(() => {})
  }, [])

  // Run backtest
  const handleRunBacktest = useCallback(async () => {
    setBacktestLoading(true)
    try {
      const result = await runBacktest({
        strategy: 'xuanji_twelve',
        params: {
          hold_count: holdCount,
          rebalance_days: rebalanceDays,
          market_state: marketState,
        },
        start_date: btStartDate,
        end_date: btEndDate,
        config: { commission_pct: 0.001, slippage_pct: 0.001, min_commission: 5, risk_free_rate: 0.02 },
      })
      if (result.type === 'backtest') {
        setBacktestResult(result.result as BacktestResult)
        message.success('回测完成')
      }
    } catch (e: any) {
      message.error(`回测失败: ${e.message}`)
    } finally {
      setBacktestLoading(false)
    }
  }, [holdCount, rebalanceDays, marketState, btStartDate, btEndDate])

  // Save config on change
  useEffect(() => {
    saveConfig({ topN, marketState, holdCount, rebalanceDays })
  }, [topN, marketState, holdCount, rebalanceDays])

  const scoreColor = (v: number, max: number = 100) => {
    const ratio = v / max
    if (ratio >= 0.8) return '#52c41a'
    if (ratio >= 0.6) return '#1677ff'
    if (ratio >= 0.4) return '#faad14'
    return '#ff4d4f'
  }

  const rankingColumns = [
    {
      title: '排名', dataIndex: 'rank', key: 'rank', width: 60,
      render: (rank: number) => (
        <span style={{ fontWeight: 'bold', color: rank <= 10 ? '#faad14' : undefined }}>
          {rank <= 3 ? <TrophyOutlined style={{ color: '#faad14', marginRight: 4 }} /> : null}{rank}
        </span>
      ),
    },
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    {
      title: '价格', dataIndex: 'price', key: 'price', width: 80,
      render: (v: number) => <Text style={{ color: v < 100 ? '#52c41a' : v > 130 ? '#ff4d4f' : undefined }}>{v?.toFixed(2)}</Text>,
    },
    {
      title: '溢价率', dataIndex: 'premium_ratio', key: 'premium_ratio', width: 80,
      render: (v: number) => <Text style={{ color: v < 20 ? '#52c41a' : v > 50 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text>,
    },
    {
      title: '双低值', dataIndex: 'dual_low', key: 'dual_low', width: 80,
      render: (v: number) => <Text style={{ color: v < 130 ? '#52c41a' : v > 160 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}</Text>,
    },
    {
      title: 'HV', dataIndex: 'hv', key: 'hv', width: 70,
      render: (v: number) => <Text style={{ color: v < 20 ? '#52c41a' : v > 40 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text>,
    },
    {
      title: '综合评分', dataIndex: 'score', key: 'score', width: 120,
      sorter: (a: any, b: any) => a.score - b.score,
      render: (v: number) => <Progress percent={Math.min(v * 100, 100)} size="small" strokeColor={scoreColor(v * 100)} format={(p) => p?.toFixed(1)} />,
    },
  ]

  const backtestMetrics = backtestResult?.metrics

  return (
    <div style={{ padding: 16 }}>
      <Card>
        <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col>
            <Title level={4} style={{ margin: 0 }}>
              <StarOutlined style={{ marginRight: 8, color: '#722ed1' }} />
              璇玑十二因子指增策略
              <Tag color="purple" style={{ marginLeft: 8 }}>v3.0</Tag>
            </Title>
            <Text type="secondary" style={{ fontSize: 12 }}>
              12因子 × 5态市场 × 12 Alpha源 | 中性12.8% / 乐观21.2% / 探索24%
            </Text>
          </Col>
          <Col>
            <Space>
              <Tag icon={marketStateConfig.icon} color={marketStateConfig.color}>
                {marketStateConfig.label}
              </Tag>
              <Button icon={<ReloadOutlined />} onClick={() => message.info('数据刷新')} loading={loading}>
                刷新
              </Button>
            </Space>
          </Col>
        </Row>

        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'ranking',
            label: <span><TrophyOutlined /> 十二因子排名</span>,
            children: (
              <>
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Row gutter={24}>
                    <Col span={6}>
                      <Text>返回前N名</Text>
                      <Slider min={10} max={100} value={topN} onChange={setTopN} marks={{ 10: '10', 50: '50', 100: '100' }} />
                    </Col>
                    <Col span={6}>
                      <Text>市场状态</Text>
                      <Select style={{ width: '100%' }} value={marketState} onChange={setMarketState}
                        options={MARKET_STATES.map(s => ({ value: s.value, label: <span>{s.icon} {s.label}</span> }))} />
                    </Col>
                    <Col span={6}>
                      <Text>持有数量</Text>
                      <InputNumber min={5} max={50} value={holdCount} onChange={v => setHoldCount(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={6}>
                      <Text>调仓间隔(天)</Text>
                      <InputNumber min={5} max={60} value={rebalanceDays} onChange={v => setRebalanceDays(v || 20)} style={{ width: '100%' }} />
                    </Col>
                  </Row>
                </Card>

                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={4}><Statistic title="筛选池" value={168} suffix="只" /></Col>
                  <Col span={4}><Statistic title="三层漏斗" value="168→125→74→50" /></Col>
                  <Col span={4}><Statistic title="当前市场" value={marketStateConfig.label} valueStyle={{ color: marketStateConfig.color }} /></Col>
                  <Col span={4}><Statistic title="中性年化" value="12.8%" valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={4}><Statistic title="乐观年化" value="21.2%" valueStyle={{ color: '#1677ff' }} /></Col>
                  <Col span={4}><Statistic title="IC衰减" value="×0.85" /></Col>
                </Row>

                <Alert
                  message="璇玑十二因子评分体系"
                  description="防守(双低+HV+YTM+期限) + 进攻(动量+Delta) + 质量(ROE+GPM+CAGR+负债率+流动比) + 估值(PE+PB+IV-HV) + 事件(回购+增持+下修+强赎)，5态市场自适应权重"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />

                <Spin spinning={loading}>
                  {rankingData.length > 0 ? (
                    <Table dataSource={rankingData} columns={rankingColumns} rowKey="code" size="small"
                      pagination={{ pageSize: 20, showSizeChanger: true }} scroll={{ x: 900 }} />
                  ) : (
                    <Empty description="点击刷新加载数据" />
                  )}
                </Spin>
              </>
            ),
          },
          {
            key: 'weights',
            label: <span><DashboardOutlined /> 5态权重</span>,
            children: (
              <>
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Text>选择市场状态查看权重分配: </Text>
                  <Select style={{ width: 200, marginLeft: 8 }} value={marketState} onChange={setMarketState}
                    options={MARKET_STATES.map(s => ({ value: s.value, label: `${s.label}` }))} />
                </Card>
                <Row gutter={[16, 16]}>
                  {MARKET_STATES.map(state => {
                    const w = MARKET_WEIGHTS_DISPLAY[state.value as keyof typeof MARKET_WEIGHTS_DISPLAY]
                    const isActive = state.value === marketState
                    return (
                      <Col span={8} key={state.value}>
                        <Card size="small" style={{ border: isActive ? `2px solid ${state.color}` : undefined }}>
                          <Title level={5} style={{ color: state.color, margin: 0 }}>
                            {state.icon} {state.label}
                            {isActive && <Tag color="blue" style={{ marginLeft: 8 }}>当前</Tag>}
                          </Title>
                          <Divider style={{ margin: '8px 0' }} />
                          <Row gutter={[8, 8]}>
                            {Object.entries(w).map(([key, val]) => (
                              <Col span={6} key={key}>
                                <Statistic title={WEIGHT_LABELS[key] || key} value={val} suffix="%" 
                                  valueStyle={{ fontSize: 14, color: val > 20 ? state.color : undefined }} />
                              </Col>
                            ))}
                          </Row>
                        </Card>
                      </Col>
                    )
                  })}
                </Row>
                <Divider>因子分组</Divider>
                <Row gutter={[16, 16]}>
                  {FACTOR_GROUPS.map(g => (
                    <Col span={4} key={g.group}>
                      <Card size="small">
                        <Title level={5} style={{ color: g.color, margin: 0 }}>{g.group}</Title>
                        <div style={{ marginTop: 8 }}>
                          {g.factors.map(f => (
                            <Tag key={f} color={g.color} style={{ marginBottom: 4 }}>{f}</Tag>
                          ))}
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </>
            ),
          },
          {
            key: 'alpha',
            label: <span><FundOutlined /> Alpha源</span>,
            children: (
              <>
                <Alert
                  message="12个Alpha源叠加"
                  description="A1-A5(基础5大alpha) + A6-A12(新增7大alpha) = 总增厚+6.1~12.8%/年"
                  type="success" showIcon style={{ marginBottom: 16 }}
                />
                <Row gutter={[16, 16]}>
                  {ALPHA_SOURCES.map(a => (
                    <Col span={4} key={a.id}>
                      <Card size="small" hoverable>
                        <Statistic title={a.id} value={a.name}
                          valueStyle={{ fontSize: 14, color: a.status === 'active' ? '#52c41a' : '#999' }} />
                        <Text type="secondary" style={{ fontSize: 12 }}>{a.range}</Text>
                        <div style={{ marginTop: 4 }}>
                          <Badge status={a.status === 'active' ? 'success' : 'default'} text={a.status === 'active' ? '已启用' : '未启用'} />
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
                <Divider>收益增厚路径</Divider>
                <Card size="small">
                  <Row gutter={16}>
                    <Col span={4}><Statistic title="v1.0" value="5-8%" valueStyle={{ fontSize: 14 }} /></Col>
                    <Col span={1}><Text style={{ lineHeight: '40px' }}>→</Text></Col>
                    <Col span={4}><Statistic title="v2.2" value="9.7%" valueStyle={{ fontSize: 14, color: '#1677ff' }} /></Col>
                    <Col span={1}><Text style={{ lineHeight: '40px' }}>→</Text></Col>
                    <Col span={4}><Statistic title="v3.0" value="12.8%" valueStyle={{ fontSize: 14, color: '#52c41a' }} /></Col>
                    <Col span={1}><Text style={{ lineHeight: '40px' }}>→</Text></Col>
                    <Col span={4}><Statistic title="乐观" value="21.2%" valueStyle={{ fontSize: 14, color: '#722ed1' }} /></Col>
                    <Col span={1}><Text style={{ lineHeight: '40px' }}>→</Text></Col>
                    <Col span={4}><Statistic title="探索上限" value="24%" valueStyle={{ fontSize: 14, color: '#ff4d4f' }} /></Col>
                  </Row>
                </Card>
              </>
            ),
          },
          {
            key: 'backtest',
            label: <span><ExperimentOutlined /> 回测</span>,
            children: (
              <>
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Row gutter={24}>
                    <Col span={6}>
                      <Text>开始日期</Text>
                      <InputNumber style={{ width: '100%' }} value={btStartDate} onChange={v => setBtStartDate(v || '2024-01-01')} />
                    </Col>
                    <Col span={6}>
                      <Text>结束日期</Text>
                      <InputNumber style={{ width: '100%' }} value={btEndDate} onChange={v => setBtEndDate(v || '2025-12-31')} />
                    </Col>
                    <Col span={6}>
                      <Text>持有数量</Text>
                      <InputNumber min={5} max={50} value={holdCount} onChange={v => setHoldCount(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={6}>
                      <Text>调仓间隔</Text>
                      <InputNumber min={5} max={60} value={rebalanceDays} onChange={v => setRebalanceDays(v || 20)} style={{ width: '100%' }} />
                    </Col>
                  </Row>
                  <div style={{ marginTop: 16, textAlign: 'center' }}>
                    <Button type="primary" icon={<ExperimentOutlined />} onClick={handleRunBacktest} loading={backtestLoading} size="large">
                      运行璇玑十二因子回测
                    </Button>
                  </div>
                </Card>

                {backtestResult && backtestMetrics && (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={4}>
                        <Statistic title="总收益" value={backtestMetrics.total_return_pct?.toFixed(2)} suffix="%"
                          valueStyle={{ color: (backtestMetrics.total_return_pct || 0) > 0 ? '#52c41a' : '#ff4d4f' }} />
                      </Col>
                      <Col span={4}>
                        <Statistic title="年化收益" value={backtestMetrics.annual_return_pct?.toFixed(2)} suffix="%"
                          valueStyle={{ color: (backtestMetrics.annual_return_pct || 0) > 0 ? '#52c41a' : '#ff4d4f' }} />
                      </Col>
                      <Col span={4}>
                        <Statistic title="最大回撤" value={backtestMetrics.max_drawdown_pct?.toFixed(2)} suffix="%"
                          valueStyle={{ color: '#ff4d4f' }} />
                      </Col>
                      <Col span={3}>
                        <Statistic title="夏普比率" value={backtestMetrics.sharpe_ratio?.toFixed(2)}
                          valueStyle={{ color: (backtestMetrics.sharpe_ratio || 0) > 1 ? '#52c41a' : '#faad14' }} />
                      </Col>
                      <Col span={3}>
                        <Statistic title="胜率" value={backtestMetrics.win_rate?.toFixed(1)} suffix="%"
                          valueStyle={{ color: (backtestMetrics.win_rate || 0) > 50 ? '#52c41a' : '#ff4d4f' }} />
                      </Col>
                      <Col span={3}>
                        <Statistic title="盈亏比" value={backtestMetrics.profit_loss_ratio?.toFixed(2)} />
                      </Col>
                      <Col span={3}>
                        <Statistic title="交易次数" value={backtestMetrics.total_trades} />
                      </Col>
                    </Row>

                    {backtestResult.equity_curve && backtestResult.equity_curve.length > 0 && (
                      <Card size="small" title="净值曲线">
                        <div style={{ height: 300 }}>
                          <Text type="secondary">净值曲线数据点: {backtestResult.equity_curve.length}个 (图表渲染需ECharts)</Text>
                        </div>
                      </Card>
                    )}

                    {backtestResult.trades && backtestResult.trades.length > 0 && (
                      <Card size="small" title={`交易记录 (${backtestResult.trades.length}笔)`} style={{ marginTop: 16 }}>
                        <Table dataSource={backtestResult.trades.slice(0, 50)} rowKey={(r: any) => `${r.code}-${r.buy_date}`}
                          size="small" pagination={{ pageSize: 10 }} scroll={{ x: 800 }}
                          columns={[
                            { title: '代码', dataIndex: 'code', width: 90 },
                            { title: '名称', dataIndex: 'name', width: 80 },
                            { title: '买入日', dataIndex: 'buy_date', width: 100 },
                            { title: '卖出日', dataIndex: 'sell_date', width: 100 },
                            { title: '买价', dataIndex: 'buy_price', width: 80, render: (v: number) => v?.toFixed(2) },
                            { title: '卖价', dataIndex: 'sell_price', width: 80, render: (v: number) => v?.toFixed(2) },
                            { title: '收益%', dataIndex: 'profit_pct', width: 80, render: (v: number) => <Text style={{ color: (v || 0) > 0 ? '#52c41a' : '#ff4d4f' }}>{v?.toFixed(2)}%</Text> },
                            { title: '持有天数', dataIndex: 'hold_days', width: 80 },
                            { title: '原因', dataIndex: 'reason', width: 150 },
                          ]}
                        />
                      </Card>
                    )}
                  </>
                )}

                {!backtestResult && !backtestLoading && (
                  <Empty description="点击上方按钮运行璇玑十二因子策略回测" />
                )}
              </>
            ),
          },
          {
            key: 'delta',
            label: <span><SafetyOutlined /> Delta对冲</span>,
            children: (
              <>
                <Alert
                  message="Delta对冲套利 (Alpha A9)"
                  description="当IV > HV时, 市场高估转债波动率, 买入转债+做空正股捕获波动率溢价。23只候选(IV>HV+溢价率20-80%)"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />
                <Table
                  dataSource={[
                    { key: '1', code: '111015', name: '绿茵转债', iv_hv: 19.3, premium: 53.6, alpha: '+2%/年' },
                    { key: '2', code: '113653', name: '伟22转债', iv_hv: 14.2, premium: 55.6, alpha: '+2%/年' },
                    { key: '3', code: '110086', name: '精工转债', iv_hv: 11.8, premium: 40.3, alpha: '+2%/年' },
                    { key: '4', code: '123017', name: '锡振转债', iv_hv: 11.5, premium: 51.6, alpha: '+2%/年' },
                    { key: '5', code: '113549', name: '莱克转债', iv_hv: 8.5, premium: 51.9, alpha: '+2%/年' },
                  ]}
                  size="small" pagination={false}
                  columns={[
                    { title: '代码', dataIndex: 'code', width: 90 },
                    { title: '名称', dataIndex: 'name', width: 100 },
                    { title: 'IV-HV差', dataIndex: 'iv_hv', width: 100, render: (v: number) => <Text style={{ color: '#52c41a' }}>+{v}%</Text> },
                    { title: '溢价率', dataIndex: 'premium', width: 100, render: (v: number) => `${v}%` },
                    { title: '对冲α', dataIndex: 'alpha', width: 100, render: (v: string) => <Text style={{ color: '#52c41a' }}>{v}</Text> },
                  ]}
                />
                <Divider>Greeks分解 (168只)</Divider>
                <Row gutter={16}>
                  <Col span={6}>
                    <Card size="small"><Statistic title="Delta δ" value="0.745" suffix="均值" valueStyle={{ color: '#1677ff' }} /></Card>
                  </Col>
                  <Col span={6}>
                    <Card size="small"><Statistic title="Gamma γ" value="0.014" suffix="均值" valueStyle={{ color: '#722ed1' }} /></Card>
                  </Col>
                  <Col span={6}>
                    <Card size="small"><Statistic title="Vega ν" value="0.75" suffix="均值" valueStyle={{ color: '#faad14' }} /></Card>
                  </Col>
                  <Col span={6}>
                    <Card size="small"><Statistic title="Theta θ" value="0.008/日" valueStyle={{ color: '#52c41a' }} /></Card>
                  </Col>
                </Row>
                <Alert style={{ marginTop: 16 }} message="109只高Delta(>0.7)、0只低Delta(<0.3)，当前选池整体偏股型" type="warning" showIcon />
              </>
            ),
          },
        ]} />
      </Card>
    </div>
  )
}
