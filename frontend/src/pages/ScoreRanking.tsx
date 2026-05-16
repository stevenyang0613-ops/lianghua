import { useState, useEffect, useCallback, useMemo } from 'react'
import { Card, Table, Tag, Row, Col, Spin, Empty, message, Typography, Space, Button, Tooltip, Progress, Tabs, Switch, Divider, Popconfirm } from 'antd'
import { TrophyOutlined, ReloadOutlined, DownloadOutlined, SaveOutlined, BellOutlined, DeleteOutlined, LineChartOutlined, HistoryOutlined, SettingOutlined, ExperimentOutlined, AlertOutlined, ClearOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchScoreRanking, fetchFullScoreRanking, fetchScoreHistory, fetchScoreDates, saveScoreSnapshot,
  fetchScoreAlerts, addScoreAlert, removeScoreAlert, checkScoreAlerts,
  fetchScoreBacktestAccuracy, fetchTopPerformers,
  fetchComboAlerts, addComboAlert, removeComboAlert, checkComboAlerts,
  fetchAlertHistory, acknowledgeAlertHistory, cleanupData,
  compareStrategies, fetchRiskMetrics, fetchScorePrediction,
  type ScoreRankingItem, type ScoreRankingParams, type ScoreHistoryItem, type ScoreAlert,
  type ScoreBacktestResult, type TopPerformer,
  type ComboAlert, type ComboCondition, type AlertHistoryItem,
  type StrategyResult, type RiskMetrics, type ScorePrediction
} from '../services/api'
import { scoreAlertNotificationService } from '../utils/scoreAlertNotification'
import ErrorBoundary from '../components/ErrorBoundary'
import {
  ScoreFilterCard, WeightConfigCard, ScoreStatsRow, ScoreDistributionChart,
  AlertManageModal, ComboAlertModal, AlertHistoryModal, FactorConfigModal,
  ScoreHistoryModal, PredictionModal, BacktestPanel, SignalStrategyTab, BacktestHistoryTab,
} from '../components/score-ranking'

const { Title, Text } = Typography

const STORAGE_KEY = 'score_ranking_config'
const WEIGHTS_KEY = 'score_ranking_weights'
const CUSTOM_FACTORS_KEY = 'score_custom_factors'

const scoreColor = (v: number) => {
  if (v >= 0.7) return '#52c41a'
  if (v >= 0.5) return '#1677ff'
  if (v >= 0.3) return '#faad14'
  return '#ff4d4f'
}

function loadConfig() {
  try { const saved = localStorage.getItem(STORAGE_KEY); if (saved) return JSON.parse(saved) } catch { /* ignore */ }
  return { topN: 60, maxPremium: 50, minPrice: 80 }
}

function loadWeights() {
  try { const saved = localStorage.getItem(WEIGHTS_KEY); if (saved) return JSON.parse(saved) } catch { /* ignore */ }
  return { dual_low: 0.4, premium: 0.2, momentum: 0.2, volume: 0.1, price: 0.1 }
}

function loadCustomFactors(): Record<string, { name: string; weights: Record<string, number> }> {
  try { const saved = localStorage.getItem(CUSTOM_FACTORS_KEY); if (saved) return JSON.parse(saved) } catch { /* ignore */ }
  return {}
}

function saveConfig(config: { topN: number; maxPremium: number; minPrice: number }) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(config)) } catch { /* ignore */ }
}

function saveWeights(weights: Record<string, number>) {
  try { localStorage.setItem(WEIGHTS_KEY, JSON.stringify(weights)) } catch { /* ignore */ }
}

function saveCustomFactors(factors: Record<string, { name: string; weights: Record<string, number> }>) {
  try { localStorage.setItem(CUSTOM_FACTORS_KEY, JSON.stringify(factors)) } catch { /* ignore */ }
}

export default function ScoreRanking() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; returned: number; items: ScoreRankingItem[] } | null>(null)
  const [fullData, setFullData] = useState<{ total: number; items: ScoreRankingItem[] } | null>(null)
  const [tab, setTab] = useState('filtered')

  const savedConfig = useMemo(() => loadConfig(), [])
  const savedWeights = useMemo(() => loadWeights(), [])
  const savedCustomFactors = useMemo(() => loadCustomFactors(), [])

  const [topN, setTopN] = useState(savedConfig.topN)
  const [maxPremium, setMaxPremium] = useState(savedConfig.maxPremium)
  const [minPrice, setMinPrice] = useState(savedConfig.minPrice)
  const [weights, setWeights] = useState(savedWeights)
  const [customFactors, setCustomFactors] = useState(savedCustomFactors)
  const [selectedFactor, setSelectedFactor] = useState<string>('default')
  const [factorModalVisible, setFactorModalVisible] = useState(false)
  const [newFactorName, setNewFactorName] = useState('')

  const [historyModalVisible, setHistoryModalVisible] = useState(false)
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [scoreHistory, setScoreHistory] = useState<ScoreHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [_scoreDates, setScoreDates] = useState<string[]>([])
  const [alertModalVisible, setAlertModalVisible] = useState(false)
  const [alerts, setAlerts] = useState<ScoreAlert[]>([])
  const [newAlert, setNewAlert] = useState<{ code: string; name: string; alert_type: 'score' | 'price' | 'dual_low' | 'premium'; threshold: number; direction: 'above' | 'below' }>({
    code: '', name: '', alert_type: 'score', threshold: 0.7, direction: 'above'
  })

  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtestResults, setBacktestResults] = useState<ScoreBacktestResult[] | null>(null)
  const [backtestSummary, setBacktestSummary] = useState<{ total_periods: number; avg_return_pct: number; avg_win_rate: number } | null>(null)
  const [backtestParams, setBacktestParams] = useState({
    startDate: dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
    endDate: dayjs().format('YYYY-MM-DD'),
    topN: 20,
    holdDays: 5,
  })
  const [topPerformers, setTopPerformers] = useState<TopPerformer[] | null>(null)
  const [performersSummary, setPerformersSummary] = useState<{ total: number; winners: number; win_rate: number; avg_return_pct: number } | null>(null)
  const [backtestChartData, setBacktestChartData] = useState<{ dates: string[]; returns: number[]; winRates: number[] } | null>(null)

  const [notificationEnabled, setNotificationEnabled] = useState(() => scoreAlertNotificationService.isEnabled())
  const [notificationSoundEnabled, setNotificationSoundEnabled] = useState(() => scoreAlertNotificationService.isSoundEnabled())

  const [comboAlerts, setComboAlerts] = useState<ComboAlert[]>([])
  const [comboModalVisible, setComboModalVisible] = useState(false)
  const [newComboConditions, setNewComboConditions] = useState<ComboCondition[]>([{ field: 'dual_low', operator: 'lte', value: 130 }])
  const [newComboName, setNewComboName] = useState('')
  const [newComboLogic, setNewComboLogic] = useState<'AND' | 'OR'>('AND')

  const [alertHistoryModalVisible, setAlertHistoryModalVisible] = useState(false)
  const [alertHistory, setAlertHistory] = useState<AlertHistoryItem[]>([])

  const [strategyResults, setStrategyResults] = useState<StrategyResult[] | null>(null)
  const [strategyLoading, setStrategyLoading] = useState(false)
  const [riskMetrics, setRiskMetrics] = useState<RiskMetrics | null>(null)
  const [riskLoading, setRiskLoading] = useState(false)

  const [predictionCode, setPredictionCode] = useState<string>('')
  const [prediction, setPrediction] = useState<ScorePrediction | null>(null)
  const [predictionLoading, setPredictionLoading] = useState(false)
  const [predictionModalVisible, setPredictionModalVisible] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const params: ScoreRankingParams = {
        top_n: topN, max_premium: maxPremium, min_price: minPrice,
        weight_dual_low: weights.dual_low, weight_premium: weights.premium,
        weight_momentum: weights.momentum, weight_volume: weights.volume, weight_price: weights.price,
      }
      const result = await fetchScoreRanking(params)
      setData(result)
    } catch (e: any) {
      message.error('加载评分排名失败: ' + e.message)
    } finally {
      setLoading(false)
    }
  }, [topN, maxPremium, minPrice, weights])

  const loadFullData = useCallback(async () => {
    try { const result = await fetchFullScoreRanking(); setFullData(result) } catch (e) { console.error('加载完整排名失败', e) }
  }, [])

  const loadAlerts = useCallback(async () => {
    try { const result = await fetchScoreAlerts(); setAlerts(result.alerts) } catch (e) { console.error('加载预警失败', e) }
  }, [])

  const loadScoreDates = useCallback(async () => {
    try { const result = await fetchScoreDates(30); setScoreDates(result.dates) } catch (e) { console.error('加载评分日期失败', e) }
  }, [])

  const loadComboAlerts = useCallback(async () => {
    try { const result = await fetchComboAlerts(); setComboAlerts(result.alerts) } catch (e) { console.error('加载组合预警失败', e) }
  }, [])

  const loadAlertHistory = useCallback(async () => {
    try { const result = await fetchAlertHistory(30); setAlertHistory(result.history) } catch (e) { console.error('加载预警历史失败', e) }
  }, [])

  useEffect(() => { loadData(); loadFullData(); loadAlerts(); loadScoreDates(); loadComboAlerts() }, [])

  const handleSaveConfig = useCallback(() => {
    saveConfig({ topN, maxPremium, minPrice }); saveWeights(weights); message.success('配置已保存')
  }, [topN, maxPremium, minPrice, weights])

  const handleWeightChange = useCallback((key: string, value: number) => {
    setWeights((prev: Record<string, number>) => ({ ...prev, [key]: value }))
  }, [])

  const handleSaveCustomFactor = useCallback(() => {
    if (!newFactorName.trim()) { message.warning('请输入配置名称'); return }
    const id = `custom_${Date.now()}`
    setCustomFactors(prev => { const updated = { ...prev, [id]: { name: newFactorName.trim(), weights } }; saveCustomFactors(updated); return updated })
    setNewFactorName(''); setFactorModalVisible(false); message.success('因子配置已保存')
  }, [newFactorName, weights])

  const handleLoadFactor = useCallback((factorId: string) => {
    if (factorId === 'default') setWeights({ dual_low: 0.4, premium: 0.2, momentum: 0.2, volume: 0.1, price: 0.1 })
    else if (customFactors[factorId]) setWeights(customFactors[factorId].weights)
    setSelectedFactor(factorId)
  }, [customFactors])

  const handleDeleteFactor = useCallback((factorId: string) => {
    setCustomFactors(prev => { const updated = { ...prev }; delete updated[factorId]; saveCustomFactors(updated); return updated })
    if (selectedFactor === factorId) setSelectedFactor('default')
  }, [selectedFactor])

  const handleViewHistory = useCallback(async (code: string) => {
    setSelectedCode(code); setHistoryLoading(true); setHistoryModalVisible(true)
    try { const result = await fetchScoreHistory(code, 30); setScoreHistory(result.items.reverse()) }
    catch { message.error('加载历史数据失败') }
    finally { setHistoryLoading(false) }
  }, [])

  const handleAddAlert = useCallback(async () => {
    if (!newAlert.code) { message.warning('请输入转债代码'); return }
    try { await addScoreAlert(newAlert); message.success('预警已添加'); loadAlerts(); setNewAlert({ code: '', name: '', alert_type: 'score', threshold: 0.7, direction: 'above' }) }
    catch { message.error('添加预警失败') }
  }, [newAlert, loadAlerts])

  const handleDeleteAlert = useCallback(async (alertId: number) => {
    try { await removeScoreAlert(alertId); message.success('预警已删除'); loadAlerts() }
    catch { message.error('删除预警失败') }
  }, [loadAlerts])

  const handleCheckAlerts = useCallback(async () => {
    try {
      const result = await checkScoreAlerts()
      if (result.triggered.length > 0) { await scoreAlertNotificationService.notify(result.triggered.map(t => ({ code: t.alert.code, name: t.alert.name, alert_type: t.alert.alert_type, direction: t.alert.direction, threshold: t.alert.threshold, current_value: t.current_value, triggered_at: t.triggered_at }))); message.warning(`${result.triggered.length} 个预警已触发！`) }
      else message.success('暂无触发预警')
    } catch { message.error('检查预警失败') }
  }, [])

  const runBacktest = useCallback(async () => {
    setBacktestLoading(true)
    try {
      const result = await fetchScoreBacktestAccuracy(backtestParams.startDate, backtestParams.endDate, backtestParams.topN, backtestParams.holdDays)
      setBacktestResults(result.details); setBacktestSummary(result.summary)
      if (result.details && result.details.length > 0) setBacktestChartData({ dates: result.details.map(d => d.date), returns: result.details.map(d => d.avg_return_pct), winRates: result.details.map(d => d.win_rate) })
      message.success('回测完成')
    } catch (e: any) { message.error('回测失败: ' + e.message) }
    finally { setBacktestLoading(false) }
  }, [backtestParams])

  const loadTopPerformers = useCallback(async () => {
    try { const result = await fetchTopPerformers(backtestParams.endDate, backtestParams.topN, backtestParams.holdDays); setTopPerformers(result.performers); setPerformersSummary(result.summary) }
    catch { message.error('加载表现最佳标的失败') }
  }, [backtestParams])

  const runStrategyCompare = useCallback(async () => {
    setStrategyLoading(true)
    try {
      const strategies = [
        { name: '双低优先', weights: { dual_low: 0.6, premium: 0.2, momentum: 0.1, volume: 0.05, price: 0.05 } },
        { name: '平衡策略', weights: { dual_low: 0.4, premium: 0.2, momentum: 0.2, volume: 0.1, price: 0.1 } },
        { name: '动量优先', weights: { dual_low: 0.2, premium: 0.2, momentum: 0.4, volume: 0.1, price: 0.1 } },
        { name: '溢价优先', weights: { dual_low: 0.2, premium: 0.5, momentum: 0.1, volume: 0.1, price: 0.1 } },
        { name: '当前配置', weights },
      ]
      const result = await compareStrategies(strategies, backtestParams.startDate, backtestParams.endDate, backtestParams.topN, backtestParams.holdDays)
      setStrategyResults(result.strategies); message.success('策略对比完成')
    } catch (e: any) { message.error('策略对比失败: ' + e.message) }
    finally { setStrategyLoading(false) }
  }, [weights, backtestParams])

  const runRiskAnalysis = useCallback(async () => {
    setRiskLoading(true)
    try { const result = await fetchRiskMetrics(backtestParams.startDate, backtestParams.endDate, backtestParams.topN, backtestParams.holdDays); setRiskMetrics(result); message.success('风险指标分析完成') }
    catch (e: any) { message.error('风险分析失败: ' + e.message) }
    finally { setRiskLoading(false) }
  }, [backtestParams])

  const runPrediction = useCallback(async (code: string) => {
    setPredictionLoading(true)
    try { const result = await fetchScorePrediction(code, 30); setPrediction(result); setPredictionCode(code); setPredictionModalVisible(true) }
    catch (e: any) { message.error('预测失败: ' + e.message) }
    finally { setPredictionLoading(false) }
  }, [])

  const handleSaveSnapshot = useCallback(async () => {
    try { const result = await saveScoreSnapshot(); message.success(`已保存 ${result.saved} 条评分记录`); loadScoreDates() }
    catch { message.error('保存快照失败') }
  }, [loadScoreDates])

  const handleAddComboAlert = useCallback(async () => {
    if (!newComboName.trim()) { message.warning('请输入预警名称'); return }
    if (newComboConditions.length === 0) { message.warning('请添加至少一个条件'); return }
    try {
      await addComboAlert({ name: newComboName, conditions: newComboConditions, logic: newComboLogic })
      message.success('组合预警已添加'); setNewComboName(''); setNewComboConditions([{ field: 'dual_low', operator: 'lte', value: 130 }]); setComboModalVisible(false); loadComboAlerts()
    } catch { message.error('添加组合预警失败') }
  }, [newComboName, newComboConditions, newComboLogic, loadComboAlerts])

  const handleDeleteComboAlert = useCallback(async (alertId: number) => {
    try { await removeComboAlert(alertId); message.success('组合预警已删除'); loadComboAlerts() }
    catch { message.error('删除组合预警失败') }
  }, [loadComboAlerts])

  const handleCheckComboAlerts = useCallback(async () => {
    try {
      const result = await checkComboAlerts()
      if (result.triggered.length > 0) message.warning(`${result.triggered.length} 个组合预警已触发！`)
      else message.success('暂无触发的组合预警')
    } catch { message.error('检查组合预警失败') }
  }, [])

  const handleAcknowledgeAlert = useCallback(async (historyId: number) => {
    try { await acknowledgeAlertHistory(historyId); message.success('已确认'); loadAlertHistory() }
    catch { message.error('确认失败') }
  }, [loadAlertHistory])

  const handleCleanup = useCallback(async () => {
    try { const result = await cleanupData(90); const total = Object.values(result.results).reduce((a, b) => a + b, 0); message.success(`清理完成，共删除 ${total} 条记录`) }
    catch { message.error('清理失败') }
  }, [])

  const handleNotificationChange = useCallback((enabled: boolean) => {
    setNotificationEnabled(enabled); scoreAlertNotificationService.setEnabled(enabled); message.success(enabled ? '已启用预警通知' : '已禁用预警通知')
  }, [])

  const handleSoundChange = useCallback((enabled: boolean) => {
    setNotificationSoundEnabled(enabled); scoreAlertNotificationService.setSoundEnabled(enabled)
  }, [])

  const columns = useMemo(() => [
    { title: '排名', dataIndex: 'rank', width: 60, render: (v: number) => <Text strong style={{ color: v <= 10 ? '#faad14' : v <= 30 ? '#1677ff' : undefined }}>#{v}</Text> },
    { title: '代码', dataIndex: 'code', width: 90, render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name', width: 120, ellipsis: true },
    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => v?.toFixed(2) },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 80, render: (v: number) => <Tag color={v < 20 ? 'green' : v < 40 ? 'blue' : 'orange'}>{v.toFixed(1)}%</Tag> },
    { title: '双低值', dataIndex: 'dual_low', width: 80, render: (v: number) => <Tag color={v < 130 ? 'green' : v < 150 ? 'blue' : 'orange'}>{v.toFixed(1)}</Tag> },
    { title: '涨跌幅', dataIndex: 'change_pct', width: 90, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}%</span> },
    {
      title: '综合评分', dataIndex: 'score', width: 140, sorter: (a: ScoreRankingItem, b: ScoreRankingItem) => a.score - b.score,
      render: (v: number) => (
        <Space><Progress percent={Math.round(v * 100)} size="small" style={{ width: 60 }} strokeColor={scoreColor(v)} /><Text strong style={{ color: scoreColor(v) }}>{v.toFixed(3)}</Text></Space>
      ),
    },
    {
      title: '因子得分', key: 'factor_scores', width: 200,
      render: (_: unknown, record: ScoreRankingItem) => (
        <Tooltip title={<div><div>双低因子: {record.score_dual_low.toFixed(3)}</div><div>溢价因子: {record.score_premium.toFixed(3)}</div><div>动量因子: {record.score_momentum.toFixed(3)}</div><div>成交量因子: {record.score_volume.toFixed(3)}</div><div>价格因子: {record.score_price.toFixed(3)}</div></div>}>
          <Space size={2}><Tag color="blue" style={{ fontSize: 10 }}>双低 {record.score_dual_low.toFixed(2)}</Tag><Tag color="green" style={{ fontSize: 10 }}>溢价 {record.score_premium.toFixed(2)}</Tag><Tag color="orange" style={{ fontSize: 10 }}>动量 {record.score_momentum.toFixed(2)}</Tag></Space>
        </Tooltip>
      ),
    },
    { title: '成交量', dataIndex: 'volume', width: 100, render: (v: number) => v?.toLocaleString() },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 80, render: (v: number) => v != null ? `${v.toFixed(1)}年` : '-' },
    { title: '转股价值', dataIndex: 'conversion_value', width: 90, render: (v: number) => v?.toFixed(2) ?? '-' },
    {
      title: '操作', key: 'actions', width: 130, fixed: 'right' as const,
      render: (_: unknown, record: ScoreRankingItem) => (
        <Space>
          <Tooltip title="查看历史"><Button type="link" size="small" icon={<HistoryOutlined />} onClick={() => handleViewHistory(record.code)} /></Tooltip>
          <Tooltip title="添加预警"><Button type="link" size="small" icon={<BellOutlined />} onClick={() => { setNewAlert({ code: record.code, name: record.name, alert_type: 'score', threshold: 0.7, direction: 'above' }); setAlertModalVisible(true) }} /></Tooltip>
          <Tooltip title="趋势预测"><Button type="link" size="small" icon={<LineChartOutlined />} onClick={() => runPrediction(record.code)} loading={predictionLoading && predictionCode === record.code} /></Tooltip>
        </Space>
      ),
    },
  ], [handleViewHistory, runPrediction, predictionLoading, predictionCode])

  const fullColumns = useMemo(() => [
    { title: '排名', dataIndex: 'rank', width: 60, render: (v: number) => <Text strong>#{v}</Text> },
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 120, ellipsis: true },
    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => v?.toFixed(2) },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 80, render: (v: number) => `${v.toFixed(1)}%` },
    { title: '双低值', dataIndex: 'dual_low', width: 80, render: (v: number) => v?.toFixed(1) },
    { title: '涨跌幅', dataIndex: 'change_pct', width: 80, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}%</span> },
    { title: '综合评分', dataIndex: 'score', width: 120, sorter: (a: ScoreRankingItem, b: ScoreRankingItem) => a.score - b.score, render: (v: number) => <Text strong style={{ color: scoreColor(v) }}>{v.toFixed(3)}</Text> },
    { title: '成交量', dataIndex: 'volume', width: 100, render: (v: number) => v?.toLocaleString() },
  ], [])

  const exportCsv = useCallback(() => {
    const items = tab === 'filtered' ? data?.items : fullData?.items
    if (!items || items.length === 0) return
    const headers = ['排名', '代码', '名称', '价格', '溢价率', '双低值', '涨跌幅', '综合评分', '成交量']
    const rows = items.map(item => [item.rank, item.code, item.name, item.price, item.premium_ratio, item.dual_low, item.change_pct, item.score, item.volume])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `score-ranking-${new Date().toISOString().slice(0, 10)}.csv`; a.click()
    URL.revokeObjectURL(url); message.success('导出成功')
  }, [tab, data, fullData])

  if (loading && !data) {
    return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
  }

  return (
    <div style={{ padding: 16 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <TrophyOutlined style={{ marginRight: 8, color: '#faad14' }} />
            多因子评分排名
          </Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<SaveOutlined />} onClick={handleSaveSnapshot}>保存快照</Button>
            <Button icon={<BellOutlined />} onClick={() => setAlertModalVisible(true)}>预警管理 ({alerts.length})</Button>
            <Button icon={<AlertOutlined />} onClick={() => setComboModalVisible(true)}>组合预警 ({comboAlerts.length})</Button>
            <Button icon={<HistoryOutlined />} onClick={() => { setAlertHistoryModalVisible(true); loadAlertHistory(); }}>预警历史</Button>
            <Button icon={<ClearOutlined />} onClick={handleCleanup}>数据清理</Button>
            <Button icon={<SettingOutlined />} onClick={() => setFactorModalVisible(true)}>因子配置</Button>
            <Button icon={<SaveOutlined />} onClick={handleSaveConfig}>保存配置</Button>
            <Button icon={<ReloadOutlined />} onClick={() => tab === 'filtered' ? loadData() : loadFullData()} loading={loading}>刷新</Button>
            <Button icon={<DownloadOutlined />} onClick={exportCsv}>导出CSV</Button>
          </Space>
        </Col>
      </Row>

      <ScoreFilterCard
        topN={topN} maxPremium={maxPremium} minPrice={minPrice} loading={loading}
        onTopNChange={setTopN} onMaxPremiumChange={setMaxPremium} onMinPriceChange={setMinPrice} onApply={loadData}
      />

      <WeightConfigCard
        weights={weights} selectedFactor={selectedFactor} customFactors={customFactors}
        onWeightChange={handleWeightChange} onLoadFactor={handleLoadFactor}
        onResetWeights={() => setWeights({ dual_low: 0.4, premium: 0.2, momentum: 0.2, volume: 0.1, price: 0.1 })}
      />

      {data && <ScoreStatsRow total={data.total} returned={data.returned} items={data.items} />}

      <ScoreDistributionChart items={data?.items || []} />

      <Card>
        <Tabs activeKey={tab} onChange={setTab} items={[
          {
            key: 'filtered', label: `筛选排名 (Top ${topN})`,
            children: loading ? <Spin /> : data && data.items.length > 0 ? (
              <Table dataSource={data.items} columns={columns} rowKey="rank" size="small"
                pagination={{ pageSize: 30, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
                scroll={{ x: 1400, y: 500 }} virtual />
            ) : <Empty description="暂无数据" />,
          },
          {
            key: 'full', label: `完整排名 (共 ${fullData?.total || 0} 只)`,
            children: !fullData ? <Spin /> : fullData.items.length > 0 ? (
              <Table dataSource={fullData.items} columns={fullColumns} rowKey="rank" size="small"
                pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
                scroll={{ x: 900, y: 500 }} virtual />
            ) : <Empty description="暂无数据" />,
          },
          {
            key: 'alerts', label: <span><BellOutlined /> 预警列表 ({alerts.length})</span>,
            children: (
              <div style={{ padding: 16 }}>
                <Space style={{ marginBottom: 16 }}>
                  <Button icon={<BellOutlined />} onClick={handleCheckAlerts}>检查预警</Button>
                  <Divider type="vertical" />
                  <Text>通知：</Text>
                  <Switch checked={notificationEnabled} onChange={handleNotificationChange} checkedChildren="开" unCheckedChildren="关" />
                  <Text>声音：</Text>
                  <Switch checked={notificationSoundEnabled} onChange={handleSoundChange} checkedChildren="开" unCheckedChildren="关" />
                  <Divider type="vertical" />
                  <Tooltip title="在信号策略Tab中管理缓存"><Button icon={<ClearOutlined />} onClick={() => setTab('signals')}>策略管理</Button></Tooltip>
                </Space>
                <Table
                  dataSource={alerts}
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: '代码', dataIndex: 'code', width: 100 },
                    { title: '名称', dataIndex: 'name', width: 120, ellipsis: true },
                    { title: '类型', dataIndex: 'alert_type', width: 80, render: (v: string) => <Tag>{v === 'score' ? '评分' : v === 'price' ? '价格' : v === 'dual_low' ? '双低' : '溢价'}</Tag> },
                    { title: '条件', key: 'cond', width: 120, render: (_: unknown, r: ScoreAlert) => <Space><Tag color={r.direction === 'above' ? 'green' : 'red'}>{r.direction === 'above' ? '高于' : '低于'}</Tag><Text>{r.threshold}</Text></Space> },
                    { title: '状态', dataIndex: 'enabled', width: 80, render: (v: boolean) => <Tag color={v ? 'blue' : 'default'}>{v ? '启用' : '禁用'}</Tag> },
                    { title: '操作', key: 'action', width: 80, render: (_: unknown, r: ScoreAlert) => <Popconfirm title="确定删除此预警？" onConfirm={() => handleDeleteAlert(r.id)}><Button type="link" danger icon={<DeleteOutlined />} /></Popconfirm> },
                  ]}
                />
              </div>
            ),
          },
          {
            key: 'signals', label: <span><ThunderboltOutlined /> 信号策略</span>,
            children: <ErrorBoundary><SignalStrategyTab /></ErrorBoundary>,
          },
          {
            key: 'backtest', label: <span><ExperimentOutlined /> 评分回测</span>,
            children: (
              <ErrorBoundary><BacktestPanel
                backtestParams={backtestParams} backtestLoading={backtestLoading}
                backtestResults={backtestResults} backtestSummary={backtestSummary}
                backtestChartData={backtestChartData} topPerformers={topPerformers}
                performersSummary={performersSummary} strategyResults={strategyResults}
                strategyLoading={strategyLoading} riskMetrics={riskMetrics} riskLoading={riskLoading}
                onParamsChange={setBacktestParams} onRunBacktest={runBacktest}
                onLoadTopPerformers={loadTopPerformers} onRunStrategyCompare={runStrategyCompare}
                onRunRiskAnalysis={runRiskAnalysis}
              /></ErrorBoundary>
            ),
          },
          {
            key: 'history', label: <span><HistoryOutlined /> 回测历史</span>,
            children: <ErrorBoundary><BacktestHistoryTab /></ErrorBoundary>,
          },
        ]} />
      </Card>

      <ScoreHistoryModal
        open={historyModalVisible} selectedCode={selectedCode}
        scoreHistory={scoreHistory} historyLoading={historyLoading}
        onClose={() => setHistoryModalVisible(false)}
      />

      <FactorConfigModal
        open={factorModalVisible} newFactorName={newFactorName} customFactors={customFactors}
        onClose={() => setFactorModalVisible(false)}
        onNewFactorNameChange={setNewFactorName}
        onSaveCustomFactor={handleSaveCustomFactor}
        onLoadFactor={handleLoadFactor} onDeleteFactor={handleDeleteFactor}
      />

      <AlertManageModal
        open={alertModalVisible} alerts={alerts} newAlert={newAlert}
        notificationEnabled={notificationEnabled} notificationSoundEnabled={notificationSoundEnabled}
        onClose={() => setAlertModalVisible(false)}
        onNewAlertChange={setNewAlert} onAddAlert={handleAddAlert}
        onDeleteAlert={handleDeleteAlert} onCheckAlerts={handleCheckAlerts}
        onNotificationChange={handleNotificationChange} onSoundChange={handleSoundChange}
      />

      <ComboAlertModal
        open={comboModalVisible} comboAlerts={comboAlerts}
        newComboName={newComboName} newComboLogic={newComboLogic}
        newComboConditions={newComboConditions}
        onClose={() => setComboModalVisible(false)}
        onComboNameChange={setNewComboName} onComboLogicChange={setNewComboLogic}
        onConditionsChange={setNewComboConditions}
        onAddComboAlert={handleAddComboAlert} onDeleteComboAlert={handleDeleteComboAlert}
        onCheckComboAlerts={handleCheckComboAlerts}
      />

      <AlertHistoryModal
        open={alertHistoryModalVisible} alertHistory={alertHistory}
        onClose={() => setAlertHistoryModalVisible(false)}
        onAcknowledge={handleAcknowledgeAlert}
      />

      <PredictionModal
        open={predictionModalVisible} predictionCode={predictionCode}
        prediction={prediction} predictionLoading={predictionLoading}
        onClose={() => setPredictionModalVisible(false)}
      />
    </div>
  )
}
