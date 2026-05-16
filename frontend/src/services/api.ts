import type { ConvertibleQuote } from '../types'
import { saveToCache, getFromCache, getCacheExpiryStatus } from '../utils/dataCache'
import { getApiBase } from '../utils/config'
import { recordApiPerformance } from '../utils/performanceMonitor'
import { withRetry } from '../utils/retryStrategy'
import { logApiError } from '../utils/errorLogger'

const BASE = getApiBase() + '/api/v1'

// 重试配置
const RETRY_CONFIG = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
}

// 离线模式检测
function isOfflineMode(): boolean {
  return localStorage.getItem('offline_mode') === 'true'
}

// 获取缓存过期状态
export function getCacheStatus(cacheKey: string): { isExpired: boolean; remainingTime: string; expiredAgo: string } | null {
  const cached = localStorage.getItem(`cache_${cacheKey}`)
  if (!cached) return null

  try {
    const entry = JSON.parse(cached)
    return getCacheExpiryStatus(entry.expiresAt || entry.timestamp + 3600000)
  } catch {
    return null
  }
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

// 统一 API 请求函数 - 只要 httpRequest 存在就使用 IPC 代理
async function requestAPI<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  url: string,
  body?: any
): Promise<T> {
  // 关键修复：只检查 httpRequest 是否存在，不依赖 isElectron()
  // 因为 isElectron 可能因 preload 加载时序问题返回 false
  if (window.electronAPI?.httpRequest) {
    const result = await window.electronAPI.httpRequest(method, url, body)
    if (!result.ok) {
      throw new ApiError(result.status, result.error || `HTTP ${result.status}`)
    }
    return result.data as T
  }

  // Web 环境使用 fetch
  const resp = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    const text = await resp.text()
    try {
      const json = JSON.parse(text)
      throw new ApiError(resp.status, json.detail || text || `HTTP ${resp.status}`)
    } catch (e) {
      if (e instanceof ApiError) throw e
      throw new ApiError(resp.status, text || `HTTP ${resp.status}`)
    }
  }
  return resp.json()
}

// 快捷方法
function postJSON<T>(url: string, body: any): Promise<T> {
  return requestAPI<T>('POST', url, body)
}

function putJSON<T>(url: string, body: any): Promise<T> {
  return requestAPI<T>('PUT', url, body)
}

function deleteJSON<T>(url: string): Promise<T> {
  return requestAPI<T>('DELETE', url)
}

async function fetchJSON<T>(url: string, cacheKey?: string, cacheTtl: number = 60 * 60 * 1000): Promise<T> {
  const apiName = cacheKey || url.split('/').pop() || 'unknown'

  // 离线模式：使用缓存
  if (isOfflineMode() && cacheKey) {
    const startTime = Date.now()
    const cached = await getFromCache<T>(cacheKey)
    if (cached) {
      console.log(`[API] Offline mode: using cached data for ${cacheKey}`)
      recordApiPerformance(`cached_${apiName}`, Date.now() - startTime)
      return cached
    }
  }

  const startTime = Date.now()
  try {
    // 使用重试策略
    return await withRetry(async () => {
      const data = await requestAPI<T>('GET', url)
      const duration = Date.now() - startTime
      recordApiPerformance(apiName, duration)

      // 缓存数据
      if (cacheKey) {
        saveToCache(cacheKey, data, cacheTtl)
        try {
          localStorage.setItem(`cache_${cacheKey}`, JSON.stringify({ data, timestamp: Date.now(), expiresAt: Date.now() + cacheTtl }))
          localStorage.setItem('cache_time', new Date().toLocaleString('zh-CN'))
        } catch { /* ignore cache errors */ }
      }

      return data
    }, RETRY_CONFIG)
  } catch (error) {
    const duration = Date.now() - startTime
    recordApiPerformance(`${apiName}_error`, duration)

    // 记录 API 错误
    logApiError(apiName, error as Error)

    // 网络错误时尝试使用缓存
    if (cacheKey) {
      const cached = await getFromCache<T>(cacheKey)
      if (cached) {
        console.log(`[API] Network error: using cached data for ${cacheKey}`)
        return cached
      }
      // 尝试从 localStorage 读取
      try {
        const backup = localStorage.getItem(`cache_${cacheKey}`)
        if (backup) {
          console.log(`[API] Using localStorage backup for ${cacheKey}`)
          const entry = JSON.parse(backup)
          return (entry.data || entry) as T
        }
      } catch { /* ignore cache errors */ }
    }
    throw error
  }
}

export async function fetchAllQuotes(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  return fetchJSON(`${BASE}/market/quotes`, 'market_quotes', 5 * 60 * 1000) // 5分钟缓存
}

export async function fetchQuote(code: string): Promise<ConvertibleQuote> {
  return fetchJSON(`${BASE}/market/quotes/${code}`)
}

export async function healthCheck(): Promise<{ status: string; app: string; market_running: boolean; db_ok: boolean; ws_auth_token?: string }> {
  return fetchJSON(getApiBase() + '/health')
}

// ── 回测 API ──

export interface BacktestConfig {
  commission_pct: number
  slippage_pct: number
  min_commission: number
  risk_free_rate: number
}

export interface OptimizationParamRange {
  name: string
  min_val: number
  max_val: number
  step: number
}

export interface OptimizationConfig {
  enabled: boolean
  param_ranges: OptimizationParamRange[]
  optimize_metric: string
  max_iterations: number
  top_n: number
}

export interface BacktestRequest {
  strategy: string
  params: Record<string, number>
  start_date: string
  end_date: string
  config?: BacktestConfig
  optimization?: OptimizationConfig
}

export interface BacktestMetrics {
  total_return_pct: number
  annual_return_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  calmar_ratio: number
  win_rate: number
  profit_loss_ratio: number
  total_trades: number
  avg_hold_days: number
}

export interface BacktestResult {
  strategy_name: string
  strategy_params: Record<string, number>
  start_date: string
  end_date: string
  metrics: BacktestMetrics
  equity_curve: { date: string; value: number }[]
  trades: {
    code: string
    name: string
    buy_date: string
    sell_date: string
    buy_price: number
    sell_price: number
    profit_pct: number
    hold_days: number
    reason: string
  }[]
  execution_time_ms: number
}

export interface OptimizationResultItem {
  params: Record<string, number>
  total_return_pct: number
  annual_return_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  calmar_ratio: number
  win_rate: number
  total_trades: number
}

export interface OptimizationResult {
  strategy_name: string
  optimize_metric: string
  total_combinations: number
  best_params: Record<string, number>
  best_metrics: BacktestMetrics | null
  top_results: OptimizationResultItem[]
  execution_time_ms: number
}

export interface StrategyInfo {
  id: string
  name: string
  description: string
  params: { name: string; label: string; type: string; default: number; min_val?: number; max_val?: number }[]
}

export async function fetchStrategies(): Promise<StrategyInfo[]> {
  const resp = await fetchJSON<{ strategies: StrategyInfo[] }>(BASE + '/backtest/strategies')
  return resp.strategies
}

export async function runBacktest(req: BacktestRequest): Promise<{ type: string; result: BacktestResult | OptimizationResult }> {
  return postJSON<{ type: string; result: BacktestResult | OptimizationResult }>(BASE + '/backtest/run', req)
}

export async function runOptimization(req: BacktestRequest): Promise<{ success: boolean; result: OptimizationResult }> {
  return postJSON<{ success: boolean; result: OptimizationResult }>(BASE + '/backtest/optimize', req)
}

// ── 交易 API ──

export interface Account {
  total_asset: number
  cash: number
  frozen: number
  market_value: number
  daily_profit: number
  total_profit: number
  updated_at: string
}

export interface Position {
  code: string
  name: string
  volume: number
  available_volume: number
  cost_price: number
  current_price: number
  market_value: number
  profit_pct: number
  profit_amount: number
}

export interface TradeOrder {
  id: string
  code: string
  name: string
  side: string
  type: string
  price: number
  volume: number
  filled_volume: number
  status: string
  created_at: string
  updated_at: string | null
  reject_reason: string
}

export interface PlaceOrderRequest {
  code: string
  name: string
  side: 'buy' | 'sell'
  price: number
  volume: number
  order_type?: 'limit' | 'market'
}

export interface FundPoint {
  ts: string
  total_asset: number
  cash: number
  market_value: number
  total_profit: number
}

export async function fetchAccount(): Promise<Account> {
  return fetchJSON(`${BASE}/trade/account`)
}

export async function fetchPositions(): Promise<{ positions: Position[] }> {
  return fetchJSON(`${BASE}/trade/positions`)
}

export async function fetchOrders(): Promise<{ orders: TradeOrder[] }> {
  return fetchJSON(`${BASE}/trade/orders`)
}

export async function placeOrder(req: PlaceOrderRequest): Promise<TradeOrder> {
  return postJSON<TradeOrder>(`${BASE}/trade/order`, req)
}

export async function cancelOrder(orderId: string): Promise<{ status: string }> {
  return fetchJSON(`${BASE}/trade/order/${orderId}/cancel`)
}

export async function resetAccount(): Promise<{ status: string }> {
  return postJSON<{ status: string }>(`${BASE}/trade/reset`, {})
}

export async function fetchFundCurve(): Promise<{ points: FundPoint[] }> {
  return fetchJSON(`${BASE}/trade/fund-curve`)
}

// ── 分析工具 API ──

export interface ForcedRedemptionItem {
  code: string
  name: string
  stock_price: number
  conversion_price: number
  ratio: number
  conversion_value: number
  premium_ratio: number
  trigger_days: number | null
  forced_call_days: number
  risk_level: string
  remaining_years: number
}

export interface DualLowItem {
  rank: number
  code: string
  name: string
  price: number
  premium_ratio: number
  dual_low: number
  ytm: number
  volume: number
  remaining_years: number
  stock_price: number
  conversion_value: number
}

export interface PulseItem {
  code: string
  name: string
  pulse_type: string
  change_pct: number
  price: number
  volume: number
  premium_ratio: number
  dual_low: number
  severity: string
  remaining_years?: number
}

export interface RevisionItem {
  code: string
  name: string
  stock_price: number
  conversion_price: number
  price_distance: number
  ratio: number
  premium_ratio: number
  remaining_years: number
  probability: number
  level: string
  distance_score: number
  time_score: number
  premium_score: number
}

export interface StockCorrelationItem {
  code: string
  name: string
  bond_change: number
  stock_change: number
  elasticity: number
  premium_ratio: number
  conversion_value: number
  price: number
  stock_price: number
  dual_low: number
}

export async function fetchForcedRedemption(): Promise<{ total: number; high_risk_count: number; items: ForcedRedemptionItem[] }> {
  return fetchJSON(`${BASE}/analysis/forced-redemption`)
}

export async function fetchDualLowRanking(): Promise<{ total: number; items: DualLowItem[] }> {
  return fetchJSON(`${BASE}/analysis/dual-low-ranking`)
}

export async function fetchPulseScan(): Promise<{ total: number; high_severity_count: number; items: PulseItem[] }> {
  return fetchJSON(`${BASE}/analysis/pulse-scan`)
}

export async function fetchRevisionProbability(): Promise<{ total: number; high_probability_count: number; items: RevisionItem[] }> {
  return fetchJSON(`${BASE}/analysis/revision-probability`)
}

export async function fetchStockCorrelation(): Promise<{ total: number; items: StockCorrelationItem[] }> {
  return fetchJSON(`${BASE}/analysis/stock-correlation`)
}

// ── 信号 API ──

export interface TradeSignal {
  strategy: string
  code: string
  name: string
  action: 'buy' | 'sell'
  price: number
  reason: string
  confidence: number
  ts: string
  executed: boolean
}

export interface SignalResponse {
  signals: TradeSignal[]
  active_strategies: string[]
  total: number
}

export interface StrategyInfoItem {
  id: string
  name: string
  description: string
}

export async function fetchSignals(): Promise<SignalResponse> {
  return fetchJSON(`${BASE}/signals`)
}

export async function fetchAvailableSignalsStrategies(): Promise<{ strategies: StrategyInfoItem[] }> {
  return fetchJSON(`${BASE}/signals/available-strategies`)
}

export async function setActiveStrategies(strategies: string[]): Promise<{ active_strategies: string[] }> {
  return postJSON<{ active_strategies: string[] }>(`${BASE}/signals/strategies`, { strategies })
}

export async function executeSignal(code: string): Promise<{ executed: number; orders: TradeOrder[] }> {
  return postJSON<{ executed: number; orders: TradeOrder[] }>(`${BASE}/signals/${code}/execute`, {})
}

export async function batchExecuteSignals(): Promise<{ executed: number; orders: TradeOrder[]; message?: string }> {
  return postJSON<{ executed: number; orders: TradeOrder[]; message?: string }>(`${BASE}/signals/batch-execute`, {})
}

export interface ExecutedPosition {
  code: string
  name: string
  side: string
  price: number
  volume: number
  ts: string
}

export async function fetchExecutedPositions(limit = 20, offset = 0): Promise<{ positions: ExecutedPosition[]; total: number }> {
  return getJSON<{ positions: ExecutedPosition[]; total: number }>(`${BASE}/signals/executed-positions?limit=${limit}&offset=${offset}`)
}

export interface SignalHistoryItem {
  id: number
  strategy: string
  code: string
  name: string
  action: string
  price: number
  reason: string
  confidence: number
  executed: boolean
  ts: string
}

export interface SignalStats {
  total: number
  executed: number
  strategy_stats: { strategy: string; count: number; executed: number }[]
}

export async function fetchSignalHistory(strategy?: string, code?: string, limit?: number, offset?: number): Promise<{ signals: SignalHistoryItem[]; total: number }> {
  const params = new URLSearchParams()
  if (strategy) params.set('strategy', strategy)
  if (code) params.set('code', code)
  if (limit) params.set('limit', String(limit))
  if (offset) params.set('offset', String(offset))
  const qs = params.toString()
  return fetchJSON(`${BASE}/signals/history${qs ? '?' + qs : ''}`)
}

export async function fetchSignalStats(): Promise<SignalStats> {
  return fetchJSON(`${BASE}/signals/stats`)
}

export async function setAutoExecuteConfig(minConfidence: number): Promise<{ auto_execute_min_confidence: number }> {
  return postJSON<{ auto_execute_min_confidence: number }>(`${BASE}/signals/auto-execute`, { min_confidence: minConfidence })
}

export interface StrategyVerifyResult {
  strategy: string
  summary: {
    total_periods: number
    overfit_periods: number
    overfit_ratio: number
    avg_test_return: number
    std_test_return: number
    avg_test_drawdown: number
    avg_test_sharpe: number
    avg_test_win_rate: number
    best_period: string
    worst_period: string
  }
  yearly: Record<string, {
    annual_return: number
    max_drawdown: number
    sharpe_ratio: number
    periods: number
  }>
}

export async function verifyStrategy(strategy: string, startDate?: string, endDate?: string): Promise<StrategyVerifyResult> {
  return postJSON<StrategyVerifyResult>(`${BASE}/signals/verify-strategy`, { strategy, start_date: startDate || '', end_date: endDate || '' })
}

export async function cleanupSignalHistory(keepDays: number = 30): Promise<{ status: string; keep_days: number }> {
  return deleteJSON<{ status: string; keep_days: number }>(`${BASE}/signals/cleanup?keep_days=${keepDays}`)
}

export async function setStrategyParams(strategy: string, params: Record<string, unknown>): Promise<{ strategy: string; params: Record<string, unknown> }> {
  return putJSON<{ strategy: string; params: Record<string, unknown> }>(`${BASE}/signals/strategy-params`, { strategy, params })
}

export async function invalidateSignalCache(strategy?: string): Promise<{ status: string; invalidated: string }> {
  return postJSON<{ status: string; invalidated: string }>(`${BASE}/signals/invalidate-cache`, strategy ? { strategy } : {})
}

export function getSignalExportCsvUrl(strategy?: string, code?: string, limit?: number): string {
  const params = new URLSearchParams()
  if (strategy) params.set('strategy', strategy)
  if (code) params.set('code', code)
  if (limit) params.set('limit', String(limit))
  const qs = params.toString()
  return `${BASE}/signals/export-csv${qs ? '?' + qs : ''}`
}

export interface DedupConfig {
  window_seconds: number
  price_threshold: number
}

export async function fetchDedupConfig(): Promise<DedupConfig> {
  return fetchJSON(`${BASE}/signals/dedup-config`)
}

export async function setDedupConfig(config: Partial<DedupConfig>): Promise<DedupConfig> {
  return putJSON<DedupConfig>(`${BASE}/signals/dedup-config`, config)
}

export interface DedupPreset {
  window_seconds: number
  price_threshold: number
  reason: string
}

export async function fetchDedupPresets(): Promise<Record<string, DedupPreset>> {
  const data = await fetchJSON<{ presets: Record<string, DedupPreset> }>(`${BASE}/signals/dedup-presets`)
  return data.presets
}

// ── 评分排名 API ──

export interface ScoreRankingItem {
  rank: number
  code: string
  name: string
  price: number
  premium_ratio: number
  dual_low: number
  volume: number
  change_pct: number
  ytm: number | null
  remaining_years: number | null
  conversion_value: number | null
  stock_price: number | null
  score: number
  score_dual_low: number
  score_premium: number
  score_momentum: number
  score_volume: number
  score_price: number
}

export interface ScoreRankingParams {
  max_premium?: number
  min_price?: number
  top_n?: number
  weight_dual_low?: number
  weight_premium?: number
  weight_momentum?: number
  weight_volume?: number
  weight_price?: number
}

export interface ScoreRankingResponse {
  total: number
  returned: number
  params: {
    max_premium: number
    min_price: number
    weights: {
      dual_low: number
      premium: number
      momentum: number
      volume: number
      price: number
    }
  }
  items: ScoreRankingItem[]
}

export async function fetchScoreRanking(params: ScoreRankingParams = {}): Promise<ScoreRankingResponse> {
  const searchParams = new URLSearchParams()
  if (params.top_n) searchParams.set('top_n', String(params.top_n))
  if (params.max_premium) searchParams.set('max_premium', String(params.max_premium))
  if (params.min_price) searchParams.set('min_price', String(params.min_price))
  if (params.weight_dual_low) searchParams.set('weight_dual_low', String(params.weight_dual_low))
  if (params.weight_premium) searchParams.set('weight_premium', String(params.weight_premium))
  if (params.weight_momentum) searchParams.set('weight_momentum', String(params.weight_momentum))
  if (params.weight_volume) searchParams.set('weight_volume', String(params.weight_volume))
  if (params.weight_price) searchParams.set('weight_price', String(params.weight_price))

  const qs = searchParams.toString()
  return fetchJSON(`${BASE}/analysis/score-ranking${qs ? '?' + qs : ''}`, 'score_ranking', 5 * 60 * 1000)
}

export async function fetchFullScoreRanking(): Promise<{ total: number; items: ScoreRankingItem[] }> {
  return fetchJSON(`${BASE}/analysis/score-ranking/full`, 'full_score_ranking', 5 * 60 * 1000)
}

// ── 评分历史 API ──

export interface ScoreHistoryItem {
  code: string
  name: string
  score: number
  score_dual_low: number
  score_premium: number
  score_momentum: number
  score_volume: number
  score_price: number
  price: number
  premium_ratio: number
  dual_low: number
  volume: number
  snapshot_date: string
}

export async function fetchScoreHistory(code: string, days: number = 30): Promise<{ code: string; days: number; items: ScoreHistoryItem[] }> {
  return fetchJSON(`${BASE}/analysis/score-ranking/history/${code}?days=${days}`, `score_history_${code}`, 5 * 60 * 1000)
}

export async function fetchScoreHistoryBatch(codes: string[], days: number = 30): Promise<{ codes: string[]; days: number; data: Record<string, ScoreHistoryItem[]> }> {
  return fetchJSON(`${BASE}/analysis/score-ranking/history-batch?codes=${codes.join(',')}&days=${days}`, 'score_history_batch', 5 * 60 * 1000)
}

export async function fetchScoreDates(limit: number = 30): Promise<{ dates: string[] }> {
  return fetchJSON(`${BASE}/analysis/score-ranking/dates?limit=${limit}`, 'score_dates', 60 * 60 * 1000)
}

export async function fetchDailyScoreRanking(date: string, topN: number = 60): Promise<{ date: string; top_n: number; items: ScoreHistoryItem[] }> {
  return fetchJSON(`${BASE}/analysis/score-ranking/daily/${date}?top_n=${topN}`, `daily_score_${date}`, 60 * 60 * 1000)
}

export async function saveScoreSnapshot(): Promise<{ status: string; saved: number }> {
  return postJSON<{ status: string; saved: number }>(`${BASE}/analysis/score-ranking/save-snapshot`, {})
}

// ── 评分预警 API ──

export interface ScoreAlert {
  id: number
  code: string
  name: string
  alert_type: 'score' | 'price' | 'dual_low' | 'premium'
  threshold: number
  direction: 'above' | 'below'
  enabled: boolean
  created_at: string
  triggered_at: string | null
}

export interface ScoreAlertRequest {
  code: string
  name?: string
  alert_type: 'score' | 'price' | 'dual_low' | 'premium'
  threshold: number
  direction: 'above' | 'below'
  enabled?: boolean
}

export async function addScoreAlert(alert: ScoreAlertRequest): Promise<{ status: string; id: number }> {
  return postJSON<{ status: string; id: number }>(`${BASE}/analysis/score-alerts`, alert)
}

export async function fetchScoreAlerts(enabledOnly: boolean = false): Promise<{ alerts: ScoreAlert[] }> {
  return fetchJSON(`${BASE}/analysis/score-alerts?enabled_only=${enabledOnly}`, 'score_alerts', 60 * 1000)
}

export async function removeScoreAlert(alertId: number): Promise<{ status: string }> {
  return deleteJSON<{ status: string }>(`${BASE}/analysis/score-alerts/${alertId}`)
}

export async function checkScoreAlerts(): Promise<{ triggered: Array<{ alert: ScoreAlert; current_value: number; triggered_at: string }>; total_alerts: number }> {
  return postJSON<{ triggered: Array<{ alert: ScoreAlert; current_value: number; triggered_at: string }>; total_alerts: number }>(`${BASE}/analysis/score-alerts/check`, {})
}

// ── 评分回测 API ──

export interface ScoreBacktestResult {
  date: string
  end_date: string
  top_n: number
  avg_return_pct: number
  win_rate: number
  max_return: number
  min_return: number
}

export interface ScoreBacktestAccuracy {
  period: { start: string; end: string; hold_days: number }
  top_n: number
  summary: { total_periods: number; avg_return_pct: number; avg_win_rate: number }
  details: ScoreBacktestResult[]
}

export interface TopPerformer {
  rank: number
  code: string
  name: string
  score: number
  start_price: number
  end_price: number
  return_pct: number
  is_winner: boolean
}

export interface TopPerformersResult {
  start_date: string
  end_date: string
  hold_days: number
  summary: {
    total: number
    winners: number
    win_rate: number
    avg_return_pct: number
    max_return: number
    min_return: number
  }
  performers: TopPerformer[]
}

export interface RankingComparison {
  code: string
  name: string
  score1: number | null
  score2: number | null
  score_change: number | null
  rank1: number | null
  rank2: number | null
  rank_change: number | null
  status: 'both' | 'dropped' | 'new'
}

export async function fetchScoreBacktestAccuracy(
  startDate: string,
  endDate: string,
  topN: number = 20,
  holdDays: number = 5
): Promise<ScoreBacktestAccuracy> {
  return fetchJSON(
    `${BASE}/analysis/score-backtest/accuracy?start_date=${startDate}&end_date=${endDate}&top_n=${topN}&hold_days=${holdDays}`,
    'score_backtest_accuracy',
    5 * 60 * 1000
  )
}

export async function fetchTopPerformers(
  snapshotDate: string,
  topN: number = 20,
  holdDays: number = 5
): Promise<TopPerformersResult> {
  return fetchJSON(
    `${BASE}/analysis/score-backtest/top-performers?snapshot_date=${snapshotDate}&top_n=${topN}&hold_days=${holdDays}`,
    `top_performers_${snapshotDate}`,
    5 * 60 * 1000
  )
}

export async function fetchRankingComparison(
  date1: string,
  date2: string,
  topN: number = 30
): Promise<{ date1: string; date2: string; top_n: number; comparison: RankingComparison[] }> {
  return fetchJSON(
    `${BASE}/analysis/score-backtest/ranking-comparison?date1=${date1}&date2=${date2}&top_n=${topN}`,
    `ranking_comparison_${date1}_${date2}`,
    5 * 60 * 1000
  )
}

// 回测历史
export interface BacktestHistoryItem {
  id: number
  run_ts: string
  start_date: string
  end_date: string
  top_n: number
  hold_days: number
  avg_return_pct: number
  win_rate: number
  total_periods: number
  params_json: string
}

export interface BacktestHistoryDetail {
  backtest_id: number
  date: string
  end_date: string
  top_n: number
  avg_return_pct: number
  win_rate: number
  max_return: number
  min_return: number
  max_drawdown: number
}

export async function fetchBacktestHistory(limit: number = 20, offset: number = 0): Promise<{ results: BacktestHistoryItem[]; total: number }> {
  return fetchJSON(`${BASE}/analysis/backtest-history?limit=${limit}&offset=${offset}`, `backtest_history_${offset}`, 60 * 1000)
}

export async function fetchBacktestDetail(backtestId: number): Promise<{ summary: BacktestHistoryItem; details: BacktestHistoryDetail[] }> {
  return fetchJSON(`${BASE}/analysis/backtest-history/${backtestId}`, `backtest_detail_${backtestId}`, 5 * 60 * 1000)
}

export async function deleteBacktestResult(backtestId: number): Promise<{ deleted: boolean; backtest_id: number }> {
  return deleteJSON<{ deleted: boolean; backtest_id: number }>(`${BASE}/analysis/backtest-history/${backtestId}`)
}

export async function cleanupBacktestHistory(keepDays: number = 90): Promise<{ deleted_count: number; keep_days: number }> {
  return postJSON<{ deleted_count: number; keep_days: number }>(`${BASE}/analysis/backtest-history/cleanup?keep_days=${keepDays}`, {})
}


// ═══════════════════════════════════════════════════════════════════════════
// 松岗七维打分 API (V3.0)
// ═══════════════════════════════════════════════════════════════════════════

export interface SonggangScoreItem {
  rank: number
  code: string
  name: string
  price: number
  premium_ratio: number
  dual_low: number
  volume: number
  change_pct: number
  ytm: number | null
  remaining_years: number | null
  total_score: number
  stock_score: number
  bond_score: number
  score_details: Record<string, number>
  bond_details: Record<string, number>
}

export interface SonggangVetoedItem {
  code: string
  name: string
  reasons: string[]
  credit_score: number
}

export interface BufferStatusItem {
  code: string
  name: string
  rank: number
  score: number
  in_buffer: boolean
  days_in_buffer: number
  days_above_60: number
  days_below_60: number
}

export interface SonggangRankingResponse {
  total: number
  returned: number
  market_env: string
  aum_level: string
  params: {
    top_n: number
    buffer_size: number
    buffer_days: number
  }
  items: SonggangScoreItem[]
  vetoed: SonggangVetoedItem[]
  vetoed_count: number
  buffer_status: BufferStatusItem[]
  cached: boolean
}

export interface SonggangSingleScore {
  code: string
  name: string
  price: number
  premium_ratio: number
  dual_low: number
  volume: number
  ytm: number
  remaining_years: number
  veto_check: {
    passed: boolean
    reasons: string[]
    credit_score: number
  }
  total_score: number
  stock_score: number
  bond_score: number
  stock_details: Record<string, number>
  bond_details: Record<string, number>
  weights: {
    stock_weights: Record<string, number>
    bond_weights: Record<string, number>
  }
}

export interface SonggangVetoCheck {
  code: string
  name: string
  passed: boolean
  reasons: string[]
  credit_score: number
  checks: {
    premium_ratio: { value: number; threshold: number; passed: boolean }
    remaining_months: { value: number; threshold: number; passed: boolean }
    forced_call: { value: number; passed: boolean }
  }
}

export async function fetchSonggangRanking(
  topN: number = 60,
  aumLevel: 'small' | 'medium' | 'large' = 'small',
  marketEnv: 'bull' | 'bear' | 'neutral' = 'neutral'
): Promise<SonggangRankingResponse> {
  return fetchJSON(
    `${BASE}/analysis/songgang-ranking?top_n=${topN}&aum_level=${aumLevel}&market_env=${marketEnv}`,
    `songgang_ranking_${topN}_${aumLevel}_${marketEnv}`,
    5 * 60 * 1000
  )
}

export async function fetchSonggangSingleScore(
  code: string,
  aumLevel: 'small' | 'medium' | 'large' = 'small'
): Promise<SonggangSingleScore> {
  return fetchJSON(
    `${BASE}/analysis/songgang-ranking/${code}?aum_level=${aumLevel}`,
    `songgang_single_${code}`,
    5 * 60 * 1000
  )
}

export async function fetchSonggangVetoCheck(code: string): Promise<SonggangVetoCheck> {
  return fetchJSON(
    `${BASE}/analysis/songgang-ranking/veto/${code}`,
    `songgang_veto_${code}`,
    5 * 60 * 1000
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// 组合预警 & 预警历史 API
// ═══════════════════════════════════════════════════════════════════════════

export interface ComboCondition {
  field: 'score' | 'price' | 'dual_low' | 'premium' | 'volume'
  operator: 'gt' | 'lt' | 'gte' | 'lte' | 'eq'
  value: number
}

export interface ComboAlert {
  id: number
  name: string
  description: string
  conditions: ComboCondition[]
  logic: 'AND' | 'OR'
  enabled: boolean
  created_at: string
  triggered_at: string | null
}

export interface AlertHistoryItem {
  id: number
  alert_id: number | null
  alert_type: string
  code: string
  name: string
  threshold: number
  current_value: number
  triggered_at: string
  acknowledged: boolean
}

export async function fetchComboAlerts(enabledOnly: boolean = false): Promise<{ alerts: ComboAlert[] }> {
  return fetchJSON(
    `${BASE}/analysis/combo-alerts?enabled_only=${enabledOnly}`,
    'combo_alerts',
    60 * 1000
  )
}

export async function addComboAlert(alert: {
  name: string
  description?: string
  conditions: ComboCondition[]
  logic?: 'AND' | 'OR'
  enabled?: boolean
}): Promise<{ status: string; id: number }> {
  return postJSON<{ status: string; id: number }>(`${BASE}/analysis/combo-alerts`, alert)
}

export async function removeComboAlert(alertId: number): Promise<{ status: string }> {
  return deleteJSON<{ status: string }>(`${BASE}/analysis/combo-alerts/${alertId}`)
}

export async function checkComboAlerts(): Promise<{ triggered: any[]; total_alerts: number }> {
  return postJSON<{ triggered: any[]; total_alerts: number }>(`${BASE}/analysis/combo-alerts/check`, {})
}

export async function fetchAlertHistory(
  days: number = 30,
  code: string = ''
): Promise<{ history: AlertHistoryItem[]; total: number }> {
  const url = `${BASE}/analysis/alert-history?days=${days}${code ? `&code=${code}` : ''}`
  return fetchJSON(url, `alert_history_${days}`, 60 * 1000)
}

export async function acknowledgeAlertHistory(historyId: number): Promise<{ status: string }> {
  return postJSON<{ status: string }>(`${BASE}/analysis/alert-history/${historyId}/acknowledge`, {})
}

export async function cleanupData(keepDays: number = 90): Promise<{ status: string; results: Record<string, number> }> {
  return postJSON<{ status: string; results: Record<string, number> }>(`${BASE}/analysis/cleanup?keep_days=${keepDays}`, {})
}

// ═══════════════════════════════════════════════════════════════════════════
// 缓存管理 API
// ═══════════════════════════════════════════════════════════════════════════

export interface CacheStats {
  total_entries: number
  valid_entries: number
  expired_entries: number
  cache_keys: string[]
}

export async function fetchCacheStats(): Promise<CacheStats> {
  return fetchJSON(`${BASE}/analysis/cache/stats`, 'cache_stats', 10 * 1000)
}

export async function clearCache(): Promise<{ status: string; cleared_entries: number }> {
  return postJSON<{ status: string; cleared_entries: number }>(`${BASE}/analysis/cache/clear`, {})
}


// ═══════════════════════════════════════════════════════════════════════════
// 策略对比 & 风险指标 API
// ═══════════════════════════════════════════════════════════════════════════

export interface StrategyConfig {
  name: string
  weights: Record<string, number>
}

export interface StrategyResult {
  name: string
  weights: Record<string, number>
  total_periods: number
  avg_return_pct: number
  avg_win_rate: number
  cumulative_return: number
  details: Array<{ date: string; avg_return: number; win_rate: number }>
}

export interface RiskMetrics {
  period: {
    start: string
    end: string
    total_periods: number
    total_days: number
  }
  return_metrics: {
    total_return: number
    annualized_return: number
    avg_period_return: number
  }
  risk_metrics: {
    max_drawdown: number
    volatility: number
    annualized_volatility: number
  }
  risk_adjusted_metrics: {
    sharpe_ratio: number
    calmar_ratio: number
  }
  trade_metrics: {
    win_rate: number
    profit_loss_ratio: number
    avg_win: number
    avg_loss: number
  }
  cumulative_returns: number[]
}

export interface ScorePrediction {
  code: string
  current_score: number
  trend: string
  slope: number
  confidence: number
  predictions: Array<{ day: number; predicted_score: number }>
  change_5d: number
  change_10d: number
  volatility: number
  historical_data: Array<{ date: string; score: number }>
}

export interface NotificationChannel {
  id: number
  channel_type: string
  name: string
  config: Record<string, any>
  enabled: boolean
  created_at: string
}

export async function compareStrategies(
  strategies: StrategyConfig[],
  startDate: string,
  endDate: string,
  topN: number = 20,
  holdDays: number = 5
): Promise<{ strategies: StrategyResult[]; period: Record<string, any> }> {
  return postJSON<{ strategies: StrategyResult[]; period: Record<string, any> }>(`${BASE}/analysis/strategy-compare`, {
    strategies,
    start_date: startDate,
    end_date: endDate,
    top_n: topN,
    hold_days: holdDays,
  })
}

export async function fetchRiskMetrics(
  startDate: string,
  endDate: string,
  topN: number = 20,
  holdDays: number = 5
): Promise<RiskMetrics> {
  return fetchJSON(
    `${BASE}/analysis/risk-metrics?start_date=${startDate}&end_date=${endDate}&top_n=${topN}&hold_days=${holdDays}`,
    'risk_metrics',
    5 * 60 * 1000
  )
}

export async function fetchScorePrediction(code: string, days: number = 30): Promise<ScorePrediction> {
  return fetchJSON(
    `${BASE}/analysis/score-prediction/${code}?days=${days}`,
    `score_prediction_${code}`,
    60 * 1000
  )
}

export async function fetchNotificationChannels(): Promise<{ channels: NotificationChannel[] }> {
  return fetchJSON(`${BASE}/analysis/notification-channels`, 'notification_channels', 60 * 1000)
}

export async function addNotificationChannel(channel: {
  channel_type: string
  name: string
  config: Record<string, any>
  enabled?: boolean
}): Promise<{ status: string; id: number }> {
  return postJSON<{ status: string; id: number }>(`${BASE}/analysis/notification-channels`, channel)
}

export async function removeNotificationChannel(channelId: number): Promise<{ status: string }> {
  return deleteJSON<{ status: string }>(`${BASE}/analysis/notification-channels/${channelId}`)
}


// ═══════════════════════════════════════════════════════════════════════════
// 四因子择时信号 API
// ═══════════════════════════════════════════════════════════════════════════

export interface TimingFactor {
  name: string
  score: number
  maxScore: number
  weight: number
  status: 'good' | 'warning' | 'danger'
  description: string
}

export interface TimingSignal {
  totalScore: number
  positionLimit: number
  marketEnv: 'bull' | 'bear' | 'neutral'
  factors: TimingFactor[]
  recommendation: string
  timestamp: string
}

export async function fetchTimingSignal(): Promise<TimingSignal> {
  return fetchJSON(`${BASE}/analysis/timing-signal`, 'timing_signal', 60 * 1000)
}

export interface TimingHistoryItem {
  date: string
  total_score: number
  position_limit: number
  market_env: string
}

export async function fetchTimingHistory(days: number = 30): Promise<{ items: TimingHistoryItem[] }> {
  return fetchJSON(`${BASE}/analysis/timing-signal/history?days=${days}`, 'timing_history', 60 * 60 * 1000)
}

export interface WsStats {
  connections: { market: number; signals: number; total: number }
  messages: {
    market_messages_sent: number
    market_bytes_sent: number
    signal_messages_sent: number
    signal_bytes_sent: number
    market_delta_messages: number
    market_full_messages: number
    market_compressed_messages?: number
    signal_compressed_messages?: number
    disconnect_reasons: Record<string, number>
  }
}

export async function fetchWsStats(): Promise<WsStats> {
  return fetchJSON(`${BASE}/ws/stats`)
}

export interface SignalsHealth {
  engine_available: boolean
  storage_available: boolean
  active_strategies: string[]
  current_signals_count: number
  dedup_config: { window_seconds: number; price_threshold: number }
  cache_entries: number
  auto_execute_threshold: number
  executed_positions_count: number
  ws_connections: { market: number; signals: number; total: number }
  ws_stats_summary: { market_messages: number; signal_messages: number; disconnect_reasons: Record<string, number> }
}

export async function fetchSignalsHealth(): Promise<SignalsHealth> {
  return fetchJSON(`${BASE}/signals/health`)
}
