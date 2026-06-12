/**
 * 璇玑十二因子指增策略页面
 *
 * 璇玑: 古代天文仪器，象征多维度精密分析
 * 12因子: 双低/HV/动量/YTM/期限/质量ROE/质量GPM/质量CAGR/估值PE/估值PB/事件/Delta
 * 5态市场: 极端牛/温和牛/震荡/温和熊/极端熊
 * Alpha源: A1-A12共12个alpha源
 * 目标: 中性年化12.8% / 乐观21.2% / 探索上限24%
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Slider, Select, Space, Button, Progress, Modal, Descriptions,
  Alert, Divider, Tabs, InputNumber, Tooltip, Badge, Input, Switch
} from 'antd'
import {
  TrophyOutlined, ReloadOutlined, StarOutlined,
  ExperimentOutlined, ThunderboltOutlined, SafetyOutlined,
  InfoCircleOutlined, RiseOutlined, FallOutlined,
  LineChartOutlined, DashboardOutlined, FundOutlined,
  DownloadOutlined, BulbOutlined, RocketOutlined, EyeOutlined
} from '@ant-design/icons'
import * as echarts from 'echarts'
import {
  fetchStrategies, runBacktest, runOptimization,
  fetchXuanjiRanking, fetchXuanjiSingle, fetchXuanjiDeltaCandidates,
  fetchXuanjiGreeks, fetchXuanjiMarketWeights, fetchXuanjiAlphaSources,
  fetchXuanjiStressTest, fetchXuanjiFactorContribution, fetchXuanjiFactorCorrelation,
  fetchXuanjiComparison,
  type StrategyInfo, type BacktestResult, type XuanjiItem,
  type XuanjiSingleResponse, type XuanjiDeltaCandidate,
  type XuanjiGreeksSummary, type XuanjiMarketWeightsResponse,
  type XuanjiAlphaResponse, type OptimizationResult,
  type XuanjiStressResponse, type XuanjiFactorContributionResponse,
  type XuanjiFactorCorrelationResponse, type XuanjiComparisonResponse
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

const WEIGHT_LABELS: Record<string, string> = {
  dual_low: '双低', momentum: '动量', hv: 'HV', quality: '质量',
  valuation: '估值', ytm: 'YTM', event: '事件', delta: 'Delta'
}

const INDUSTRY_COLORS: Record<string, string> = {
  '银行': '#1890ff', '非银金融': '#52c41a', '医药生物': '#fa541c',
  '电子': '#722ed1', '计算机': '#13c2c2', '化工': '#eb2f96',
  '机械设备': '#fa8c16', '汽车': '#fadb14', '房地产': '#a0d911',
  '传媒': '#2f54eb', '公用事业': '#52c41a',
}

function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return {
    topN: 50, marketState: 'mild_bull', holdCount: 20, rebalanceDays: 20,
    maxPremium: 50, minPrice: 90, maxPrice: 150, volAdjust: 0.85,
    autoDetect: true,
  }
}

function saveConfig(config: any) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(config)) } catch { /* ignore */ }
}

function exportToCSV(data: any[], filename: string) {
  if (!data || data.length === 0) return
  const headers = Object.keys(data[0])
  const csv = [
    headers.join(','),
    ...data.map(row => headers.map(h => {
      const v = row[h]
      if (v == null) return ''
      const s = String(v).replace(/"/g, '""')
      return /[,"\n]/.test(s) ? `"${s}"` : s
    }).join(','))
  ].join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export default function XuanjiIndex() {
  const savedConfig = useMemo(() => loadConfig(), [])

  const [rankingLoading, setRankingLoading] = useState(false)
  const [rankingData, setRankingData] = useState<XuanjiItem[]>([])
  const [rankingInfo, setRankingInfo] = useState<any>(null)
  const [topN, setTopN] = useState(savedConfig.topN)
  const [marketState, setMarketState] = useState(savedConfig.marketState)
  const [holdCount, setHoldCount] = useState(savedConfig.holdCount)
  const [rebalanceDays, setRebalanceDays] = useState(savedConfig.rebalanceDays)
  const [maxPremium, setMaxPremium] = useState(savedConfig.maxPremium)
  const [minPrice, setMinPrice] = useState(savedConfig.minPrice)
  const [maxPrice, setMaxPrice] = useState(savedConfig.maxPrice)
  const [volAdjust, setVolAdjust] = useState(savedConfig.volAdjust)
  const [autoDetect, setAutoDetect] = useState(savedConfig.autoDetect)

  // Backtest states
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [optimizationLoading, setOptimizationLoading] = useState(false)
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null)
  const [optimizationResult, setOptimizationResult] = useState<OptimizationResult | null>(null)
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [btStartDate, setBtStartDate] = useState('2024-01-01')
  const [btEndDate, setBtEndDate] = useState('2025-12-31')

  // Single bond detail
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedCode, setSelectedCode] = useState('')
  const [selectedDetail, setSelectedDetail] = useState<XuanjiSingleResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Greeks and delta
  const [greeksData, setGreeksData] = useState<XuanjiGreeksSummary | null>(null)
  const [deltaCandidates, setDeltaCandidates] = useState<XuanjiDeltaCandidate[]>([])
  const [alphaSources, setAlphaSources] = useState<XuanjiAlphaResponse | null>(null)
  const [marketWeights, setMarketWeights] = useState<XuanjiMarketWeightsResponse | null>(null)

  // Stress test, factor contribution, comparison
  const [stressData, setStressData] = useState<XuanjiStressResponse | null>(null)
  const [factorContrib, setFactorContrib] = useState<XuanjiFactorContributionResponse | null>(null)
  const [factorCorr, setFactorCorr] = useState<XuanjiFactorCorrelationResponse | null>(null)
  const [strategyCompare, setStrategyCompare] = useState<XuanjiComparisonResponse | null>(null)

  const [activeTab, setActiveTab] = useState('ranking')

  // Charts
  const equityChartRef = useRef<HTMLDivElement>(null)
  const equityChart = useRef<echarts.ECharts | null>(null)
  const weightChartRef = useRef<HTMLDivElement>(null)
  const weightChart = useRef<echarts.ECharts | null>(null)
  const radarChartRef = useRef<HTMLDivElement>(null)
  const radarChart = useRef<echarts.ECharts | null>(null)
  const industryChartRef = useRef<HTMLDivElement>(null)
  const industryChart = useRef<echarts.ECharts | null>(null)

  // Load initial data
  useEffect(() => {
    fetchStrategies().then(setStrategies).catch(() => {})
    fetchXuanjiAlphaSources().then(setAlphaSources).catch(() => {})
    fetchXuanjiMarketWeights().then(setMarketWeights).catch(() => {})
    fetchXuanjiGreeks().then(setGreeksData).catch(() => {})
    fetchXuanjiStressTest(50, marketState).then(setStressData).catch(() => {})
    fetchXuanjiFactorContribution(20, marketState).then(setFactorContrib).catch(() => {})
    fetchXuanjiFactorCorrelation(50, marketState).then(setFactorCorr).catch(() => {})
    fetchXuanjiComparison(50).then(setStrategyCompare).catch(() => {})
  }, [marketState])

  // Load ranking data
  const loadRanking = useCallback(async () => {
    setRankingLoading(true)
    try {
      const result = await fetchXuanjiRanking(
        topN, autoDetect ? 'auto' : marketState,
        maxPremium, minPrice, maxPrice, volAdjust
      )
      setRankingData(result.items || [])
      setRankingInfo({
        total: result.total,
        returned: result.returned,
        detected: result.market_state_detected,
        actual: result.market_state_actual,
        weights: result.market_weights,
        factorNames: result.factor_names,
      })
    } catch (e: any) {
      message.error(`加载排名失败: ${e.message}`)
      setRankingData([])
    } finally {
      setRankingLoading(false)
    }
  }, [topN, marketState, maxPremium, minPrice, maxPrice, volAdjust, autoDetect])

  const loadDeltaCandidates = useCallback(async () => {
    try {
      const result = await fetchXuanjiDeltaCandidates(5.0, 20, 80, 30)
      setDeltaCandidates(result.items || [])
    } catch (e: any) {
      // silent fail
    }
  }, [])

  useEffect(() => {
    loadRanking()
    loadDeltaCandidates()
  }, [loadRanking, loadDeltaCandidates])

  useEffect(() => {
    saveConfig({ topN, marketState, holdCount, rebalanceDays, maxPremium, minPrice, maxPrice, volAdjust, autoDetect })
  }, [topN, marketState, holdCount, rebalanceDays, maxPremium, minPrice, maxPrice, volAdjust, autoDetect])

  // Backtest
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
        setOptimizationResult(null)
        message.success('回测完成')
      }
    } catch (e: any) {
      message.error(`回测失败: ${e.message}`)
    } finally {
      setBacktestLoading(false)
    }
  }, [holdCount, rebalanceDays, marketState, btStartDate, btEndDate])

  // Optimization
  const handleRunOptimization = useCallback(async () => {
    setOptimizationLoading(true)
    try {
      const result = await runOptimization({
        strategy: 'xuanji_twelve',
        params: { hold_count: holdCount, market_state: marketState },
        start_date: btStartDate,
        end_date: btEndDate,
        config: { commission_pct: 0.001, slippage_pct: 0.001, min_commission: 5, risk_free_rate: 0.02 },
        optimization: {
          enabled: true,
          param_ranges: [
            { name: 'hold_count', min_val: 10, max_val: 30, step: 5 },
            { name: 'rebalance_days', min_val: 10, max_val: 30, step: 5 },
          ],
          optimize_metric: 'sharpe_ratio',
          max_iterations: 50,
          top_n: 10,
          parallel_workers: 4,
        },
      })
      if (result.success) {
        setOptimizationResult(result.result)
        setBacktestResult(null)
        message.success('参数优化完成')
      }
    } catch (e: any) {
      message.error(`优化失败: ${e.message}`)
    } finally {
      setOptimizationLoading(false)
    }
  }, [holdCount, rebalanceDays, marketState, btStartDate, btEndDate])

  // Single bond detail
  const handleViewDetail = useCallback(async (code: string) => {
    setSelectedCode(code)
    setDetailVisible(true)
    setDetailLoading(true)
    try {
      const detail = await fetchXuanjiSingle(code, marketState === 'auto' ? 'mild_bull' : marketState)
      setSelectedDetail(detail)
    } catch (e: any) {
      message.error(`加载详情失败: ${e.message}`)
    } finally {
      setDetailLoading(false)
    }
  }, [marketState])

  // Equity curve chart
  useEffect(() => {
    if (activeTab === 'backtest' && backtestResult && equityChartRef.current) {
      if (!equityChart.current) {
        equityChart.current = echarts.init(equityChartRef.current)
      }
      const data = backtestResult.equity_curve || []
      const dates = data.map((d: any) => d.date)
      const values = data.map((d: any) => d.value)
      const benchmark = backtestResult.benchmark_curve?.map((d: any) => d.value) || []

      equityChart.current.setOption({
        title: { text: '净值曲线', left: 'center' },
        tooltip: { trigger: 'axis' },
        legend: { data: ['璇玑十二因子', '中证转债基准'], top: 30 },
        grid: { top: 70, left: 50, right: 30, bottom: 50 },
        xAxis: { type: 'category', data: dates, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', name: '净值' },
        series: [
          { name: '璇玑十二因子', type: 'line', data: values, smooth: true, lineStyle: { color: '#722ed1', width: 2 }, areaStyle: { color: 'rgba(114, 46, 209, 0.1)' } },
          ...(benchmark.length ? [{ name: '中证转债基准', type: 'line', data: benchmark, smooth: true, lineStyle: { color: '#52c41a', width: 1, type: 'dashed' as const } }] : []),
        ],
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20 }],
      })
    }
    return () => {
      if (equityChart.current) {
        equityChart.current.dispose()
        equityChart.current = null
      }
    }
  }, [backtestResult, activeTab])

  // Weight radar chart
  useEffect(() => {
    if (activeTab === 'weights' && weightChartRef.current) {
      if (!weightChart.current) {
        weightChart.current = echarts.init(weightChartRef.current)
      }
      const states = rankingInfo?.weights ? [marketState] : ['mild_bull', 'neutral', 'mild_bear']
      const seriesData = states.map(s => {
        const w = rankingInfo?.weights || {
          dual_low: 0.30, momentum: 0.10, hv: 0.20, quality: 0.20,
          valuation: 0.10, ytm: 0.05, event: 0.03, delta: 0.02
        }
        return { name: s, value: Object.values(w).map((v: any) => +(v * 100).toFixed(1)) }
      })

      weightChart.current.setOption({
        title: { text: '权重雷达图', left: 'center' },
        tooltip: {},
        legend: { data: states, top: 30 },
        radar: {
          indicator: Object.keys(WEIGHT_LABELS).map(k => ({ name: WEIGHT_LABELS[k], max: 50 })),
        },
        series: [{
          type: 'radar',
          data: seriesData,
        }],
      })
    }
    return () => {
      if (weightChart.current) {
        weightChart.current.dispose()
        weightChart.current = null
      }
    }
  }, [activeTab, rankingInfo, marketState])

  // Industry distribution chart
  useEffect(() => {
    if (activeTab === 'ranking' && industryChartRef.current && rankingData.length > 0) {
      if (!industryChart.current) {
        industryChart.current = echarts.init(industryChartRef.current)
      }
      const industryCount: Record<string, number> = {}
      rankingData.forEach(item => {
        const ind = item.industry || '其他'
        industryCount[ind] = (industryCount[ind] || 0) + 1
      })
      const pieData = Object.entries(industryCount).map(([k, v]) => ({ name: k, value: v }))

      industryChart.current.setOption({
        title: { text: '行业分布', left: 'center' },
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        series: [{
          type: 'pie',
          radius: ['40%', '70%'],
          data: pieData,
          label: { formatter: '{b}\n{d}%' },
        }],
      })
    }
    return () => {
      if (industryChart.current) {
        industryChart.current.dispose()
        industryChart.current = null
      }
    }
  }, [activeTab, rankingData])

  // Single bond radar
  useEffect(() => {
    if (detailVisible && selectedDetail && radarChartRef.current) {
      if (!radarChart.current) {
        radarChart.current = echarts.init(radarChartRef.current)
      }
      const factorScores = selectedDetail.factor_scores
      const indicators = Object.keys(factorScores).map(k => ({
        name: WEIGHT_LABELS[k] || k,
        max: 1,
      }))
      const values = Object.values(factorScores).map(s => s.value)
      const weights = Object.values(factorScores).map(s => s.weight)

      radarChart.current.setOption({
        title: { text: '因子评分雷达', left: 'center' },
        tooltip: {},
        radar: { indicator: indicators },
        series: [{
          type: 'radar',
          data: [
            { name: '评分', value: values, areaStyle: { color: 'rgba(114, 46, 209, 0.3)' }, lineStyle: { color: '#722ed1' } },
            { name: '权重(%)', value: weights, areaStyle: { color: 'rgba(82, 196, 26, 0.2)' }, lineStyle: { color: '#52c41a' } },
          ],
        }],
      })
    }
    return () => {
      if (radarChart.current) {
        radarChart.current.dispose()
        radarChart.current = null
      }
    }
  }, [detailVisible, selectedDetail])

  const scoreColor = (v: number, max: number = 1) => {
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
    { title: '代码', dataIndex: 'code', key: 'code', width: 90, render: (c: string) => <a onClick={() => handleViewDetail(c)} style={{ color: '#1677ff' }}>{c}</a> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    {
      title: '价格', dataIndex: 'price', key: 'price', width: 70,
      render: (v: number) => <Text style={{ color: v < 100 ? '#52c41a' : v > 130 ? '#ff4d4f' : undefined }}>{v?.toFixed(2)}</Text>,
    },
    {
      title: '溢价率', dataIndex: 'premium_ratio', key: 'premium_ratio', width: 70,
      render: (v: number) => <Text style={{ color: v < 20 ? '#52c41a' : v > 50 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text>,
    },
    {
      title: '双低', dataIndex: 'dual_low', key: 'dual_low', width: 65,
      render: (v: number) => <Text style={{ color: v < 130 ? '#52c41a' : v > 160 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}</Text>,
    },
    {
      title: 'HV', dataIndex: 'hv', key: 'hv', width: 60,
      render: (v: number) => <Text style={{ color: v < 20 ? '#52c41a' : v > 40 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text>,
    },
    {
      title: '行业', dataIndex: 'industry', key: 'industry', width: 80,
      render: (v: string) => <Tag color={INDUSTRY_COLORS[v] || 'default'}>{v || '其他'}</Tag>,
    },
    {
      title: '评级', dataIndex: 'rating', key: 'rating', width: 60,
      render: (v: string) => <Tag color={v === 'AAA' ? 'gold' : v === 'AA+' ? 'orange' : 'blue'}>{v}</Tag>,
    },
    {
      title: '综合评分', dataIndex: 'score', key: 'score', width: 130,
      sorter: (a: XuanjiItem, b: XuanjiItem) => a.score - b.score,
      defaultSortOrder: 'descend' as const,
      render: (v: number) => <Progress percent={Math.min(v * 100, 100)} size="small" strokeColor={scoreColor(v)} format={(p) => p?.toFixed(1)} />,
    },
  ]

  const backtestMetrics = backtestResult?.metrics

  const marketStateConfig = MARKET_STATES.find(s => s.value === marketState) || MARKET_STATES[1]

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
              {rankingInfo?.actual && (
                <Tag icon={MARKET_STATES.find(s => s.value === rankingInfo.actual)?.icon}
                  color={MARKET_STATES.find(s => s.value === rankingInfo.actual)?.color}>
                  检测:{MARKET_STATES.find(s => s.value === rankingInfo.actual)?.label}
                </Tag>
              )}
              <Button icon={<ReloadOutlined />} onClick={loadRanking} loading={rankingLoading}>
                刷新
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => exportToCSV(rankingData, '璇玑排名.csv')}>
                导出CSV
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
                <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
                  <Row gutter={16}>
                    <Col span={4}>
                      <Text>Top N</Text>
                      <Slider min={10} max={100} value={topN} onChange={setTopN} marks={{ 10: '10', 50: '50', 100: '100' }} />
                    </Col>
                    <Col span={4}>
                      <Text>市场状态</Text>
                      <Select style={{ width: '100%' }} value={marketState} onChange={setMarketState}
                        options={[{ value: 'auto', label: '自动检测' }, ...MARKET_STATES.map(s => ({ value: s.value, label: <span>{s.icon} {s.label}</span> }))]} />
                      <Switch checked={autoDetect} onChange={setAutoDetect} checkedChildren="自动" unCheckedChildren="手动" style={{ marginTop: 4 }} />
                    </Col>
                    <Col span={3}>
                      <Text>持有数</Text>
                      <InputNumber min={5} max={50} value={holdCount} onChange={v => setHoldCount(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={3}>
                      <Text>调仓天</Text>
                      <InputNumber min={5} max={60} value={rebalanceDays} onChange={v => setRebalanceDays(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={3}>
                      <Text>溢价上限</Text>
                      <InputNumber min={10} max={100} value={maxPremium} onChange={v => setMaxPremium(v || 50)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={3}>
                      <Text>HV调权</Text>
                      <InputNumber min={0.5} max={1.0} step={0.05} value={volAdjust} onChange={v => setVolAdjust(v || 0.85)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={4}>
                      <Button type="primary" icon={<BulbOutlined />} onClick={loadRanking} loading={rankingLoading} block style={{ marginTop: 18 }}>
                        计算评分
                      </Button>
                    </Col>
                  </Row>
                </Card>

                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={3}><Statistic title="筛选池" value={rankingInfo?.total || 0} suffix="只" /></Col>
                  <Col span={3}><Statistic title="返回" value={rankingInfo?.returned || 0} suffix="只" /></Col>
                  <Col span={3}><Statistic title="三层漏斗" value="168→125→74→50" valueStyle={{ fontSize: 14 }} /></Col>
                  <Col span={3}><Statistic title="中性年化" value="12.8%" valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={3}><Statistic title="乐观年化" value="21.2%" valueStyle={{ color: '#1677ff' }} /></Col>
                  <Col span={3}><Statistic title="IC衰减" value="×0.85" /></Col>
                  <Col span={3}><Statistic title="回撤控制" value="<8%" valueStyle={{ color: '#fa8c16' }} /></Col>
                  <Col span={3}><Statistic title="胜率目标" value=">55%" valueStyle={{ color: '#722ed1' }} /></Col>
                </Row>

                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={16}>
                    <Alert
                      message="璇玑十二因子评分体系"
                      description="防守(双低+HV+YTM+期限) + 进攻(动量+Delta) + 质量(ROE+GPM+CAGR+负债率+流动比) + 估值(PE+PB+IV-HV) + 事件(回购+增持+下修+强赎)，5态市场自适应权重"
                      type="info" showIcon
                    />
                  </Col>
                  <Col span={8}>
                    <div ref={industryChartRef} style={{ height: 80 }} />
                  </Col>
                </Row>

                <Spin spinning={rankingLoading}>
                  {rankingData.length > 0 ? (
                    <Table dataSource={rankingData} columns={rankingColumns} rowKey="code" size="small"
                      pagination={{ pageSize: 20, showSizeChanger: true, showQuickJumper: true }} scroll={{ x: 1100 }} />
                  ) : (
                    <Empty description="暂无数据" />
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
                  <Row gutter={16} align="middle">
                    <Col span={6}>
                      <Text>市场状态选择: </Text>
                      <Select value={marketState} onChange={setMarketState} style={{ width: 160 }}
                        options={MARKET_STATES.map(s => ({ value: s.value, label: `${s.label}` }))} />
                    </Col>
                    <Col span={18}>
                      <Text type="secondary">
                        5态市场: 极端牛(动量30%) / 温和牛(动量25%) / 震荡(均衡) / 温和熊(防御) / 极端熊(双低50%)
                      </Text>
                    </Col>
                  </Row>
                </Card>
                <Row gutter={[16, 16]}>
                  <Col span={14}>
                    <div ref={weightChartRef} style={{ height: 400 }} />
                  </Col>
                  <Col span={10}>
                    {MARKET_STATES.map(state => {
                      const w = (rankingInfo?.actual === state.value && rankingInfo?.weights) ?
                        rankingInfo.weights : null
                      return (
                        <Card size="small" key={state.value}
                          style={{ marginBottom: 8, border: marketState === state.value ? `2px solid ${state.color}` : undefined }}>
                          <Title level={5} style={{ color: state.color, margin: 0 }}>
                            {state.icon} {state.label}
                            {marketState === state.value && <Tag color="blue" style={{ marginLeft: 8 }}>当前</Tag>}
                          </Title>
                          {w ? (
                            <Row gutter={[4, 4]} style={{ marginTop: 8 }}>
                              {Object.entries(w).map(([key, val]) => (
                                <Col span={6} key={key}>
                                  <Statistic title={WEIGHT_LABELS[key] || key} value={Math.round((val as number) * 100)} suffix="%"
                                    valueStyle={{ fontSize: 12, color: (val as number) > 0.2 ? state.color : undefined }} />
                                </Col>
                              ))}
                            </Row>
                          ) : (
                            <Text type="secondary" style={{ fontSize: 12 }}>该状态下权重配置</Text>
                          )}
                        </Card>
                      )
                    })}
                  </Col>
                </Row>
                <Divider>因子分组</Divider>
                <Row gutter={[16, 16]}>
                  {[
                    { group: '防守', factors: ['双低值', '历史波动率', '到期收益率', '剩余期限'], color: '#52c41a' },
                    { group: '进攻', factors: ['多时帧动量', 'Delta对冲'], color: '#ff4d4f' },
                    { group: '质量', factors: ['ROE', '毛利率', '复合增长率', '负债率', '流动比率'], color: '#1677ff' },
                    { group: '估值', factors: ['市盈率', '市净率', 'IV-HV差'], color: '#faad14' },
                    { group: '事件', factors: ['回购金额', '管理层增持', '下修概率', '强赎预警'], color: '#722ed1' },
                  ].map(g => (
                    <Col span={4} key={g.group}>
                      <Card size="small">
                        <Title level={5} style={{ color: g.color, margin: 0 }}>{g.group}</Title>
                        <div style={{ marginTop: 8 }}>
                          {g.factors.map(f => <Tag key={f} color={g.color} style={{ marginBottom: 4 }}>{f}</Tag>)}
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
                  message="12个Alpha源叠加 (A1-A12)"
                  description={alphaSources?.total_alpha_potential || '+6.1~12.8%/年'}
                  type="success" showIcon style={{ marginBottom: 16 }}
                />
                <Row gutter={[16, 16]}>
                  {alphaSources?.sources?.map(a => (
                    <Col span={4} key={a.id}>
                      <Card size="small" hoverable>
                        <Statistic title={a.id} value={a.name}
                          valueStyle={{ fontSize: 14, color: a.status === 'active' ? '#52c41a' : '#999' }} />
                        <Tag color="purple" style={{ marginTop: 4 }}>{a.category}</Tag>
                        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
                          {a.implementation}
                        </Text>
                        <div style={{ marginTop: 4 }}>
                          <Text style={{ color: '#52c41a', fontSize: 12 }}>{a.range}</Text>
                        </div>
                        <Badge status={a.status === 'active' ? 'success' : 'default'} text={a.status === 'active' ? '已启用' : '未启用'} />
                      </Card>
                    </Col>
                  )) || <Spin />}
                </Row>
                <Divider>收益增厚路径</Divider>
                <Card size="small">
                  <Row gutter={16}>
                    {alphaSources?.return_path?.map((r, i) => (
                      <Col span={5} key={r.version}>
                        <Statistic title={r.version} value={r.neutral}
                          valueStyle={{ fontSize: 14, color: i === alphaSources.return_path.length - 1 ? '#722ed1' : '#1677ff' }} />
                        <Text type="secondary" style={{ fontSize: 12 }}>乐观 {r.optimistic}</Text>
                      </Col>
                    ))}
                    {alphaSources?.return_path && alphaSources.return_path.length > 0 && (
                      <Col span={1} style={{ display: 'flex', alignItems: 'center' }}>
                        <RocketOutlined style={{ fontSize: 24, color: '#722ed1' }} />
                      </Col>
                    )}
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
                  <Row gutter={16}>
                    <Col span={4}>
                      <Text>开始</Text>
                      <Input style={{ width: '100%' }} value={btStartDate} onChange={e => setBtStartDate(e.target.value)} />
                    </Col>
                    <Col span={4}>
                      <Text>结束</Text>
                      <Input style={{ width: '100%' }} value={btEndDate} onChange={e => setBtEndDate(e.target.value)} />
                    </Col>
                    <Col span={3}>
                      <Text>持有数</Text>
                      <InputNumber min={5} max={50} value={holdCount} onChange={v => setHoldCount(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={3}>
                      <Text>调仓天</Text>
                      <InputNumber min={5} max={60} value={rebalanceDays} onChange={v => setRebalanceDays(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={4}>
                      <Text>市场状态</Text>
                      <Select style={{ width: '100%' }} value={marketState} onChange={setMarketState}
                        options={MARKET_STATES.map(s => ({ value: s.value, label: s.label }))} />
                    </Col>
                    <Col span={6}>
                      <Space style={{ marginTop: 18 }}>
                        <Button type="primary" icon={<ExperimentOutlined />} onClick={handleRunBacktest} loading={backtestLoading}>
                          策略回测
                        </Button>
                        <Button icon={<RocketOutlined />} onClick={handleRunOptimization} loading={optimizationLoading}>
                          参数优化
                        </Button>
                      </Space>
                    </Col>
                  </Row>
                </Card>

                {backtestResult && backtestMetrics && (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={3}><Statistic title="总收益" value={backtestMetrics.total_return_pct?.toFixed(2)} suffix="%"
                        valueStyle={{ color: (backtestMetrics.total_return_pct || 0) > 0 ? '#52c41a' : '#ff4d4f' }} /></Col>
                      <Col span={3}><Statistic title="年化收益" value={backtestMetrics.annual_return_pct?.toFixed(2)} suffix="%"
                        valueStyle={{ color: (backtestMetrics.annual_return_pct || 0) > 0 ? '#52c41a' : '#ff4d4f' }} /></Col>
                      <Col span={3}><Statistic title="最大回撤" value={backtestMetrics.max_drawdown_pct?.toFixed(2)} suffix="%"
                        valueStyle={{ color: '#ff4d4f' }} /></Col>
                      <Col span={2}><Statistic title="夏普" value={backtestMetrics.sharpe_ratio?.toFixed(2)}
                        valueStyle={{ color: (backtestMetrics.sharpe_ratio || 0) > 1 ? '#52c41a' : '#faad14' }} /></Col>
                      <Col span={2}><Statistic title="Sortino" value={backtestMetrics.sortino_ratio?.toFixed(2)} /></Col>
                      <Col span={2}><Statistic title="Calmar" value={backtestMetrics.calmar_ratio?.toFixed(2)} /></Col>
                      <Col span={2}><Statistic title="胜率" value={backtestMetrics.win_rate?.toFixed(1)} suffix="%" /></Col>
                      <Col span={2}><Statistic title="盈亏比" value={backtestMetrics.profit_loss_ratio?.toFixed(2)} /></Col>
                      <Col span={2}><Statistic title="交易" value={backtestMetrics.total_trades} /></Col>
                      <Col span={3}><Statistic title="平均持仓" value={backtestMetrics.avg_hold_days?.toFixed(1)} suffix="天" /></Col>
                    </Row>

                    <Card size="small" title="净值曲线" style={{ marginBottom: 16 }}>
                      <div ref={equityChartRef} style={{ height: 400 }} />
                    </Card>

                    {backtestResult.trades && backtestResult.trades.length > 0 && (
                      <Card size="small" title={`交易记录 (${backtestResult.trades.length}笔)`}>
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
                            { title: '持有天', dataIndex: 'hold_days', width: 70 },
                            { title: '原因', dataIndex: 'reason', width: 150 },
                          ]}
                        />
                      </Card>
                    )}
                  </>
                )}

                {optimizationResult && (
                  <Card size="small" title={`参数优化 Top${optimizationResult.top_results.length}`}>
                    <Alert message={`优化目标: ${optimizationResult.optimize_metric} | 总组合: ${optimizationResult.total_combinations} | 耗时: ${optimizationResult.execution_time_ms}ms`}
                      type="info" style={{ marginBottom: 16 }} />
                    <div style={{ marginBottom: 16 }}>
                      <Title level={5}>最优参数</Title>
                      <Space>
                        {Object.entries(optimizationResult.best_params).map(([k, v]) => (
                          <Tag color="purple" key={k}>{k} = {v}</Tag>
                        ))}
                      </Space>
                    </div>
                    <Table dataSource={optimizationResult.top_results} rowKey={(r: any) => JSON.stringify(r.params)}
                      size="small" pagination={{ pageSize: 10 }}
                      columns={[
                        { title: '参数', dataIndex: 'params', render: (p: any) => Object.entries(p).map(([k, v]) => `${k}=${v}`).join(', ') },
                        { title: '年化%', dataIndex: 'annual_return_pct', render: (v: number) => v?.toFixed(2) },
                        { title: '夏普', dataIndex: 'sharpe_ratio', render: (v: number) => v?.toFixed(2) },
                        { title: '回撤%', dataIndex: 'max_drawdown_pct', render: (v: number) => v?.toFixed(2) },
                        { title: '胜率%', dataIndex: 'win_rate', render: (v: number) => v?.toFixed(1) },
                        { title: '交易数', dataIndex: 'total_trades' },
                      ]}
                    />
                  </Card>
                )}

                {!backtestResult && !optimizationResult && !backtestLoading && !optimizationLoading && (
                  <Empty description="点击上方按钮运行回测或参数优化" />
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
                  description="当IV > HV时, 市场高估转债波动率, 买入转债+做空正股捕获波动率溢价"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={4}><Statistic title="候选总数" value={deltaCandidates.length} suffix="只" /></Col>
                  <Col span={4}><Statistic title="平均IV-HV" value={deltaCandidates.length > 0 ? (deltaCandidates.reduce((s, c) => s + c.iv_hv_diff, 0) / deltaCandidates.length).toFixed(1) : '0'} suffix="%" valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={4}><Statistic title="最大IV-HV" value={deltaCandidates.length > 0 ? Math.max(...deltaCandidates.map(c => c.iv_hv_diff)).toFixed(1) : '0'} suffix="%" valueStyle={{ color: '#ff4d4f' }} /></Col>
                  <Col span={4}><Statistic title="对冲α" value="+0.5~1.5%/年" valueStyle={{ color: '#722ed1' }} /></Col>
                  <Col span={4}><Statistic title="回撤改善" value="-2~4%" valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={4}><Button onClick={loadDeltaCandidates}>刷新候选</Button></Col>
                </Row>
                <Table
                  dataSource={deltaCandidates}
                  size="small" pagination={{ pageSize: 15 }} rowKey="code"
                  columns={[
                    { title: '排名', key: 'rank', width: 60, render: (_: any, _r: any, i: number) => <span style={{ color: i < 3 ? '#faad14' : undefined, fontWeight: 'bold' }}>#{i + 1}</span> },
                    { title: '代码', dataIndex: 'code', width: 90, render: (c: string) => <a onClick={() => handleViewDetail(c)}>{c}</a> },
                    { title: '名称', dataIndex: 'name', width: 100 },
                    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => v?.toFixed(2) },
                    { title: 'IV', dataIndex: 'iv', width: 80, render: (v: number) => `${v}%` },
                    { title: 'HV', dataIndex: 'hv', width: 80, render: (v: number) => `${v}%` },
                    { title: 'IV-HV差', dataIndex: 'iv_hv_diff', width: 100, render: (v: number) => <Text style={{ color: '#52c41a', fontWeight: 'bold' }}>+{v}%</Text> },
                    { title: '溢价率', dataIndex: 'premium_ratio', width: 90, render: (v: number) => `${v}%` },
                    { title: 'Delta', dataIndex: 'delta', width: 80, render: (v: number) => v?.toFixed(3) },
                    { title: '对冲α', dataIndex: 'alpha_potential', width: 100, render: (v: string) => <Text style={{ color: '#722ed1' }}>{v}</Text> },
                  ]}
                />
                <Divider>Greeks分解汇总 ({greeksData?.total || 0}只)</Divider>
                {greeksData && (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={4}><Card size="small"><Statistic title="Delta δ" value={greeksData.summary.delta_mean?.toFixed(3)} valueStyle={{ color: '#1677ff' }} /></Card></Col>
                      <Col span={4}><Card size="small"><Statistic title="Gamma γ" value={greeksData.summary.gamma_mean?.toFixed(4)} valueStyle={{ color: '#722ed1' }} /></Card></Col>
                      <Col span={4}><Card size="small"><Statistic title="Vega ν" value={greeksData.summary.vega_mean?.toFixed(3)} valueStyle={{ color: '#faad14' }} /></Card></Col>
                      <Col span={4}><Card size="small"><Statistic title="Theta θ" value={greeksData.summary.theta_mean?.toFixed(6)} valueStyle={{ color: '#52c41a' }} /></Card></Col>
                      <Col span={4}><Card size="small"><Statistic title="IV均值" value={greeksData.summary.iv_mean?.toFixed(1)} suffix="%" /></Card></Col>
                      <Col span={4}><Card size="small"><Statistic title="高Delta" value={greeksData.distribution.high_delta} suffix="只" valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
                    </Row>
                    <Row gutter={16}>
                      <Col span={12}><Card size="small"><Statistic title="高Delta(>0.7, 进攻型)" value={greeksData.distribution.high_delta} suffix="只" /></Card></Col>
                      <Col span={12}><Card size="small"><Statistic title="中Delta(0.3-0.7, 平衡型)" value={greeksData.distribution.mid_delta} suffix="只" /></Card></Col>
                    </Row>
                  </>
                )}
              </>
            ),
          },
          {
            key: 'compare',
            label: <span><LineChartOutlined /> 策略对比</span>,
            children: (
              <>
                <Alert
                  message="璇玑 vs 其他策略对比"
                  description="将璇玑十二因子与其他策略(multi_factor/songgang_seven)进行多维度对比"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={6}><Statistic title="筛选池" value={strategyCompare?.total_bonds || 0} suffix="只" /></Col>
                  <Col span={6}><Statistic title="Top N" value={strategyCompare?.top_n || 50} /></Col>
                  <Col span={6}><Statistic title="策略数" value={strategyCompare?.strategies?.length || 0} /></Col>
                  <Col span={6}><Button onClick={() => fetchXuanjiComparison(50).then(setStrategyCompare)}>刷新对比</Button></Col>
                </Row>
                <Table
                  dataSource={strategyCompare?.strategies?.map((s, i) => ({ key: String(i), ...s })) || []}
                  size="small" pagination={false}
                  columns={[
                    { title: '策略', dataIndex: 'name', width: 150, render: (v: string, r: any) => <Tag color={r.id === 'xuanji_twelve' ? 'purple' : r.id === 'multi_factor' ? 'blue' : 'cyan'}>{v}</Tag> },
                    { title: '因子数', dataIndex: 'factors', width: 80 },
                    { title: '市场自适应', dataIndex: 'market_adaptive', width: 100, render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
                    { title: '选中数', dataIndex: 'selected', width: 80 },
                    { title: '平均价格', dataIndex: 'avg_price', width: 100, render: (v: number) => v?.toFixed(2) },
                    { title: '平均评分', dataIndex: 'avg_score', width: 100, render: (v: number) => v?.toFixed(3) },
                    { title: '与璇玑重叠%', dataIndex: 'overlap_with_xuanji', width: 110, render: (v: number) => <Tag color={v === 100 ? 'purple' : 'blue'}>{v}%</Tag> },
                    { title: '与多因子重叠%', dataIndex: 'overlap_with_mf', width: 110 },
                    { title: '与松岗重叠%', dataIndex: 'overlap_with_sg', width: 110 },
                  ]}
                />
                <Divider>策略能力对比</Divider>
                <Table
                  dataSource={[
                    { key: '1', metric: '因子数量', xuanji: '12', multi: '5', songgang: '11(7+4)' },
                    { key: '2', metric: '市场状态', xuanji: '5态自适应', multi: '静态', songgang: '静态' },
                    { key: '3', metric: '波动率调权', xuanji: '✓', multi: '✗', songgang: '✗' },
                    { key: '4', metric: 'Greeks分解', xuanji: '✓', multi: '✗', songgang: '✗' },
                    { key: '5', metric: 'Delta对冲', xuanji: '✓', multi: '✗', songgang: '✗' },
                    { key: '6', metric: '事件驱动', xuanji: '✓', multi: '✗', songgang: '✗' },
                    { key: '7', metric: '中性年化', xuanji: '12.8%', multi: '8-10%', songgang: '10-12%' },
                    { key: '8', metric: '乐观年化', xuanji: '21.2%', multi: '12-15%', songgang: '15-18%' },
                  ]}
                  size="small" pagination={false}
                  columns={[
                    { title: '维度', dataIndex: 'metric', width: 120, render: (v: string) => <Text strong>{v}</Text> },
                    { title: '璇玑十二因子', dataIndex: 'xuanji', width: 150, render: (v: string) => <Tag color="purple">{v}</Tag> },
                    { title: '多因子策略', dataIndex: 'multi', width: 150, render: (v: string) => <Tag color="blue">{v}</Tag> },
                    { title: '松岗七维', dataIndex: 'songgang', width: 150, render: (v: string) => <Tag color="cyan">{v}</Tag> },
                  ]}
                />
              </>
            ),
          },
          {
            key: 'stress',
            label: <span><ThunderboltOutlined /> 压力测试</span>,
            children: (
              <>
                <Alert
                  message="6种极端场景压力测试"
                  description="评估璇玑策略在牛市/熊市/暴跌/震荡/利率上行/信用风险等场景下的表现"
                  type="warning" showIcon style={{ marginBottom: 16 }}
                />
                {stressData && (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}><Statistic title="平均收益" value={stressData.summary.avg_return} suffix="%" valueStyle={{ color: stressData.summary.avg_return > 0 ? '#52c41a' : '#ff4d4f' }} /></Col>
                      <Col span={6}><Statistic title="最好情况" value={stressData.summary.best_case} suffix="%" valueStyle={{ color: '#52c41a' }} /></Col>
                      <Col span={6}><Statistic title="最坏情况" value={stressData.summary.worst_case} suffix="%" valueStyle={{ color: '#ff4d4f' }} /></Col>
                      <Col span={6}><Statistic title="期望夏普" value={stressData.summary.expected_sharpe} valueStyle={{ color: '#722ed1' }} /></Col>
                    </Row>
                    <Table
                      dataSource={stressData.scenarios.map((s, i) => ({ key: String(i), ...s }))}
                      size="small" pagination={false}
                      columns={[
                        { title: '场景', dataIndex: 'name', width: 120, render: (v: string) => <Tag color="purple">{v}</Tag> },
                        { title: '描述', dataIndex: 'description' },
                        { title: '预期收益%', dataIndex: 'expected_return', width: 100, render: (v: number) => <Text style={{ color: v > 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>{v > 0 ? '+' : ''}{v}%</Text> },
                        { title: '最大回撤%', dataIndex: 'max_drawdown', width: 100, render: (v: number) => <Text style={{ color: '#ff4d4f' }}>{v}%</Text> },
                        { title: '胜率%', dataIndex: 'win_rate', width: 80, render: (v: number) => <Progress percent={v} size="small" /> },
                        { title: '选中数', dataIndex: 'selected_count', width: 80 },
                      ]}
                    />
                  </>
                )}
              </>
            ),
          },
          {
            key: 'attribution',
            label: <span><FundOutlined /> 因子归因</span>,
            children: (
              <>
                <Alert
                  message="因子贡献度与相关性分析"
                  description="评估各因子对综合评分的实际贡献，识别冗余因子以优化权重配置"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />
                {factorContrib && (
                  <>
                    <Title level={5}>因子贡献度 (Top{factorContrib.top_n})</Title>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}><Statistic title="总评分" value={factorContrib.total_score?.toFixed(4)} valueStyle={{ color: '#722ed1' }} /></Col>
                      <Col span={6}><Statistic title="平均价格" value={factorContrib.selection?.avg_price} /></Col>
                      <Col span={6}><Statistic title="平均溢价" value={factorContrib.selection?.avg_premium} suffix="%" /></Col>
                      <Col span={6}><Statistic title="平均HV" value={factorContrib.selection?.avg_hv} suffix="%" /></Col>
                    </Row>
                    <Table
                      dataSource={factorContrib.factors.map((f, i) => ({ key: String(i), ...f }))}
                      size="small" pagination={false}
                      columns={[
                        { title: '排名', key: 'rank', width: 60, render: (_: any, _r: any, i: number) => <Tag color="purple">#{i + 1}</Tag> },
                        { title: '因子', dataIndex: 'name', width: 120 },
                        { title: '平均评分', dataIndex: 'mean_score', width: 100, render: (v: number) => v?.toFixed(3) },
                        { title: '权重', dataIndex: 'weight', width: 80, render: (v: number) => `${(v * 100).toFixed(1)}%` },
                        { title: '贡献度', dataIndex: 'contribution', width: 100, render: (v: number) => v?.toFixed(4) },
                        {
                          title: '贡献占比%', dataIndex: 'contribution_pct', width: 200,
                          render: (v: number) => <Progress percent={v} size="small" strokeColor={scoreColor(v / 100)} format={(p) => `${p?.toFixed(1)}%`} />
                        },
                      ]}
                    />
                  </>
                )}
                <Divider>因子相关性分析 (识别冗余)</Divider>
                {factorCorr && (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}><Statistic title="相关性对数" value={factorCorr.total_pairs} /></Col>
                      <Col span={6}><Statistic title="高冗余对" value={factorCorr.high_redundancy_pairs} valueStyle={{ color: '#ff4d4f' }} /></Col>
                      <Col span={6}><Statistic title="市场状态" value={factorCorr.market_state} /></Col>
                      <Col span={6}><Statistic title="样本数" value={factorCorr.top_n} /></Col>
                    </Row>
                    {factorCorr.high_redundancy_pairs > 0 && (
                      <Alert
                        message={`发现${factorCorr.high_redundancy_pairs}对高冗余因子(|r|>0.7)`}
                        description="建议合并或剔除冗余因子以简化模型"
                        type="error" showIcon style={{ marginBottom: 16 }}
                      />
                    )}
                    <Table
                      dataSource={factorCorr.correlations.map((c, i) => ({ key: String(i), ...c }))}
                      size="small" pagination={{ pageSize: 10 }}
                      columns={[
                        { title: '因子1', dataIndex: 'factor1', render: (v: string) => <Tag color="blue">{WEIGHT_LABELS[v] || v}</Tag> },
                        { title: '因子2', dataIndex: 'factor2', render: (v: string) => <Tag color="cyan">{WEIGHT_LABELS[v] || v}</Tag> },
                        { title: '相关系数', dataIndex: 'correlation', render: (v: number) => <Text style={{ color: v > 0 ? '#52c41a' : '#ff4d4f' }}>{v?.toFixed(3)}</Text> },
                        { title: '|r|', dataIndex: 'abs_correlation', render: (v: number) => v?.toFixed(3) },
                        { title: '冗余度', dataIndex: 'redundancy', render: (v: string) => <Tag color={v === 'high' ? 'red' : v === 'medium' ? 'orange' : 'blue'}>{v}</Tag> },
                      ]}
                    />
                  </>
                )}
              </>
            ),
          },
        ]} />
      </Card>

      {/* 单券详情弹窗 */}
      <Modal
        title={<span><EyeOutlined /> {selectedCode} 璇玑十二因子详情</span>}
        open={detailVisible}
        onCancel={() => { setDetailVisible(false); setSelectedDetail(null) }}
        footer={null}
        width={900}
      >
        <Spin spinning={detailLoading}>
          {selectedDetail && (
            <>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}><Statistic title="综合评分" value={(selectedDetail.composite_score * 100).toFixed(1)} suffix="/100" valueStyle={{ color: '#722ed1' }} /></Col>
                <Col span={8}><Statistic title="波动率调权" value={selectedDetail.vol_factor?.toFixed(3)} valueStyle={{ color: '#1677ff' }} /></Col>
                <Col span={8}><Statistic title="市场状态" value={selectedDetail.market_state} valueStyle={{ color: '#fa8c16' }} /></Col>
              </Row>
              <Row gutter={16}>
                <Col span={12}>
                  <Title level={5}>12因子评分</Title>
                  <div ref={radarChartRef} style={{ height: 300 }} />
                </Col>
                <Col span={12}>
                  <Title level={5}>因子明细</Title>
                  <Table
                    dataSource={Object.entries(selectedDetail.factor_scores).map(([k, v]) => ({
                      key: k,
                      factor: WEIGHT_LABELS[k] || k,
                      score: (v.value * 100).toFixed(1),
                      weight: (v.weight * 100).toFixed(1),
                    }))}
                    size="small" pagination={false}
                    columns={[
                      { title: '因子', dataIndex: 'factor' },
                      { title: '评分', dataIndex: 'score', render: (v: string) => <Text style={{ color: '#722ed1' }}>{v}</Text> },
                      { title: '权重%', dataIndex: 'weight' },
                    ]}
                  />
                </Col>
              </Row>
              <Divider>基本信息</Divider>
              <Descriptions bordered size="small" column={4}>
                <Descriptions.Item label="价格">{selectedDetail.basic_info.price}</Descriptions.Item>
                <Descriptions.Item label="溢价率">{selectedDetail.basic_info.premium_ratio}%</Descriptions.Item>
                <Descriptions.Item label="双低值">{selectedDetail.basic_info.dual_low}</Descriptions.Item>
                <Descriptions.Item label="涨跌%">{selectedDetail.basic_info.change_pct}</Descriptions.Item>
                <Descriptions.Item label="YTM">{selectedDetail.basic_info.ytm || '-'}%</Descriptions.Item>
                <Descriptions.Item label="剩余年限">{selectedDetail.basic_info.remaining_years || '-'}</Descriptions.Item>
                <Descriptions.Item label="正股价">{selectedDetail.basic_info.stock_price || '-'}</Descriptions.Item>
                <Descriptions.Item label="转股价值">{selectedDetail.basic_info.conversion_value || '-'}</Descriptions.Item>
              </Descriptions>
              <Divider>Greeks近似</Divider>
              <Row gutter={16}>
                <Col span={6}><Statistic title="Delta δ" value={selectedDetail.greeks.delta?.toFixed(4)} valueStyle={{ color: '#1677ff' }} /></Col>
                <Col span={6}><Statistic title="Gamma γ" value={selectedDetail.greeks.gamma?.toFixed(4)} valueStyle={{ color: '#722ed1' }} /></Col>
                <Col span={6}><Statistic title="Vega ν" value={selectedDetail.greeks.vega?.toFixed(4)} valueStyle={{ color: '#faad14' }} /></Col>
                <Col span={6}><Statistic title="Theta θ" value={selectedDetail.greeks.theta?.toFixed(6)} valueStyle={{ color: '#52c41a' }} /></Col>
              </Row>
            </>
          )}
        </Spin>
      </Modal>
    </div>
  )
}
