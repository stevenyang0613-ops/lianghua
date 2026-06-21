/**
 * 璇玑十二因子指增策略页面
 *
 * 璇玑: 古代天文仪器，象征多维度精密分析
 * 12因子: 双低/HV/动量/YTM/期限/质量ROE/质量GPM/质量CAGR/估值PE/估值PB/事件/Delta
 * 5态市场: 极端牛/温和牛/震荡/温和熊/极端熊
 * Alpha源: A1-A12共12个alpha源
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Slider, Select, Space, Button, Progress, Modal, Descriptions,
  Alert, Divider, Tabs, InputNumber, Tooltip, Badge, Input, Switch, DatePicker
} from 'antd'
import {
  TrophyOutlined, ReloadOutlined, StarOutlined,
  ExperimentOutlined, ThunderboltOutlined, SafetyOutlined,
  InfoCircleOutlined, RiseOutlined, FallOutlined,
  LineChartOutlined, DashboardOutlined, FundOutlined,
  DownloadOutlined, BulbOutlined, RocketOutlined, EyeOutlined
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import dayjs from 'dayjs'
import { getApiBase } from '../utils/config'
import {
  fetchStrategies, runBacktestStream,
  fetchXuanjiRanking, fetchXuanjiSingle, fetchXuanjiDeltaCandidates,
  fetchXuanjiGreeks, fetchXuanjiMarketWeights, fetchXuanjiAlphaSources,
  fetchXuanjiStressTest, fetchXuanjiFactorContribution, fetchXuanjiFactorCorrelation,
  fetchXuanjiComparison, fetchXuanjiDataSourceHealth,
  fetchXuanjiIcirHistory, postXuanjiCustomRanking,
  type StrategyInfo, type BacktestResult, type XuanjiItem,
  type XuanjiSingleResponse, type XuanjiDeltaCandidate,
  type XuanjiGreeksSummary, type XuanjiMarketWeightsResponse,
  type XuanjiAlphaResponse, type OptimizationResult,
  type XuanjiStressResponse, type XuanjiFactorContributionResponse,
  type XuanjiFactorCorrelationResponse, type XuanjiComparisonResponse,
  type BacktestProgressEvent
} from '../services/api'
import { useXuanjiStore } from '../stores/useXuanjiStore'

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
  valuation: '估值', ytm: 'YTM', remaining_years: '期限', event: '事件', delta: 'Delta'
}

const INDUSTRY_COLORS: Record<string, string> = {
  '银行': '#1890ff', '非银金融': '#52c41a', '医药生物': '#fa541c',
  '电子': '#722ed1', '计算机': '#13c2c2', '化工': '#eb2f96',
  '机械设备': '#fa8c16', '汽车': '#fadb14', '房地产': '#a0d911',
  '传媒': '#2f54eb', '公用事业': '#52c41a',
}

// Hash-based color for any industry not in the predefined map
function getIndustryColor(industry: string): string {
  if (INDUSTRY_COLORS[industry]) return INDUSTRY_COLORS[industry]
  // Deterministic hash → color
  let hash = 0
  for (let i = 0; i < industry.length; i++) {
    hash = industry.charCodeAt(i) + ((hash << 5) - hash)
  }
  const colors = ['#1677ff','#52c41a','#fa541c','#722ed1','#13c2c2','#eb2f96','#fa8c16','#2f54eb','#a0d911','#f5222d','#1890ff','#389e0d','#d48806','#597ef7','#36cfc9','#f759ab','#ff7a45','#9254de','#40a9ff','#73d13d']
  return colors[Math.abs(hash) % colors.length]
}

function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return {
    topN: 50, marketState: 'mild_bull', holdCount: 20, rebalanceDays: 20,
    maxPremium: 50, minPrice: 90, maxPrice: 150, volAdjust: 0.85, stopLossPct: -8,
    autoDetect: true,
    deltaMinIvHv: 5.0, deltaPremiumLow: 20, deltaPremiumHigh: 80, deltaTopN: 30,
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
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export default function XuanjiIndex() {
  const savedConfig = useMemo(() => loadConfig(), [])

  // Shared store — only keep what's needed for non-local state actions
  const storeRankingData = useXuanjiStore((s) => s.rankingData)
  const storeRankingInfo = useXuanjiStore((s) => s.rankingInfo)
  const storeRankingLoading = useXuanjiStore((s) => s.rankingLoading)
  const storeLoadRanking = useXuanjiStore((s) => s.loadRanking)
  const storeLoadStaticData = useXuanjiStore((s) => s.loadStaticData)
  const storeLoadComputedData = useXuanjiStore((s) => s.loadComputedData)
  const storeLoadDeltaCandidates = useXuanjiStore((s) => s.loadDeltaCandidates)

  const [rankingLoading, setRankingLoading] = useState(false)
  const [rankingData, setRankingData] = useState<XuanjiItem[]>([])
  const [rankingInfo, setRankingInfo] = useState<any>(null)
  const [rankParams, setRankParams] = useState<any>(null)
  const [topN, setTopN] = useState(savedConfig.topN)
  const [marketState, setMarketState] = useState(savedConfig.marketState)
  const [holdCount, setHoldCount] = useState(savedConfig.holdCount)
  const [rebalanceDays, setRebalanceDays] = useState(savedConfig.rebalanceDays)
  const [maxPremium, setMaxPremium] = useState(savedConfig.maxPremium)
  const [minPrice, setMinPrice] = useState(savedConfig.minPrice)
  const [maxPrice, setMaxPrice] = useState(savedConfig.maxPrice)
  const [volAdjust, setVolAdjust] = useState(savedConfig.volAdjust)
  const [stopLossPct, setStopLossPct] = useState(savedConfig.stopLossPct ?? -8)
  const [autoDetect, setAutoDetect] = useState(savedConfig.autoDetect)
  const [deltaMinIvHv, setDeltaMinIvHv] = useState(savedConfig.deltaMinIvHv)
  const [deltaPremiumLow, setDeltaPremiumLow] = useState(savedConfig.deltaPremiumLow)
  const [deltaPremiumHigh, setDeltaPremiumHigh] = useState(savedConfig.deltaPremiumHigh)
  const [deltaTopN, setDeltaTopN] = useState(savedConfig.deltaTopN)

  // Backtest states
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtestProgress, setBacktestProgress] = useState<BacktestProgressEvent | null>(null)
  const [optimizationLoading, setOptimizationLoading] = useState(false)
  const [dataStale, setDataStale] = useState(false)
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null)
  const [optimizationResult, setOptimizationResult] = useState<OptimizationResult | null>(null)
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [btStartDate, setBtStartDate] = useState(() => {
    const d = new Date(); d.setFullYear(d.getFullYear() - 2)
    return d.toISOString().slice(0, 10)
  })
  const [btEndDate, setBtEndDate] = useState(() => {
    const d = new Date()
    return d.toISOString().slice(0, 10)
  })

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
  const [dataSourceHealth, setDataSourceHealth] = useState<any>(null)
  const [icirHistory, setIcirHistory] = useState<any>(null)
  const [customWeights, setCustomWeights] = useState<Record<string, number>>({})
  const [customRankResult, setCustomRankResult] = useState<any>(null)
  const [customRankLoading, setCustomRankLoading] = useState(false)

  const [activeTab, setActiveTab] = useState('ranking')

  const effectiveState = useMemo(() => autoDetect ? 'auto' : marketState, [autoDetect, marketState])

  // Sync ranking data from store (for cross-navigation persistence)
  useEffect(() => { if (storeRankingData.length > 0) setRankingData(storeRankingData) }, [storeRankingData])
  useEffect(() => { if (storeRankingInfo) setRankingInfo(storeRankingInfo) }, [storeRankingInfo])

  // Combined ranking loading state
  const rankingLoadingCombined = storeRankingLoading || rankingLoading

  // Load initial data — parallel batch loading
  useEffect(() => {
    fetchStrategies().then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setStrategies(d) }).catch(() => {})
    // Load all static data in parallel via store
    storeLoadStaticData()
  }, [])

  useEffect(() => {
    // Load ranking + computed data in parallel
    const params = { topN, marketState: autoDetect ? 'auto' : marketState, maxPremium, minPrice, maxPrice, volAdjust }
    storeLoadRanking(params)
    storeLoadComputedData({ topN, marketState: autoDetect ? 'auto' : marketState })
    // Also load delta candidates
    storeLoadDeltaCandidates({ minIvHv: deltaMinIvHv, premiumLow: deltaPremiumLow, premiumHigh: deltaPremiumHigh, topN: deltaTopN })
  }, [topN, marketState, maxPremium, minPrice, maxPrice, volAdjust, autoDetect, deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN])

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
        totalUnfiltered: result.total_unfiltered ?? 0,
        returned: result.returned,
        detected: result.market_state_detected,
        actual: result.market_state_actual,
        weights: result.market_weights,
        factorNames: result.factor_names,
      })
      setRankParams(result.params)
    } catch (e: any) {
      message.error(`加载排名失败: ${e.message}`)
      setRankingData([])
    } finally {
      setRankingLoading(false)
    }
  }, [topN, marketState, maxPremium, minPrice, maxPrice, volAdjust, autoDetect])

  const loadDeltaCandidates = useCallback(async () => {
    try {
      const result = await fetchXuanjiDeltaCandidates(deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN)
      setDeltaCandidates(result.items || [])
    } catch (e: any) {
      console.error('[Xuanji] Delta candidates load failed:', e)
      message.error(`加载Delta候选失败: ${e.message}`)
    }
  }, [deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN])

  // Tab change handler — load data on demand
  const handleTabChange = useCallback((key: string) => {
    setActiveTab(key)
    if (key === 'stress' && !stressData) {
      fetchXuanjiStressTest(50, effectiveState).then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setStressData(d) }).catch(() => {})
    }
    if (key === 'weights' && !icirHistory) {
      fetchXuanjiIcirHistory().then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setIcirHistory(d) }).catch(() => {})
    }
    if (key === 'attribution') {
      if (!factorContrib) {
        fetchXuanjiFactorContribution(20, effectiveState).then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setFactorContrib(d) }).catch(() => {})
      }
      if (!factorCorr) {
        fetchXuanjiFactorCorrelation(50, effectiveState).then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setFactorCorr(d) }).catch(() => {})
      }
    }
    if (key === 'compare' && !strategyCompare) {
      fetchXuanjiComparison(50, effectiveState).then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setStrategyCompare(d) }).catch(() => {})
    }
    if (key === 'delta' && deltaCandidates.length === 0) {
      fetchXuanjiDeltaCandidates(deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN).then(r => setDeltaCandidates(r.items || [])).catch(() => {})
    }
    if (key === 'health' && !dataSourceHealth) {
      fetchXuanjiDataSourceHealth().then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setDataSourceHealth(d) }).catch(() => {})
    }
  }, [effectiveState, stressData, factorContrib, factorCorr, strategyCompare, deltaCandidates, deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN, dataSourceHealth])

  useEffect(() => {
    loadRanking()
    loadDeltaCandidates()
    fetch(getApiBase() + '/api/v1/backtest/data-freshness')
      .then(r => r.json())
      .then(d => { if (d.stale) setDataStale(true) })
      .catch(() => {})
  }, [loadRanking, loadDeltaCandidates])

  const saveConfigTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const loadSeqRef = useRef(0)
  useEffect(() => {
    if (saveConfigTimer.current) clearTimeout(saveConfigTimer.current)
    saveConfigTimer.current = setTimeout(() => {
      saveConfig({ topN, marketState, holdCount, rebalanceDays, maxPremium, minPrice, maxPrice, volAdjust, stopLossPct, autoDetect, deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN })
    }, 1000)
    return () => { if (saveConfigTimer.current) clearTimeout(saveConfigTimer.current) }
  }, [topN, marketState, holdCount, rebalanceDays, maxPremium, minPrice, maxPrice, volAdjust, autoDetect, deltaMinIvHv, deltaPremiumLow, deltaPremiumHigh, deltaTopN])

  // Backtest
  const handleRunBacktest = useCallback(async () => {
    setBacktestLoading(true)
    setBacktestProgress(null)
    try {
      const result = await runBacktestStream(
        {
          strategy: 'xuanji_twelve',
          params: {
            hold_count: holdCount,
            rebalance_days: rebalanceDays,
            market_state: effectiveState,
            max_premium: maxPremium,
            min_price: minPrice,
            max_price: maxPrice,
            vol_adjust: volAdjust,
            stop_loss_pct: stopLossPct,
          },
          start_date: btStartDate,
          end_date: btEndDate,
          config: { commission_pct: 0.0003, slippage_pct: 0.0003, min_commission: 1, risk_free_rate: 0.02 },
        },
        (evt) => setBacktestProgress(evt),
      )
      if (result.type === 'backtest') {
        setBacktestResult(result.result as BacktestResult)
        setOptimizationResult(null)
        message.success('回测完成')
      }
    } catch (e: any) {
      message.error(`回测失败: ${e.message}`)
    } finally {
      setBacktestLoading(false)
      setBacktestProgress(null)
    }
  }, [holdCount, rebalanceDays, effectiveState, maxPremium, minPrice, maxPrice, volAdjust, stopLossPct, btStartDate, btEndDate])

  // Optimization
  const handleRunOptimization = useCallback(async () => {
    setOptimizationLoading(true)
    setBacktestProgress(null)
    try {
      const result = await runBacktestStream(
        {
          strategy: 'xuanji_twelve',
          params: {
            hold_count: holdCount, rebalance_days: rebalanceDays, market_state: effectiveState,
            max_premium: maxPremium, min_price: minPrice, max_price: maxPrice, vol_adjust: volAdjust,
            stop_loss_pct: stopLossPct,
          },
          start_date: btStartDate,
          end_date: btEndDate,
          config: { commission_pct: 0.0003, slippage_pct: 0.0003, min_commission: 1, risk_free_rate: 0.02 },
          optimization: {
            enabled: true,
            param_ranges: [
              { name: 'hold_count', min_val: 10, max_val: 40, step: 5 },
              { name: 'rebalance_days', min_val: 5, max_val: 30, step: 5 },
              { name: 'max_premium', min_val: 20, max_val: 80, step: 10 },
              { name: 'min_price', min_val: 85, max_val: 105, step: 5 },
              { name: 'max_price', min_val: 130, max_val: 180, step: 10 },
              { name: 'vol_adjust', min_val: 0.5, max_val: 1.0, step: 0.1 },
              { name: 'stop_loss_pct', min_val: -20, max_val: -2, step: 2 },
            ],
            optimize_metric: 'sharpe_ratio',
            max_iterations: 100,
            top_n: 10,
            parallel_workers: 1,
          },
        },
        (evt) => setBacktestProgress(evt),
      )
      if (result.type === 'optimization') {
        setOptimizationResult(result.result as OptimizationResult)
        setBacktestResult(null)
        message.success('参数优化完成')
      }
    } catch (e: any) {
      message.error(`优化失败: ${e.message}`)
    } finally {
      setOptimizationLoading(false)
      setBacktestProgress(null)
    }
  }, [holdCount, rebalanceDays, effectiveState, maxPremium, minPrice, maxPrice, volAdjust, stopLossPct, btStartDate, btEndDate])

  // Single bond detail
  const handleViewDetail = useCallback(async (code: string) => {
    setSelectedCode(code)
    setDetailVisible(true)
    setDetailLoading(true)
    try {
      const stateForDetail = autoDetect
        ? (rankingInfo?.actual || 'neutral')
        : marketState
      const detail = await fetchXuanjiSingle(code, stateForDetail, maxPremium, minPrice, maxPrice, volAdjust)
      setSelectedDetail(detail)
    } catch (e: any) {
      message.error(`加载详情失败: ${e.message}`)
    } finally {
      setDetailLoading(false)
    }
  }, [marketState, autoDetect, rankingInfo, maxPremium, minPrice, maxPrice])

  const weightChartOption = useMemo(() => {
    if (!marketWeights?.states) return null
    const allWeights = marketWeights.states
    const seriesData = allWeights.map(s => ({
      name: MARKET_STATES.find(ms => ms.value === s.value)?.label || s.value,
      value: Object.entries(s.weights).map(([k, v]) => +((v as number) * 100).toFixed(1))
    }))
    return {
      title: { text: '5态市场权重雷达图', left: 'center' },
      tooltip: {},
      legend: { data: allWeights.map(s => MARKET_STATES.find(ms => ms.value === s.value)?.label || s.value), top: 30 },
      radar: { indicator: Object.keys(WEIGHT_LABELS).map(k => ({ name: WEIGHT_LABELS[k], max: 50 })) },
      series: [{ type: 'radar', data: seriesData }],
    }
  }, [marketWeights])

  const equityChartOption = useMemo(() => {
    if (!backtestResult) return null
    const data = backtestResult.equity_curve || []
    const dates = data.map((d: any) => d.date)
    const values = data.map((d: any) => d.value)
    const benchmark = backtestResult.benchmark_curve?.map((d: any) => d.value) || []
    return {
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
    }
  }, [backtestResult])

  const industryChartOption = useMemo(() => {
    if (!rankingData || rankingData.length === 0) return null
    const industryCount: Record<string, number> = {}
    rankingData.forEach(item => {
      const ind = item.industry || '其他'
      industryCount[ind] = (industryCount[ind] || 0) + 1
    })
    const pieData = Object.entries(industryCount).map(([k, v]) => ({ name: k, value: v }))
    return {
      title: { text: '行业分布', left: 'center' },
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{ type: 'pie', radius: ['40%', '70%'], data: pieData, label: { formatter: '{b}\n{d}%' } }],
    }
  }, [rankingData])

  const contribChartOption = useMemo(() => {
    if (!factorContrib) return null
    const sorted = [...factorContrib.factors].sort((a, b) => b.contribution_pct - a.contribution_pct)
    return {
      title: { text: '因子贡献占比', left: 'center' },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { top: 40, left: 60, right: 30, bottom: 50 },
      xAxis: { type: 'category', data: sorted.map(f => f.name), axisLabel: { rotate: 30 } },
      yAxis: { type: 'value', name: '占比%' },
      series: [{
        type: 'bar', data: sorted.map(f => ({ value: f.contribution_pct, itemStyle: { color: f.contribution_pct > 20 ? '#722ed1' : f.contribution_pct > 10 ? '#1677ff' : '#52c41a' } })),
        label: { show: true, position: 'top', formatter: '{c}%' },
      }],
    }
  }, [factorContrib])

  const radarChartOption = useMemo(() => {
    if (!selectedDetail) return null
    const factorScores = selectedDetail.factor_scores
    const indicators = Object.keys(factorScores).map(k => ({ name: WEIGHT_LABELS[k] || k, max: 0.5 }))
    const values = Object.values(factorScores).map(s => s.value)
    const weights = Object.values(factorScores).map(s => s.weight)
    return {
      title: { text: '因子评分雷达', left: 'center' },
      tooltip: {},
      legend: { data: ['评分 (0-1)', '权重 (0-0.5)'], top: 30 },
      radar: { indicator: indicators },
      series: [{
        type: 'radar',
        data: [
          { name: '评分 (0-1)', value: values, areaStyle: { color: 'rgba(114, 46, 209, 0.3)' }, lineStyle: { color: '#722ed1' } },
          { name: '权重 (0-0.5)', value: weights, areaStyle: { color: 'rgba(82, 196, 26, 0.2)' }, lineStyle: { color: '#52c41a' } },
        ],
      }],
    }
  }, [selectedDetail])

  const heatmapChartOption = useMemo(() => {
    if (!factorCorr?.correlations || factorCorr.correlations.length === 0) return null
    const factors = ['dual_low', 'momentum', 'hv', 'quality', 'valuation', 'ytm', 'remaining_years', 'event', 'delta']
    const n = factors.length
    const matrix: number[][] = Array.from({ length: n }, () => Array(n).fill(0))
    const pairMap: Record<string, number> = {}
    for (const c of factorCorr.correlations) {
      pairMap[`${c.factor1}:${c.factor2}`] = c.correlation
      pairMap[`${c.factor2}:${c.factor1}`] = c.correlation
    }
    for (let i = 0; i < n; i++) {
      matrix[i][i] = 1.0
      for (let j = i + 1; j < n; j++) {
        const val = pairMap[`${factors[i]}:${factors[j]}`] || 0
        matrix[i][j] = val
        matrix[j][i] = val
      }
    }
    const labels = factors.map(k => WEIGHT_LABELS[k] || k)
    return {
      title: { text: '因子相关性热力图', left: 'center' },
      tooltip: { position: 'top', formatter: (p: any) => `${labels[p.data[0]]} × ${labels[p.data[1]]}: ${p.data[2].toFixed(3)}` },
      grid: { top: 60, left: 100, right: 40, bottom: 60 },
      xAxis: { type: 'category', data: labels, axisLabel: { rotate: 30 } },
      yAxis: { type: 'category', data: labels },
      visualMap: { min: -1, max: 1, inRange: { color: ['#ff4d4f', '#fff', '#52c41a'] }, calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
      series: [{
        type: 'heatmap', data: matrix.flatMap((row, i) => row.map((v, j) => [j, i, v])),
        label: { show: true, formatter: (p: any) => p.data[2].toFixed(2), fontSize: 10 },
        emphasis: { itemStyle: { shadowBlur: 10 } },
      }],
    }
  }, [factorCorr])

  const icirChartOption = useMemo(() => {
    if (!icirHistory?.scenarios) return null
    const labels = Object.keys(WEIGHT_LABELS).map(k => WEIGHT_LABELS[k])
    const states = icirHistory.scenarios
    return {
      title: { text: 'ICIR动态权重 vs 基准权重对比', left: 'center' },
      tooltip: { trigger: 'axis' },
      legend: { data: states.map((s: any) => `${s.state_name} ICIR`), top: 30 },
      grid: { top: 70, left: 60, right: 30, bottom: 60 },
      xAxis: { type: 'category', data: labels, axisLabel: { rotate: 30 } },
      yAxis: { type: 'value', name: '权重', max: 0.5 },
      series: states.map((s: any) => ({
        name: `${s.state_name} ICIR`,
        type: 'bar',
        data: Object.keys(WEIGHT_LABELS).map(k => (s.icir_weights[k] || 0) * 100),
        label: { show: true, position: 'top', formatter: (p: any) => `${p.data.toFixed(0)}%`, fontSize: 9 },
      })),
    }
  }, [icirHistory])

  const scoreColor = useCallback((v: number, max: number = 1): string => {
    const ratio = v / max
    if (ratio >= 0.8) return '#52c41a'
    if (ratio >= 0.6) return '#1677ff'
    if (ratio >= 0.4) return '#faad14'
    return '#ff4d4f'
  }, [])

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
      render: (v: string) => <Tag color={getIndustryColor(v)}>{v || '其他'}</Tag>,
    },
    {
      title: '评级', dataIndex: 'rating', key: 'rating', width: 60,
      render: (v: string) => <Tag color={v === 'AAA' ? 'gold' : v === 'AA+' ? 'orange' : 'blue'}>{v}</Tag>,
    },
    {
      title: 'ROE', dataIndex: 'roe', key: 'roe', width: 65,
      render: (v: number | null) => v != null ? <Text style={{ color: v > 15 ? '#52c41a' : v < 5 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: 'PE', dataIndex: 'pe', key: 'pe', width: 60,
      render: (v: number | null) => v != null ? <Text style={{ color: v < 20 ? '#52c41a' : v > 60 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: 'PB', dataIndex: 'pb', key: 'pb', width: 60,
      render: (v: number | null) => v != null ? <Text style={{ color: v < 2 ? '#52c41a' : v > 5 ? '#ff4d4f' : undefined }}>{v?.toFixed(2)}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: 'GPM', dataIndex: 'gpm', key: 'gpm', width: 65,
      render: (v: number | null) => v === -1 ? <Text type="secondary" style={{ fontSize: 11 }}>银行</Text> : v != null ? <Text style={{ color: v > 30 ? '#52c41a' : v < 10 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: 'CAGR', dataIndex: 'cagr', key: 'cagr', width: 70,
      render: (v: number | null) => v != null ? <Text style={{ color: v > 20 ? '#52c41a' : v < 0 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '负债率', dataIndex: 'debt_ratio', key: 'debt_ratio', width: 70,
      render: (v: number | null) => v != null ? <Text style={{ color: v < 50 ? '#52c41a' : v > 70 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '流动比', dataIndex: 'current_ratio', key: 'current_ratio', width: 70,
      render: (v: number | null) => v != null ? <Text style={{ color: v > 2 ? '#52c41a' : v < 1 ? '#ff4d4f' : undefined }}>{v?.toFixed(2)}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '换手率', dataIndex: 'turnover_rate', key: 'turnover_rate', width: 70,
      render: (v: number | null) => v != null ? <Text>{v?.toFixed(2)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '主力净流入', dataIndex: 'net_capital_flow', key: 'net_capital_flow', width: 95,
      render: (v: number | null) => {
        if (v == null) return <Text type="secondary">-</Text>
        const wan = v / 1e4
        return <Text style={{ color: wan > 0 ? '#52c41a' : wan < 0 ? '#ff4d4f' : undefined }}>{wan > 0 ? '+' : ''}{wan.toFixed(0)}万</Text>
      },
    },
    {
      title: '20日动量', dataIndex: 'momentum_20d', key: 'momentum_20d', width: 80,
      render: (v: number | null) => v != null ? <Text style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : undefined }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '60日动量', dataIndex: 'momentum_60d', key: 'momentum_60d', width: 80,
      render: (v: number | null) => v != null ? <Text style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : undefined }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '质押率', dataIndex: 'pledge_ratio', key: 'pledge_ratio', width: 70,
      render: (v: number | null) => v != null ? <Text style={{ color: v < 30 ? '#52c41a' : v > 50 ? '#ff4d4f' : undefined }}>{v?.toFixed(1)}%</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '剩余期限', dataIndex: 'remaining_years', key: 'remaining_years', width: 70,
      render: (v: number | null) => v != null ? <Text>{v.toFixed(2)}年</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '事件', dataIndex: 'event_score', key: 'event_score', width: 70,
      render: (v: number | null, r: XuanjiItem) => {
        if (v != null && v > 0.5) return <Tooltip title={r.event_detail || ''}><Tag color="green">利好</Tag></Tooltip>
        if (v != null && v < 0.3) return <Tooltip title={r.event_detail || ''}><Tag color="red">利空</Tag></Tooltip>
        return <Tag>中性</Tag>
      },
    },
    {
      title: '综合评分', dataIndex: 'score', key: 'score', width: 130,
      sorter: (a: XuanjiItem, b: XuanjiItem) => a.score - b.score,
      defaultSortOrder: 'descend' as const,
      render: (v: number) => <Progress percent={Math.min(v * 100, 100)} size="small" strokeColor={scoreColor(v)} format={(p) => p?.toFixed(1)} />,
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
              <Tag color="purple" style={{ marginLeft: 8 }}>v4.0</Tag>
            </Title>
            <Text type="secondary" style={{ fontSize: 12 }}>
              12因子 × 5态市场 × 12 Alpha源
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
              <Button icon={<ReloadOutlined />} onClick={loadRanking} loading={rankingLoadingCombined}>
                刷新
              </Button>
              <Button icon={<DownloadOutlined />} onClick={() => exportToCSV(rankingData, '璇玑排名.csv')}>
                导出CSV
              </Button>
            </Space>
          </Col>
        </Row>

        <Tabs activeKey={activeTab} onChange={handleTabChange} items={[
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
                      <Button type="primary" icon={<BulbOutlined />} onClick={loadRanking} loading={rankingLoadingCombined} block style={{ marginTop: 18 }}>
                        计算评分
                      </Button>
                    </Col>
                  </Row>
                </Card>

                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={3}><Statistic title="全市场" value={rankingInfo?.totalUnfiltered ?? 0} suffix="只" /></Col>
                  <Col span={3}><Statistic title="筛选池" value={rankingInfo?.total || 0} suffix="只" /></Col>
                  <Col span={3}><Statistic title="返回" value={rankingInfo?.returned || 0} suffix="只" /></Col>
                  <Col span={3}><Statistic title="市场状态" value={rankingInfo?.actual ? (MARKET_STATES.find(s => s.value === rankingInfo.actual)?.label || rankingInfo.actual) : '-'} /></Col>
                  <Col span={3}><Statistic title="波动率调权" value={rankParams?.vol_adjust?.toFixed(2) || '-'} suffix="×" /></Col>
                  <Col span={3}><Statistic title="溢价上限" value={rankParams?.max_premium || '-'} suffix="%" /></Col>
                  <Col span={3}><Statistic title="价格区间" value={rankParams ? `${rankParams.min_price}-${rankParams.max_price}` : '-'} /></Col>
                  <Col span={3}><Statistic title="因子数" value={rankingInfo?.weights ? Object.keys(rankingInfo.weights).length : '-'} /></Col>
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
                    {industryChartOption ? (
                    <ReactEChartsCore option={industryChartOption} style={{ height: 200 }} notMerge={true} />
                  ) : (
                    <div style={{ height: 200 }} />
                  )}
                  </Col>
                </Row>

                <Spin spinning={rankingLoadingCombined}>
                  {rankingData.length > 0 ? (
                    <Table dataSource={rankingData} columns={rankingColumns} rowKey="code" size="small"
                      pagination={{ pageSize: 20, showSizeChanger: true, showQuickJumper: true }} scroll={{ x: 1700 }} />
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
                        5态市场: 极端牛(动量28%) / 温和牛(动量24%) / 震荡(均衡) / 温和熊(防御) / 极端熊(双低47%)
                      </Text>
                    </Col>
                  </Row>
                </Card>
                {weightChartOption ? (
                  <ReactEChartsCore option={weightChartOption} style={{ height: 450 }} notMerge={true} />
                ) : (
                  <div style={{ height: 450, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>加载中...</div>
                )}
                <Row gutter={[8, 8]}>
                  {MARKET_STATES.map(state => {
                     const w = (rankingInfo?.actual === state.value && rankingInfo?.weights) ?
                       rankingInfo.weights : (marketWeights?.states?.find(s => s.value === state.value)?.weights || null)
                     return (
                       <Col span={4} key={state.value} style={{ display: 'flex' }}>
                         <Card size="small" style={{ flex: 1, border: marketState === state.value ? `2px solid ${state.color}` : undefined }}>
                           <Title level={5} style={{ color: state.color, margin: 0, fontSize: 13 }}>
                             {state.icon} {state.label}
                             {marketState === state.value && <Tag color="blue" style={{ marginLeft: 4, fontSize: 10 }}>当前</Tag>}
                           </Title>
                           {w ? (
                             <div style={{ marginTop: 4 }}>
                               {Object.entries(w).map(([key, val]) => (
                                 <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '1px 0', borderBottom: '1px solid #f0f0f0' }}>
                                   <span style={{ color: '#888' }}>{WEIGHT_LABELS[key] || key}</span>
                                   <span style={{ fontWeight: 600, color: (val as number) > 0.2 ? state.color : '#666' }}>{Math.round((val as number) * 100)}%</span>
                                 </div>
                               ))}
                             </div>
                           ) : (
                             <Text type="secondary" style={{ fontSize: 12 }}>加载中...</Text>
                           )}
                         </Card>
                       </Col>
                     )
                   })}
                 </Row>
                <Divider>ICIR动态权重 (模拟)</Divider>
                {icirChartOption ? (
                  <ReactEChartsCore option={icirChartOption} style={{ height: 400 }} notMerge={true} />
                ) : (
                  <Card size="small">
                    <Button onClick={() => fetchXuanjiIcirHistory().then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setIcirHistory(d) }).catch(() => {})}>加载ICIR数据</Button>
                  </Card>
                )}
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
                  description={alphaSources?.total_alpha_potential || '(暂无数据)'}
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
                    {Array.isArray(alphaSources?.return_path) && alphaSources.return_path.map((r: any, i: number) => (
                      <Col span={5} key={r.version}>
                        <Statistic title={r.version} value={r.neutral}
                          valueStyle={{ fontSize: 14, color: i === alphaSources.return_path.length - 1 ? '#722ed1' : '#1677ff' }} />
                        <Text type="secondary" style={{ fontSize: 12 }}>乐观 {r.optimistic}</Text>
                      </Col>
                    ))}
                    {Array.isArray(alphaSources?.return_path) && alphaSources.return_path.length > 0 && (
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
                {dataStale && (
                  <Alert type="warning" showIcon message="历史数据已过期 (>7天)，建议先运行种子接口 /backtest/seed 更新数据" closable onClose={() => setDataStale(false)} style={{ marginBottom: 12 }} />
                )}
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Row gutter={16}>
                    <Col span={3}>
                      <Text>开始</Text>
                      <DatePicker style={{ width: '100%' }} value={btStartDate ? dayjs(btStartDate) : undefined} onChange={d => setBtStartDate(d ? d.format('YYYY-MM-DD') : '')} />
                    </Col>
                    <Col span={3}>
                      <Text>结束</Text>
                      <DatePicker style={{ width: '100%' }} value={btEndDate ? dayjs(btEndDate) : undefined} onChange={d => setBtEndDate(d ? d.format('YYYY-MM-DD') : '')} />
                    </Col>
                    <Col span={2}>
                      <Text>持有数</Text>
                      <InputNumber min={5} max={50} value={holdCount} onChange={v => setHoldCount(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={2}>
                      <Text>调仓天</Text>
                      <InputNumber min={5} max={60} value={rebalanceDays} onChange={v => setRebalanceDays(v || 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={3}>
                      <Text>市场状态</Text>
                      <Select style={{ width: '100%' }} value={marketState} onChange={setMarketState}
                        options={MARKET_STATES.map(s => ({ value: s.value, label: s.label }))} />
                    </Col>
                    <Col span={2}>
                      <Tooltip title="单券止损阈值%, -8表示亏8%卖出">
                        <Text>止损%</Text>
                      </Tooltip>
                      <InputNumber min={-20} max={-2} step={1} value={stopLossPct} onChange={v => setStopLossPct(v ?? -8)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={9}>
                      <Space style={{ marginTop: 18 }}>
                        <Button type="primary" icon={<ExperimentOutlined />} onClick={handleRunBacktest} loading={backtestLoading}>
                          策略回测
                        </Button>
                        <Button icon={<RocketOutlined />} onClick={handleRunOptimization} loading={optimizationLoading}>
                          参数优化
                        </Button>
                        {backtestProgress && (backtestLoading || optimizationLoading) && (
                          <Text type="secondary" style={{ fontSize: 12 }}>{backtestProgress.msg} ({backtestProgress.pct}%)</Text>
                        )}
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
                      {equityChartOption ? (
                      <ReactEChartsCore option={equityChartOption} style={{ height: 400 }} notMerge={true} />
                    ) : (
                      <div style={{ height: 400 }} />
                    )}
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
                <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
                  <Row gutter={16} align="middle">
                    <Col span={5}>
                      <Text>最小IV-HV差 (%)</Text>
                      <InputNumber min={0} max={50} step={0.5} value={deltaMinIvHv} onChange={v => setDeltaMinIvHv(v ?? 5)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={5}>
                      <Text>溢价率下限 (%)</Text>
                      <InputNumber min={0} max={100} value={deltaPremiumLow} onChange={v => setDeltaPremiumLow(v ?? 20)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={5}>
                      <Text>溢价率上限 (%)</Text>
                      <InputNumber min={0} max={100} value={deltaPremiumHigh} onChange={v => setDeltaPremiumHigh(v ?? 80)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={5}>
                      <Text>Top N</Text>
                      <InputNumber min={5} max={100} value={deltaTopN} onChange={v => setDeltaTopN(v ?? 30)} style={{ width: '100%' }} />
                    </Col>
                    <Col span={4}>
                      <Button type="primary" onClick={loadDeltaCandidates} style={{ marginTop: 18, width: '100%' }}>应用筛选</Button>
                    </Col>
                  </Row>
                </Card>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={4}><Statistic title="候选总数" value={deltaCandidates.length} suffix="只" /></Col>
                  <Col span={4}><Statistic title="平均IV-HV" value={deltaCandidates.length > 0 ? (deltaCandidates.reduce((s, c) => s + c.iv_hv_diff, 0) / deltaCandidates.length).toFixed(1) : '0'} suffix="%" valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={4}><Statistic title="最大IV-HV" value={deltaCandidates.length > 0 ? Math.max(...deltaCandidates.map(c => c.iv_hv_diff)).toFixed(1) : '0'} suffix="%" valueStyle={{ color: '#ff4d4f' }} /></Col>
                  <Col span={4}><Statistic title="对冲α" value={deltaCandidates.length > 0 ? `${(deltaCandidates[0]?.iv_hv_diff || 0).toFixed(1)}bp` : '-'} valueStyle={{ color: '#722ed1' }} /></Col>
                  <Col span={4}><Statistic title="时间价值" value={greeksData ? `${(Math.abs(greeksData.summary.theta_mean) * 365 * 100).toFixed(1)}bp/年` : '-'} valueStyle={{ color: '#52c41a' }} /></Col>
                  <Col span={4}><Button onClick={loadDeltaCandidates}>刷新候选</Button></Col>
                </Row>
                <Table
                  dataSource={deltaCandidates}
                  size="small" pagination={{ pageSize: 15 }} rowKey="code"
                  columns={[
                    { title: '排名', key: 'rank', width: 60, render: (_: any, _r: any, i: number) => <span style={{ color: i < 3 ? '#faad14' : undefined, fontWeight: 'bold' }}>#{i + 1}</span> },
                    { title: '代码', dataIndex: 'code', width: 90, render: (c: string) => <a onClick={() => handleViewDetail(c)}>{c}</a> },
                    { title: '名称', dataIndex: 'name', width: 100 },
                    { title: '行业', dataIndex: 'industry', width: 80, render: (v: string) => <Tag color={getIndustryColor(v)}>{v || '其他'}</Tag> },
                    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => v?.toFixed(2) },
                    { title: 'IV', dataIndex: 'iv', width: 80, render: (v: number, r: XuanjiDeltaCandidate) => <Tooltip title={`来源: ${r.iv_source || '-'}`}>{v}%</Tooltip> },
                    { title: 'HV', dataIndex: 'hv', width: 80, render: (v: number, r: XuanjiDeltaCandidate) => <Tooltip title={`来源: ${r.hv_source || '-'}`}>{v}%</Tooltip> },
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
                      <Col span={4}><Card size="small"><Statistic title="低Delta(<0.3, 防守型)" value={greeksData.distribution.low_delta} suffix="只" valueStyle={{ color: '#52c41a' }} /></Card></Col>
                    </Row>
                    <Row gutter={16}>
                      <Col span={8}><Card size="small"><Statistic title="高Delta(>0.7, 进攻型)" value={greeksData.distribution.high_delta} suffix="只" /></Card></Col>
                      <Col span={8}><Card size="small"><Statistic title="中Delta(0.3-0.7, 平衡型)" value={greeksData.distribution.mid_delta} suffix="只" /></Card></Col>
                      <Col span={8}><Card size="small"><Statistic title="低Delta(<0.3, 防守型)" value={greeksData.distribution.low_delta} suffix="只" /></Card></Col>
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
                  description="将璇玑十二因子与其他策略(multi_factor/xibu_seven)进行多维度对比"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={6}><Statistic title="筛选池" value={strategyCompare?.total_bonds || 0} suffix="只" /></Col>
                  <Col span={6}><Statistic title="Top N" value={strategyCompare?.top_n || 50} /></Col>
                  <Col span={6}><Statistic title="策略数" value={strategyCompare?.strategies?.length || 0} /></Col>
                  <Col span={6}><Button onClick={() => fetchXuanjiComparison(50, effectiveState).then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setStrategyCompare(d) })}>刷新对比</Button></Col>
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
                    { title: '与西部重叠%', dataIndex: 'overlap_with_xb', width: 110 },
                  ]}
                />
                <Divider>策略能力对比</Divider>
                <Table
                  dataSource={[
                    { key: '1', metric: '因子数量', xuanji: '12', multi: '5', xibu: '11' },
                    { key: '2', metric: '市场状态', xuanji: '5态自适应', multi: '静态', xibu: '静态' },
                    { key: '3', metric: '选中重叠%', xuanji: `100%`, multi: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'multi_factor')?.overlap_with_xb; return v != null ? `${v.toFixed(0)}%` : '-' })(), xibu: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'xibu_seven')?.overlap_with_mf; return v != null ? `${v.toFixed(0)}%` : '-' })() },
                    { key: '4', metric: '平均价格', xuanji: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'xuanji_twelve')?.avg_price; return v != null ? v.toFixed(1) : '-' })(), multi: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'multi_factor')?.avg_price; return v != null ? v.toFixed(1) : '-' })(), xibu: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'xibu_seven')?.avg_price; return v != null ? v.toFixed(1) : '-' })() },
                    { key: '5', metric: '平均评分', xuanji: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'xuanji_twelve')?.avg_score; return v != null ? v.toFixed(3) : '-' })(), multi: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'multi_factor')?.avg_score; return v != null ? v.toFixed(3) : '-' })(), xibu: (() => { const v = strategyCompare?.strategies?.find(s => s.id === 'xibu_seven')?.avg_score; return v != null ? v.toFixed(3) : '-' })() },
                  ]}
                  size="small" pagination={false}
                  columns={[
                    { title: '维度', dataIndex: 'metric', width: 120, render: (v: string) => <Text strong>{v}</Text> },
                    { title: '璇玑十二因子', dataIndex: 'xuanji', width: 150, render: (v: string) => <Tag color="purple">{v}</Tag> },
                    { title: '多因子策略', dataIndex: 'multi', width: 150, render: (v: string) => <Tag color="blue">{v}</Tag> },
                    { title: '西部七维', dataIndex: 'xibu', width: 150, render: (v: string) => <Tag color="cyan">{v}</Tag> },
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
                  action={<Button size="small" icon={<ReloadOutlined />} onClick={() => fetchXuanjiStressTest(50, effectiveState).then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setStressData(d) }).catch(() => {})}>刷新</Button>}
                />
                {!stressData ? (
                  <Empty description="点击「刷新」加载压力测试数据" />
                ) : (
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
            key: 'sources',
            label: <span><DashboardOutlined /> 数据源</span>,
            children: (
              <>
                <Alert
                  message="数据源覆盖度监控"
                  description="检查各个维度的缓存数据覆盖率和健康状态"
                  type="info" showIcon style={{ marginBottom: 16 }}
                  action={<Button size="small" icon={<ReloadOutlined />} onClick={() => fetchXuanjiDataSourceHealth().then(d => { const seq = ++loadSeqRef.current; if (seq === loadSeqRef.current) setDataSourceHealth(d) }).catch(() => {})}>刷新</Button>}
                />
                {!dataSourceHealth ? (
                  <Empty description="加载数据源状态..." />
                ) : (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={4}><Statistic title="可转债总数" value={dataSourceHealth.total_bonds || 0} suffix="只" /></Col>
                      <Col span={4}><Statistic title="数据源" value={dataSourceHealth.summary?.sources_with_data || 0} suffix={`/${dataSourceHealth.summary?.total_sources || 0}`} /></Col>
                      <Col span={4}><Statistic title="平均覆盖率" value={dataSourceHealth.summary?.avg_coverage_pct || 0} suffix="%" /></Col>
                      <Col span={4}>
                        <Statistic title="正股代码已加载" value={dataSourceHealth.bond_stock_codes_loaded ? '是' : '否'}
                          valueStyle={{ color: dataSourceHealth.bond_stock_codes_loaded ? '#52c41a' : '#ff4d4f' }} />
                      </Col>
                    </Row>
                    <Table
                      dataSource={(dataSourceHealth.sources || []).map((s: any, i: number) => ({ key: String(i), ...s }))}
                      size="small" pagination={false}
                      columns={[
                        { title: '数据源', dataIndex: 'label', width: 130, render: (v: string) => <Tag color="blue">{v}</Tag> },
                        { title: '名称', dataIndex: 'name', width: 100 },
                        { title: '条目数', dataIndex: 'count', width: 70, render: (v: number) => <Text strong>{v}</Text> },
                        { title: '覆盖率', dataIndex: 'coverage_pct', width: 90, render: (v: number) => <Progress percent={Math.min(v, 100)} size="small" strokeColor={v > 80 ? '#52c41a' : v > 30 ? '#faad14' : '#ff4d4f'} format={(p) => `${p}%`} /> },
                        { title: '最后更新', dataIndex: 'last_update', width: 100, render: (v: string, r: any) => {
                          if (!v) return <Text type="secondary">未更新</Text>
                          const age = Date.now() / 1000 - (r.last_update_ts || 0)
                          const stale = age > 3600 * 6
                          return <Text style={{ color: stale ? '#ff4d4f' : undefined }}>{v}</Text>
                        }},
                        { title: '状态', dataIndex: 'has_data', width: 70, render: (v: boolean) => v ? <Tag color="green">有</Tag> : <Tag color="red">无</Tag> },
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
                {!factorContrib ? (
                  <Empty description="点击「刷新」加载因子贡献数据" />
                ) : (
                  <>
                    <Title level={5}>因子贡献度 (Top{factorContrib.top_n})</Title>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}><Statistic title="总评分" value={factorContrib.total_score?.toFixed(4)} valueStyle={{ color: '#722ed1' }} /></Col>
                      <Col span={6}><Statistic title="平均价格" value={factorContrib.selection?.avg_price} /></Col>
                      <Col span={6}><Statistic title="平均溢价" value={factorContrib.selection?.avg_premium} suffix="%" /></Col>
                      <Col span={6}><Statistic title="平均HV" value={factorContrib.selection?.avg_hv} suffix="%" /></Col>
                    </Row>
                    {contribChartOption ? (
                    <ReactEChartsCore option={contribChartOption} style={{ height: 300 }} notMerge={true} />
                  ) : (
                    <div style={{ height: 300 }} />
                  )}
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
                {!factorCorr ? (
                  <Empty description="点击「刷新」加载因子相关性数据" />
                ) : (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}><Statistic title="相关性对数" value={factorCorr.total_pairs} /></Col>
                      <Col span={6}><Statistic title="高冗余对" value={factorCorr.high_redundancy_pairs} valueStyle={{ color: '#ff4d4f' }} /></Col>
                       <Col span={6}><Statistic title="市场状态" value={MARKET_STATES.find(s => s.value === factorCorr.market_state)?.label || factorCorr.market_state || '-'} /></Col>
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
                    <Divider>相关性热力图</Divider>
                    {heatmapChartOption ? (
                      <ReactEChartsCore option={heatmapChartOption} style={{ height: 400 }} notMerge={true} />
                    ) : (
                      <Text type="secondary">数据不足以生成热力图（需要≥2个债券）</Text>
                    )}
                  </>
                )}
              </>
            ),
          },
          {
            key: 'custom',
            label: <span><ExperimentOutlined /> 自定义权重</span>,
            children: (
              <>
                <Alert
                  message="自定义因子权重组合"
                  description="拖动滑块调整各因子权重，实时查看自定义排名"
                  type="info" showIcon style={{ marginBottom: 16 }}
                />
                <Row gutter={16}>
                  <Col span={12}>
                    <Card size="small" title="因子权重配置">
                      {Object.entries(WEIGHT_LABELS).map(([key, label]) => (
                        <div key={key} style={{ marginBottom: 12 }}>
                          <Row align="middle">
                            <Col span={4}><Text style={{ fontSize: 12 }}>{label}</Text></Col>
                            <Col span={14}>
                              <Slider
                                min={0} max={100} step={1}
                                value={customWeights[key] ?? Math.round(((rankingInfo?.weights?.[key] || 0.11) * 100))}
                                onChange={(v) => setCustomWeights(prev => ({ ...prev, [key]: v }))}
                              />
                            </Col>
                            <Col span={4} offset={1}>
                              <InputNumber
                                min={0} max={100} style={{ width: 60 }}
                                value={customWeights[key] ?? Math.round(((rankingInfo?.weights?.[key] || 0.11) * 100))}
                                onChange={(v) => setCustomWeights(prev => ({ ...prev, [key]: v ?? 0 }))}
                              />
                            </Col>
                          </Row>
                        </div>
                      ))}
                      <Divider />
                      <Button
                        type="primary" icon={<BulbOutlined />} block
                        loading={customRankLoading}
                        onClick={async () => {
                          setCustomRankLoading(true)
                          try {
                            const result = await postXuanjiCustomRanking({
                              weights: Object.fromEntries(
                                Object.entries(customWeights).map(([k, v]) => [k, v / 100])
                              ),
                              top_n: topN,
                              market_state: autoDetect ? 'auto' : marketState,
                              max_premium: maxPremium,
                              min_price: minPrice,
                              max_price: maxPrice,
                            })
                            setCustomRankResult(result)
                            message.success(`自定义排名计算完成: ${result.returned} 只`)
                          } catch (e: any) {
                            message.error(`自定义排名失败: ${e.message}`)
                          } finally {
                            setCustomRankLoading(false)
                          }
                        }}
                      >
                        计算自定义排名
                      </Button>
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card size="small" title="自定义排名结果">
                      {!customRankResult ? (
                        <Empty description="调整左侧权重后点击「计算自定义排名」" />
                      ) : (
                        <Table
                          dataSource={customRankResult.items}
                          rowKey="code" size="small" pagination={{ pageSize: 10 }}
                          columns={[
                            { title: '排名', key: 'rank', width: 50, render: (_: any, _r: any, i: number) => <Tag color="purple">#{i + 1}</Tag> },
                            { title: '代码', dataIndex: 'code', width: 80, render: (c: string) => <a onClick={() => handleViewDetail(c)}>{c}</a> },
                            { title: '名称', dataIndex: 'name', width: 100 },
                            { title: '价格', dataIndex: 'price', width: 70, render: (v: number) => v?.toFixed(2) },
                            { title: '行业', dataIndex: 'industry', width: 80, render: (v: string) => <Tag color={getIndustryColor(v)}>{v || '其他'}</Tag> },
                            { title: '自定义评分', dataIndex: 'score', width: 120, render: (v: number) => <Progress percent={Math.min(v * 100, 100)} size="small" strokeColor={scoreColor(v)} format={(p) => p?.toFixed(1)} /> },
                          ]}
                        />
                      )}
                    </Card>
                  </Col>
                </Row>
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
                <Col span={6}><Statistic title="综合评分" value={(selectedDetail.composite_score * 100).toFixed(1)} suffix="/100" valueStyle={{ color: '#722ed1' }} /></Col>
                <Col span={6}><Statistic title="波动率调权" value={selectedDetail.vol_factor?.toFixed(3)} valueStyle={{ color: '#1677ff' }} /></Col>
                <Col span={6}><Statistic title="市场状态" value={MARKET_STATES.find(s => s.value === selectedDetail.market_state)?.label || selectedDetail.market_state} valueStyle={{ color: '#fa8c16' }} /></Col>
                <Col span={6}>
                  <Statistic
                    title="全市场排名"
                    value={selectedDetail.rank_in_universe ? `${selectedDetail.rank_in_universe}/${selectedDetail.total_in_universe}` : '-'}
                    valueStyle={{ color: '#722ed1' }}
                  />
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={12}>
                  <Title level={5}>12因子评分</Title>
                  <div style={{ height: 300 }}>
                    {radarChartOption ? <ReactEChartsCore option={radarChartOption} style={{ height: 300 }} notMerge={true} /> : null}
                  </div>
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
                <Descriptions.Item label="YTM">{selectedDetail.basic_info.ytm != null ? `${selectedDetail.basic_info.ytm}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="剩余年限">{selectedDetail.basic_info.remaining_years || '-'}</Descriptions.Item>
                <Descriptions.Item label="正股价">{selectedDetail.basic_info.stock_price || '-'}</Descriptions.Item>
                <Descriptions.Item label="转股价值">{selectedDetail.basic_info.conversion_value || '-'}</Descriptions.Item>
                <Descriptions.Item label="ROE">{selectedDetail.basic_info.roe != null ? `${selectedDetail.basic_info.roe}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="毛利率">{selectedDetail.basic_info.gpm === -1 ? '银行(无毛利率)' : selectedDetail.basic_info.gpm != null ? `${selectedDetail.basic_info.gpm}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="CAGR">{selectedDetail.basic_info.cagr != null ? `${selectedDetail.basic_info.cagr}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="负债率">{selectedDetail.basic_info.debt_ratio != null ? `${selectedDetail.basic_info.debt_ratio}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="PE">{selectedDetail.basic_info.pe ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="PB">{selectedDetail.basic_info.pb ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="IV">{selectedDetail.basic_info.iv != null ? `${selectedDetail.basic_info.iv}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="流动比">{selectedDetail.basic_info.current_ratio ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="质押率">{selectedDetail.basic_info.pledge_ratio != null ? `${selectedDetail.basic_info.pledge_ratio}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="换手率">{selectedDetail.basic_info.turnover_rate != null ? `${selectedDetail.basic_info.turnover_rate}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="5日动量">{selectedDetail.basic_info.momentum_5d != null ? `${selectedDetail.basic_info.momentum_5d}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="20日动量">{selectedDetail.basic_info.momentum_20d != null ? `${selectedDetail.basic_info.momentum_20d}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="60日动量">{selectedDetail.basic_info.momentum_60d != null ? `${selectedDetail.basic_info.momentum_60d}%` : '-'}</Descriptions.Item>
                <Descriptions.Item label="事件">{selectedDetail.basic_info.event_detail || '-'}</Descriptions.Item>
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
