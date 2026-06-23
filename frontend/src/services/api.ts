import type { ConvertibleQuote } from '../types'
import { saveToCache, getFromCache, getCacheExpiryStatus, getCacheEntry } from '../utils/dataCache'
import { getApiBase, setWsAuthToken } from '../utils/config'
import { recordApiPerformance } from '../utils/performanceMonitor'
import { withRetry } from '../utils/retryStrategy'
import { logApiError } from '../utils/errorLogger'

const getBase = () => getApiBase() + "/api/v1"

// 重试配置
const RETRY_CONFIG = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
}

// 离线模式检测
function isOfflineMode(): boolean {
  try { return localStorage.getItem('offline_mode') === 'true' } catch { return false }
}

// 获取缓存过期状态（从 IndexedDB 读取）
export async function getCacheStatus(cacheKey: string): Promise<{ isExpired: boolean; remainingTime: string; expiredAgo: string } | null> {
  // getFromCache 在过期时返回 null，所以直接从 IndexedDB 读取原始条目
  try {
    const raw = await getCacheEntry(cacheKey)
    if (!raw) return null
    return getCacheExpiryStatus(raw.expiresAt || raw.timestamp + 3600000)
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

async function refreshAuthToken(): Promise<boolean> {
  try {
    const base = getApiBase()
    const resp = await fetch(`${base}/api/v1/health`, { headers: { 'Content-Type': 'application/json' } })
    if (!resp.ok) return false
    const data = await resp.json()
    const newToken = data?.ws_auth_token
    if (newToken && typeof newToken === 'string') {
      setWsAuthToken(newToken)
      console.log('[API] Auth token refreshed from /health')
      return true
    }
  } catch (e) {
    console.warn('[API] Failed to refresh auth token:', e)
  }
  return false
}

// 统一 API 请求函数 - 只要 httpRequest 存在就使用 IPC 代理
async function requestAPI<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  url: string,
  body?: unknown
): Promise<T> {
  // 关键修复：只检查 httpRequest 是否存在，不依赖 isElectron()
  // 因为 isElectron 可能因 preload 加载时序问题返回 false
  if (window.electronAPI?.httpRequest) {
    const ipcPromise = window.electronAPI.httpRequest(method, url, body)
    let timeoutId: ReturnType<typeof setTimeout> | null = null
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => reject(new Error('IPC timeout')), 30000)
    })
    try {
      const result = await Promise.race([ipcPromise, timeoutPromise])
      if (timeoutId) clearTimeout(timeoutId)
      if (!result.ok) {
        if (result.status === 401) {
          console.warn('[API] IPC proxy got 401, requesting token refresh...')
          try {
            const refreshResult = await window.electronAPI.httpRequest('GET', getApiBase() + '/health')
            if (refreshResult.ok && refreshResult.data?.ws_auth_token) {
              setWsAuthToken(refreshResult.data.ws_auth_token)
              const retryResult = await window.electronAPI.httpRequest(method, url, body)
              if (retryResult.ok) return retryResult.data as T
            }
          } catch { /* retry failed */ }
        }
        throw new ApiError(result.status, result.error || `HTTP ${result.status}`)
      }
      return result.data as T
    } catch (err) {
      if (timeoutId) clearTimeout(timeoutId)
      throw err
    }
  }

  // Web 环境使用 fetch —— 注入 ws_auth_token 作为 Bearer 以通过后端鉴权
  const doFetch = async (token?: string): Promise<Response> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    let wsToken: string | null = null
    try { wsToken = token || localStorage.getItem('ws_auth_token') } catch { /* localStorage unavailable */ }
    if (wsToken) {
      headers['Authorization'] = `Bearer ${wsToken}`
    }
    return fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  let resp = await doFetch()
  if (resp.status === 401) {
    console.warn('[API] Got 401, refreshing auth token...')
    const refreshed = await refreshAuthToken()
    if (refreshed) {
      resp = await doFetch()
    }
  }
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
function postJSON<T>(url: string, body: unknown): Promise<T> {
  return requestAPI<T>('POST', url, body)
}

function putJSON<T>(url: string, body: unknown): Promise<T> {
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
    if (cached && typeof cached === 'object') {
      const c = cached as any
      // 离线模式也不返回错误状态的缓存数据
      if (c.success !== false && !c.error && c.status !== 'error') {
        console.log(`[API] Offline mode: using cached data for ${cacheKey}`)
        recordApiPerformance(`cached_${apiName}`, Date.now() - startTime)
        return cached
      } else {
        console.log(`[API] Offline mode: cached data is error state, skipping ${cacheKey}`)
      }
    }
  }

  const startTime = Date.now()
  try {
    // 使用重试策略
    return await withRetry(async () => {
      const data = await requestAPI<T>('GET', url)
      const duration = Date.now() - startTime
      recordApiPerformance(apiName, duration)

      // 缓存数据（仅使用 IndexedDB，避免 localStorage 5MB 限制）
      // 不缓存包含错误状态的数据，避免错误状态被长期缓存
      if (cacheKey) {
        const isErrorState = (data: any) => {
          if (!data || typeof data !== 'object') return false
          if (data.success === false) return true
          if (data.error) return true
          if (data.status === 'error') return true
          return false
        }
        if (!isErrorState(data) && cacheTtl > 0) {
          saveToCache(cacheKey, data, cacheTtl)
        } else if (isErrorState(data)) {
          console.log(`[API] Error state returned, skipping cache for ${cacheKey}`)
        } else {
          console.log(`[API] TTL=0, skipping cache for ${cacheKey}`)
        }
      }

      return data
    }, RETRY_CONFIG)
  } catch (error) {
    const duration = Date.now() - startTime
    recordApiPerformance(`${apiName}_error`, duration)

    // 记录 API 错误
    logApiError(apiName, error as Error)

    // 网络错误时尝试使用缓存（但跳过错误状态缓存）
    if (cacheKey) {
      const cached = await getFromCache<T>(cacheKey)
      if (cached && typeof cached === 'object') {
        const c = cached as any
        if (c.success !== false && !c.error && c.status !== 'error') {
          console.log(`[API] Network error: using cached data for ${cacheKey}`)
          return cached
        } else {
          console.log(`[API] Network error: cached data is error state, skipping ${cacheKey}`)
        }
      }
    }
    throw error
  }
}

export async function fetchAllQuotes(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  // Try prefetched data from Electron main process first (zero network latency)
  if (window.electronAPI?.getPrefetchedMarketData) {
    try {
      const prefetched = await window.electronAPI.getPrefetchedMarketData()
      if (prefetched?.bonds && Array.isArray(prefetched.bonds) && prefetched.bonds.length > 0) {
        console.log(`[API] Using prefetched market data: ${prefetched.bonds.length} bonds`)
        return prefetched
      }
    } catch { /* fallback to HTTP */ }
  }
  return fetchJSON(`${getBase()}/market/quotes`, 'market_quotes', 5 * 60 * 1000) // 5分钟缓存
}

export async function fetchExchangeableBonds(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  return fetchJSON(`${getBase()}/market/exchangeable`, 'exchangeable_bonds', 5 * 60 * 1000)
}

export async function fetchQuote(code: string): Promise<ConvertibleQuote> {
  return fetchJSON(`${getBase()}/market/quotes/${code}`)
}

export async function healthCheck(): Promise<{
  status: string
  app: string
  market_running: boolean
  db_ok: boolean
  ws_auth_token?: string
  data_sources?: {
    mx: { configured: boolean }
    tavily: { configured: boolean }
    minimax: { configured: boolean }
    deepseek: { configured: boolean }
    github: { configured: boolean }
    akshare_proxy: { enabled: boolean }
  }
}> {
  return fetchJSON(getApiBase() + '/health')
}

// ── 回测 API ──

export interface BacktestConfig {
  commission_pct: number
  slippage_pct: number
  min_commission: number
  risk_free_rate: number
  initial_cash?: number
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
  parallel_workers?: number
}

export interface BacktestRequest {
  strategy: string
  params: Record<string, number | string>
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
  strategy_params: Record<string, number | string>
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
  monthly_returns?: { year: number; month: number; return_pct: number }[]
  benchmark_curve?: { date: string; value: number }[]
  execution_time_ms: number
}

export interface OptimizationResultItem {
  params: Record<string, number | string>
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
  best_params: Record<string, number | string>
  best_metrics: BacktestMetrics | null
  top_results: OptimizationResultItem[]
  execution_time_ms: number
}

export interface StrategyInfo {
  id: string
  name: string
  description: string
  params: { name: string; label: string; type: string; default: number; min_val?: number; max_val?: number; options?: string[]; description?: string }[]
}

export async function fetchStrategies(): Promise<StrategyInfo[]> {
  const resp = await fetchJSON<{ strategies: StrategyInfo[] }>(getBase() + '/backtest/strategies')
  return resp.strategies
}

export async function runBacktest(req: BacktestRequest): Promise<{ type: string; result: BacktestResult | OptimizationResult }> {
  return postJSON<{ type: string; result: BacktestResult | OptimizationResult }>(getBase() + '/backtest/run', req)
}

export async function runOptimization(req: BacktestRequest): Promise<{ success: boolean; data_source?: string; result: OptimizationResult }> {
  return postJSON<{ success: boolean; data_source?: string; result: OptimizationResult }>(getBase() + '/backtest/optimize', req)
}

export interface BacktestProgressEvent {
  phase: string
  pct: number
  msg: string
  type?: string
  data_source?: string
  result?: any
}

export function runBacktestStream(
  req: BacktestRequest,
  onProgress: (evt: BacktestProgressEvent) => void,
  timeoutMs: number = 30 * 60 * 1000,
): Promise<{ type: string; result: BacktestResult | OptimizationResult; data_source?: string }> {
   return new Promise((resolve, reject) => {
      const controller = new AbortController()
      let _settled = false
      let _reader: ReadableStreamDefaultReader<Uint8Array> | null = null
      const _cleanup = () => {
        try { controller.abort() } catch { /* ignore */ }
        if (_reader) {
          try { _reader.cancel() } catch { /* ignore */ }
          _reader = null
        }
      }
      const _settle = (fn: (v: any) => void, val: any) => {
        if (_settled) return
        _settled = true
        _cleanup()
        fn(val)
      }
      let timeoutId = setTimeout(() => {
        _settle(reject, new Error('回测请求超时, 请缩短日期范围或减少参数'))
      }, timeoutMs)
      const resetTimeout = () => {
        if (_settled) return
        clearTimeout(timeoutId)
        timeoutId = setTimeout(() => {
          _settle(reject, new Error('回测请求超时, 请缩短日期范围或减少参数'))
        }, timeoutMs)
      }

     // Use IPC proxy or auth token like other API calls
     const sseHeaders: Record<string, string> = { 'Content-Type': 'application/json' }
     let wsToken: string | null = null
     try { wsToken = localStorage.getItem('ws_auth_token') } catch { /* localStorage unavailable */ }
     if (wsToken) {
       sseHeaders['Authorization'] = `Bearer ${wsToken}`
     }

     const sseUrl = getBase() + '/backtest/run-stream'

     fetch(sseUrl, {
      method: 'POST',
      headers: sseHeaders,
      body: JSON.stringify(req),
      signal: controller.signal,
    }).then(resp => {
      if (!resp.ok || !resp.body) {
        clearTimeout(timeoutId)
        // Try to extract error detail from response body
        resp.text().then(text => {
          let detail = `HTTP ${resp.status}`
          try {
            const json = JSON.parse(text)
            if (json.detail) detail = json.detail
          } catch { /* ignore */ }
          _settle(reject, new Error(detail))
        }).catch(() => _settle(reject, new Error(`HTTP ${resp.status}`)))
        return
      }
      const reader = resp.body.getReader()
      _reader = reader
      const decoder = new TextDecoder()
      let buffer = ''
      let finalResult: { type: string; result: BacktestResult | OptimizationResult; data_source?: string } | null = null

      function pump(): Promise<void> {
        return reader.read().then(({ done, value }) => {
          if (done) {
            clearTimeout(timeoutId)
            if (finalResult) _settle(resolve, finalResult)
            else _settle(reject, new Error('Stream ended without result'))
            return
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          let hasData = false
          for (const line of lines) {
            if (line.startsWith(': ')) {
              hasData = true
              continue
            }
            if (!line.startsWith('data: ')) continue
            hasData = true
            try {
              const evt: BacktestProgressEvent = JSON.parse(line.slice(6))
              if (evt.phase === 'done' && evt.result) {
                finalResult = { type: evt.type || 'backtest', result: evt.result, data_source: evt.data_source }
              }
              if (evt.phase === 'error') {
                clearTimeout(timeoutId)
                _settle(reject, new Error(evt.msg))
                return
              }
              onProgress(evt)
            } catch { /* skip malformed */ }
          }
          if (hasData) {
            resetTimeout()
          }
          return pump()
        })
      }
      pump().catch(e => { clearTimeout(timeoutId); _settle(reject, e) })
    }).catch(e => {
      clearTimeout(timeoutId)
      // Provide more helpful error message for connection failures
      const errMsg = e instanceof TypeError && e.message === 'Failed to fetch'
        ? '无法连接到后端服务，请确认应用已正常启动'
        : (e instanceof Error ? e.message : String(e))
      _settle(reject, new Error(errMsg))
    })
  })
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
  return fetchJSON(`${getBase()}/trade/account`)
}

export async function fetchPositions(): Promise<{ positions: Position[] }> {
  return fetchJSON(`${getBase()}/trade/positions`)
}

export async function fetchOrders(): Promise<{ orders: TradeOrder[] }> {
  return fetchJSON(`${getBase()}/trade/orders`)
}

export async function placeOrder(req: PlaceOrderRequest): Promise<TradeOrder> {
  return postJSON<TradeOrder>(`${getBase()}/trade/order`, req)
}

export async function cancelOrder(orderId: string): Promise<{ status: string }> {
  return postJSON<{ status: string }>(`${getBase()}/trade/orders/${orderId}/cancel`, {})
}

export async function resetAccount(): Promise<{ status: string }> {
  return postJSON<{ status: string }>(`${getBase()}/trade/reset`, {})
}

export async function fetchFundCurve(): Promise<{ points: FundPoint[] }> {
  return fetchJSON(`${getBase()}/trade/fund-curve`)
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
  put_back_pressure: boolean
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
  volume_ratio?: number
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
  correlation: string
  pearson_correlation: number | null
  premium_ratio: number
  conversion_value: number
  price: number
  stock_price: number
  dual_low: number
}

export interface AnalysisQueryOpts {
  min_volume?: number
  sort_by?: string
  sort_order?: string
  start_date?: string
  end_date?: string
}

function _buildParams(opts?: AnalysisQueryOpts): string {
  if (!opts) return ''
  const parts: string[] = []
  if (opts.min_volume && opts.min_volume > 0) parts.push(`min_volume=${opts.min_volume}`)
  if (opts.sort_by) parts.push(`sort_by=${opts.sort_by}`)
  if (opts.sort_order) parts.push(`sort_order=${opts.sort_order}`)
  if (opts.start_date) parts.push(`start_date=${opts.start_date}`)
  if (opts.end_date) parts.push(`end_date=${opts.end_date}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export async function fetchForcedRedemption(opts?: AnalysisQueryOpts): Promise<{ total: number; high_risk_count: number; items: ForcedRedemptionItem[] }> {
  return fetchJSON(`${getBase()}/analysis/forced-redemption${_buildParams(opts)}`, 'analysis_forced_redemption')
}

export async function fetchDualLowRanking(opts?: AnalysisQueryOpts): Promise<{ total: number; items: DualLowItem[] }> {
  return fetchJSON(`${getBase()}/analysis/dual-low-ranking${_buildParams(opts)}`, 'analysis_dual_low_ranking')
}

export async function fetchPulseScan(opts?: AnalysisQueryOpts): Promise<{ total: number; high_severity_count: number; items: PulseItem[] }> {
  return fetchJSON(`${getBase()}/analysis/pulse-scan${_buildParams(opts)}`, 'analysis_pulse_scan')
}

export async function fetchRevisionProbability(opts?: AnalysisQueryOpts): Promise<{ total: number; high_probability_count: number; items: RevisionItem[] }> {
  return fetchJSON(`${getBase()}/analysis/revision-probability${_buildParams(opts)}`, 'analysis_revision_probability')
}

export async function fetchStockCorrelation(opts?: AnalysisQueryOpts): Promise<{ total: number; strong_correlation_count: number; items: StockCorrelationItem[] }> {
  return fetchJSON(`${getBase()}/analysis/stock-correlation${_buildParams(opts)}`, 'analysis_stock_correlation')
}

export function getAnalysisExportUrl(tabKey: string, opts?: AnalysisQueryOpts): string {
  return `${getBase()}/analysis/${tabKey}/export${_buildParams(opts)}`
}

// ── 信号 API ──

export interface TradeSignal {
  id?: string
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
  params?: Array<{ name: string; default: number; max_val?: number; min_val?: number; description?: string }>
}

export async function fetchSignals(): Promise<SignalResponse> {
  return fetchJSON(`${getBase()}/signals`)
}

export async function fetchAvailableSignalsStrategies(): Promise<{ strategies: StrategyInfoItem[] }> {
  return fetchJSON(`${getBase()}/signals/available-strategies`)
}

export async function setActiveStrategies(strategies: string[]): Promise<{ active_strategies: string[] }> {
  return postJSON<{ active_strategies: string[] }>(`${getBase()}/signals/strategies`, { strategies })
}

export async function executeSignal(code: string): Promise<{ executed: number; orders: TradeOrder[] }> {
  return postJSON<{ executed: number; orders: TradeOrder[] }>(`${getBase()}/signals/${code}/execute`, {})
}

export async function batchExecuteSignals(): Promise<{ executed: number; orders: TradeOrder[]; message?: string }> {
  return postJSON<{ executed: number; orders: TradeOrder[]; message?: string }>(`${getBase()}/signals/batch-execute`, {})
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
  return fetchJSON<{ positions: ExecutedPosition[]; total: number }>(`${getBase()}/signals/executed-positions?limit=${limit}&offset=${offset}`)
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
  return fetchJSON(`${getBase()}/signals/history${qs ? '?' + qs : ''}`)
}

export async function fetchSignalStats(): Promise<SignalStats> {
  return fetchJSON(`${getBase()}/signals/stats`)
}

export async function setAutoExecuteConfig(minConfidence: number): Promise<{ auto_execute_min_confidence: number }> {
  return postJSON<{ auto_execute_min_confidence: number }>(`${getBase()}/signals/auto-execute`, { min_confidence: minConfidence })
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
  return postJSON<StrategyVerifyResult>(`${getBase()}/signals/verify-strategy`, { strategy, start_date: startDate || '', end_date: endDate || '' })
}

export async function cleanupSignalHistory(keepDays: number = 30): Promise<{ status: string; keep_days: number }> {
  return postJSON<{ status: string; keep_days: number }>(`${getBase()}/signals/cleanup?keep_days=${keepDays}`, {})
}

export async function setStrategyParams(strategy: string, params: Record<string, unknown>): Promise<{ strategy: string; params: Record<string, unknown> }> {
  return putJSON<{ strategy: string; params: Record<string, unknown> }>(`${getBase()}/signals/strategy-params`, { strategy, params })
}

export async function invalidateSignalCache(strategy?: string): Promise<{ status: string; invalidated: string }> {
  return postJSON<{ status: string; invalidated: string }>(`${getBase()}/signals/invalidate-cache`, strategy ? { strategy } : {})
}

export function getSignalExportCsvUrl(strategy?: string, code?: string, limit?: number): string {
  const params = new URLSearchParams()
  if (strategy) params.set('strategy', strategy)
  if (code) params.set('code', code)
  if (limit) params.set('limit', String(limit))
  const qs = params.toString()
  return `${getBase()}/signals/export-csv${qs ? '?' + qs : ''}`
}

export interface DedupConfig {
  window_seconds: number
  price_threshold: number
}

export async function fetchDedupConfig(): Promise<DedupConfig> {
  return fetchJSON(`${getBase()}/signals/dedup-config`)
}

export async function setDedupConfig(config: Partial<DedupConfig>): Promise<DedupConfig> {
  return putJSON<DedupConfig>(`${getBase()}/signals/dedup-config`, config)
}

export interface DedupPreset {
  window_seconds: number
  price_threshold: number
  reason: string
}

export async function fetchDedupPresets(): Promise<Record<string, DedupPreset>> {
  const data = await fetchJSON<{ presets: Record<string, DedupPreset> }>(`${getBase()}/signals/dedup-presets`)
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
  return fetchJSON(`${getBase()}/analysis/score-ranking${qs ? '?' + qs : ''}`, 'score_ranking', 5 * 60 * 1000)
}

export async function fetchFullScoreRanking(): Promise<{ total: number; items: ScoreRankingItem[] }> {
  return fetchJSON(`${getBase()}/analysis/score-ranking/full`, 'full_score_ranking', 5 * 60 * 1000)
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
  return fetchJSON(`${getBase()}/analysis/score-ranking/history/${code}?days=${days}`, `score_history_${code}`, 5 * 60 * 1000)
}

export async function fetchScoreHistoryBatch(codes: string[], days: number = 30): Promise<{ codes: string[]; days: number; data: Record<string, ScoreHistoryItem[]> }> {
  return fetchJSON(`${getBase()}/analysis/score-ranking/history-batch?codes=${codes.join(',')}&days=${days}`, 'score_history_batch', 5 * 60 * 1000)
}

export async function fetchScoreDates(limit: number = 30): Promise<{ dates: string[] }> {
  return fetchJSON(`${getBase()}/analysis/score-ranking/dates?limit=${limit}`, 'score_dates', 60 * 60 * 1000)
}

export async function fetchDailyScoreRanking(date: string, topN: number = 60): Promise<{ date: string; top_n: number; items: ScoreHistoryItem[] }> {
  return fetchJSON(`${getBase()}/analysis/score-ranking/daily/${date}?top_n=${topN}`, `daily_score_${date}`, 60 * 60 * 1000)
}

export async function saveScoreSnapshot(): Promise<{ status: string; saved: number }> {
  return postJSON<{ status: string; saved: number }>(`${getBase()}/analysis/score-ranking/save-snapshot`, {})
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
  return postJSON<{ status: string; id: number }>(`${getBase()}/analysis/score-alerts`, alert)
}

export async function fetchScoreAlerts(enabledOnly: boolean = false): Promise<{ alerts: ScoreAlert[] }> {
  return fetchJSON(`${getBase()}/analysis/score-alerts?enabled_only=${enabledOnly}`) // 实时告警不缓存
}

export async function removeScoreAlert(alertId: number): Promise<{ status: string }> {
  return deleteJSON<{ status: string }>(`${getBase()}/analysis/score-alerts/${alertId}`)
}

export async function checkScoreAlerts(): Promise<{ triggered: Array<{ alert: ScoreAlert; current_value: number; triggered_at: string }>; total_alerts: number }> {
  return postJSON<{ triggered: Array<{ alert: ScoreAlert; current_value: number; triggered_at: string }>; total_alerts: number }>(`${getBase()}/analysis/score-alerts/check`, {})
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
    `${getBase()}/analysis/score-backtest/accuracy?start_date=${startDate}&end_date=${endDate}&top_n=${topN}&hold_days=${holdDays}`,
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
    `${getBase()}/analysis/score-backtest/top-performers?snapshot_date=${snapshotDate}&top_n=${topN}&hold_days=${holdDays}`,
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
    `${getBase()}/analysis/score-backtest/ranking-comparison?date1=${date1}&date2=${date2}&top_n=${topN}`,
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
  return fetchJSON(`${getBase()}/analysis/backtest-history?limit=${limit}&offset=${offset}`, `backtest_history_${offset}`, 60 * 1000)
}

export async function fetchBacktestDetail(backtestId: number): Promise<{ summary: BacktestHistoryItem; details: BacktestHistoryDetail[] }> {
  return fetchJSON(`${getBase()}/analysis/backtest-history/${backtestId}`, `backtest_detail_${backtestId}`, 5 * 60 * 1000)
}

export async function deleteBacktestResult(backtestId: number): Promise<{ deleted: boolean; backtest_id: number }> {
  return deleteJSON<{ deleted: boolean; backtest_id: number }>(`${getBase()}/analysis/backtest-history/${backtestId}`)
}

export async function cleanupBacktestHistory(keepDays: number = 90): Promise<{ deleted_count: number; keep_days: number }> {
  return postJSON<{ deleted_count: number; keep_days: number }>(`${getBase()}/analysis/backtest-history/cleanup?keep_days=${keepDays}`, {})
}


// ═══════════════════════════════════════════════════════════════════════════
// 西部七维打分 API (V3.0)
// ═══════════════════════════════════════════════════════════════════════════

export interface XibuScoreItem {
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
  change_1d?: number
  change_3d?: number | null
  change_5d?: number | null
  change_10d?: number | null
  change_30d?: number | null
}

export interface XibuVetoedItem {
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

export interface MarketChangeStats {
  /** 全市场可转债总数 */
  total: number
  /** 上涨只数 (change_pct > 0) */
  up: number
  /** 下跌只数 (change_pct < 0) */
  down: number
  /** 持平只数 (change_pct == 0) */
  flat: number
  /** 上涨占比 % */
  up_ratio: number
  /** 下跌占比 % */
  down_ratio: number
  /** 全市场平均涨跌幅 % */
  avg_change: number
  /** 全市场中位数涨跌幅 % */
  median_change: number
}

export interface XibuRankingResponse {
  total: number
  returned: number
  market_env: string
  aum_level: string
  params: {
    top_n: number
    buffer_size: number
    buffer_days: number
  }
  items: XibuScoreItem[]
  vetoed: XibuVetoedItem[]
  vetoed_count: number
  buffer_status: BufferStatusItem[]
  market_stats?: MarketChangeStats
  cached: boolean
}

export interface XibuSingleScore {
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

export interface XibuVetoCheck {
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

export async function fetchXibuRanking(
  topN: number = 60,
  aumLevel: 'small' | 'medium' | 'large' = 'small',
  marketEnv: 'bull' | 'bear' | 'neutral' = 'neutral'
): Promise<XibuRankingResponse> {
  return fetchJSON(
    `${getBase()}/analysis/xibu-ranking?top_n=${topN}&aum_level=${aumLevel}&market_env=${marketEnv}`,
    `xibu_ranking_v2_${topN}_${aumLevel}_${marketEnv}`,
    5 * 60 * 1000
  )
}

export async function fetchXibuSingleScore(
  code: string,
  aumLevel: 'small' | 'medium' | 'large' = 'small'
): Promise<XibuSingleScore> {
  return fetchJSON(
    `${getBase()}/analysis/xibu-ranking/${code}?aum_level=${aumLevel}`,
    `xibu_single_${code}`,
    5 * 60 * 1000
  )
}

export async function fetchXibuVetoCheck(code: string): Promise<XibuVetoCheck> {
  return fetchJSON(
    `${getBase()}/analysis/xibu-ranking/veto/${code}`,
    `xibu_veto_${code}`,
    5 * 60 * 1000
  )
}

export async function saveXibuSnapshot(): Promise<{ status: string; saved: number }> {
  return postJSON<{ status: string; saved: number }>(`${getBase()}/analysis/xibu-ranking/save-snapshot`, {})
}

export interface SevenDimHistoryItem {
  snapshot_date: string
  code: string
  name: string
  total_score: number
  stock_score: number
  bond_score: number
  momentum: number
  sector: number
  technical: number
  chip: number
  volatility: number
  news: number
  fundamental: number
  valuation: number
  clause: number
  liquidity: number
  credit: number
  price: number
  premium_ratio: number
  dual_low: number
}

export async function fetchXibuHistory(code: string, days: number = 30): Promise<{ code: string; days: number; items: SevenDimHistoryItem[] }> {
  return fetchJSON(
    `${getBase()}/analysis/xibu-ranking/history/${code}?days=${days}`,
    `xibu_history_${code}_${days}`,
    60 * 1000
  )
}

/**
 * SSE流式获取七维排名，实时推送计算进度和中间结果
 */
export function streamXibuRanking(
  params: { topN: number; aumLevel: string; marketEnv: string },
  onProgress: (data: { progress: number; computed: number; items: XibuScoreItem[] }) => void,
  onDone: (data: any) => void,
  onError: (err: string) => void,
  timeout = 30000,
): EventSource {
  const url = `${getBase()}/analysis/xibu-ranking/stream?top_n=${params.topN}&aum_level=${params.aumLevel}&market_env=${params.marketEnv}`
  const es = new EventSource(url)
  let settled = false
  let timer = setTimeout(() => {
    if (settled) return
    settled = true
    es.close()
    onError('SSE timeout, falling back to REST')
  }, timeout)
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'progress') {
        clearTimeout(timer)
        timer = setTimeout(() => {
          if (settled) return
          settled = true
          es.close()
          onError('SSE timeout, falling back to REST')
        }, timeout)
        onProgress(data)
      } else if (data.type === 'done') {
        settled = true
        clearTimeout(timer)
        onDone(data)
        es.close()
      } else if (data.type === 'error') {
        settled = true
        clearTimeout(timer)
        onError(data.message || 'Unknown error')
        es.close()
      }
    } catch (parseErr) {
        console.error('[SSE] JSON parse error:', parseErr, 'raw:', e.data?.slice(0, 200))
        // 仅当非 settled 时报错，避免已完成后还触发 onError
        if (!settled) {
          settled = true
          clearTimeout(timer)
          onError(`SSE 数据解析失败: ${parseErr instanceof Error ? parseErr.message : String(parseErr)}`)
          es.close()
        }
      }
  }
  es.onerror = () => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    onError('SSE connection error')
    es.close()
  }
  return es
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
    `${getBase()}/analysis/combo-alerts?enabled_only=${enabledOnly}`,
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
  return postJSON<{ status: string; id: number }>(`${getBase()}/analysis/combo-alerts`, alert)
}

export async function removeComboAlert(alertId: number): Promise<{ status: string }> {
  return deleteJSON<{ status: string }>(`${getBase()}/analysis/combo-alerts/${alertId}`)
}

export async function checkComboAlerts(): Promise<{ triggered: any[]; total_alerts: number }> {
  return postJSON<{ triggered: any[]; total_alerts: number }>(`${getBase()}/analysis/combo-alerts/check`, {})
}

export async function fetchAlertHistory(
  days: number = 30,
  code: string = ''
): Promise<{ history: AlertHistoryItem[]; total: number }> {
  const url = `${getBase()}/analysis/alert-history?days=${days}${code ? `&code=${code}` : ''}`
  return fetchJSON(url, `alert_history_${days}`, 60 * 1000)
}

export async function acknowledgeAlertHistory(historyId: number): Promise<{ status: string }> {
  return postJSON<{ status: string }>(`${getBase()}/analysis/alert-history/${historyId}/acknowledge`, {})
}

export async function cleanupData(keepDays: number = 90): Promise<{ status: string; results: Record<string, number> }> {
  return postJSON<{ status: string; results: Record<string, number> }>(`${getBase()}/analysis/cleanup?keep_days=${keepDays}`, {})
}

// ═══════════════════════════════════════════════════════════════════════════
// 缓存管理 API
// ═══════════════════════════════════════════════════════════════════════════

export interface CacheStats {
  hits: number
  misses: number
  size: number
  ttl: number
  hit_rate: number
}

export async function fetchCacheStats(): Promise<CacheStats> {
  return fetchJSON(`${getBase()}/analysis/cache-stats`) // 状态信息不缓存
}

export async function clearCache(): Promise<{ status: string; cleared_entries: number }> {
  return postJSON<{ status: string; cleared_entries: number }>(`${getBase()}/analysis/cache/clear`, {})
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
  return postJSON<{ strategies: StrategyResult[]; period: Record<string, any> }>(`${getBase()}/analysis/strategy-compare`, {
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
    `${getBase()}/analysis/risk-metrics?start_date=${startDate}&end_date=${endDate}&top_n=${topN}&hold_days=${holdDays}`,
    'risk_metrics',
    5 * 60 * 1000
  )
}

export async function fetchScorePrediction(code: string, days: number = 30): Promise<ScorePrediction> {
  return fetchJSON(
    `${getBase()}/analysis/score-prediction/${code}?days=${days}`,
    `score_prediction_${code}`,
    60 * 1000
  )
}

export async function fetchNotificationChannels(): Promise<{ channels: NotificationChannel[] }> {
  return fetchJSON(`${getBase()}/analysis/notification-channels`) // 配置信息不缓存
}

export async function addNotificationChannel(channel: {
  channel_type: string
  name: string
  config: Record<string, any>
  enabled?: boolean
}): Promise<{ status: string; id: number }> {
  return postJSON<{ status: string; id: number }>(`${getBase()}/analysis/notification-channels`, channel)
}

export async function removeNotificationChannel(channelId: number): Promise<{ status: string }> {
  return deleteJSON<{ status: string }>(`${getBase()}/analysis/notification-channels/${channelId}`)
}


// ═══════════════════════════════════════════════════════════════════════════
// 多因子择时信号 API (V3 Legacy) + 增强择时信号 API (V4)
// ═══════════════════════════════════════════════════════════════════════════

export interface TimingFactor {
  name: string
  score: number | null
  maxScore: number
  weight: number
  status: 'good' | 'warning' | 'danger' | 'missing'
  description: string
  icon?: string
  subFactors?: TimingSubFactor[]
}

export interface TimingSubFactor {
  name: string
  score: number | null
  weight: number
  signal: 'bullish' | 'bearish' | 'neutral' | 'missing'
  description: string
}

export interface TimingSignal {
  totalScore: number | null
  positionLimit: number
  marketEnv: 'bull' | 'bear' | 'neutral' | 'strong_bull' | 'strong_bear' | 'unknown'
  factors: TimingFactor[]
  recommendation: string
  timestamp: string
  // V4 增强字段
  modelVersion?: string
  quality?: string
  confidence?: number
  consensusScore?: number
  riskAlerts?: string[]
  hedgeRecommended?: boolean
  crossValidation?: {
    bullishCount: number
    bearishCount: number
    totalCount: number
  }
  // 集成学习额外字段
  stability?: {
    stable: boolean
    volatility: number
    trend: string
    avg_score: number
    min_score: number
    max_score: number
    samples: number
  }
  riskScore?: number
  factorContributions?: Record<string, number>
  // V4.1: 信号准确率统计
  accuracyStats?: {
    accuracy: number
    total: number
    verified: number
    correct: number
    recentAccuracy: number
  }
}

export async function fetchTimingSignal(): Promise<TimingSignal> {
  return fetchJSON(`${getBase()}/xb-strategy/timing-signal`, 'timing_signal', 60 * 1000)
}

export async function fetchEnhancedTimingSignal(): Promise<TimingSignal> {
  return fetchJSON(`${getBase()}/xb-strategy/timing-signal/enhanced`, 'enhanced_timing_signal', 60 * 1000)
}

export interface TimingHistoryItem {
  date: string
  total_score: number
  position_limit: number
  market_env: string
}

export async function fetchTimingHistory(days: number = 30): Promise<{ items: TimingHistoryItem[] }> {
  return fetchJSON(`${getBase()}/xb-strategy/timing-signal/history?days=${days}`, 'timing_history', 60 * 60 * 1000)
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
  return fetchJSON(`${getBase()}/ws/stats`)
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
  return fetchJSON(`${getBase()}/signals/health`)
}

// ── 璇玑十二因子 API ──

export interface XuanjiFactorScore {
  value: number
  weight: number
}

export interface XuanjiItem {
  rank: number
  code: string
  name: string
  stock_code: string
  price: number
  premium_ratio: number
  dual_low: number
  volume: number
  change_pct: number
  ytm: number | null
  remaining_years: number | null
  hv: number
  industry: string
  rating: string
  pe: number | null
  pb: number | null
  roe: number | null
  gpm: number | null
  cagr: number | null
  debt_ratio: number | null
  current_ratio: number | null
  iv: number | null
  turnover_rate: number | null
  net_capital_flow: number | null
  net_capital_flow_pct: number | null
  buyback_amount: number | null
  mgmt_buy_price: number | null
  outstanding_scale: number | null
  pledge_ratio: number | null
  momentum_5d: number | null
  momentum_10d: number | null
  momentum_20d: number | null
  momentum_60d: number | null
  event_score: number | null
  event_detail: string | null
  score: number
  score_dual_low: number
  score_momentum: number
  score_hv: number
  score_quality: number
  score_valuation: number
  score_ytm: number
  score_event: number
  score_delta: number
  score_remaining_years: number
}

export interface XuanjiRankingResponse {
  total: number
  total_unfiltered?: number
  returned: number
  market_state_requested: string
  market_state_detected: string
  market_state_actual: string
  market_weights: Record<string, number>
  factor_names: Record<string, string>
  params: Record<string, any>
  items: XuanjiItem[]
  cached?: boolean
}

export interface XuanjiGreeks {
  delta: number
  gamma: number
  vega: number
  theta: number
  iv: number
  iv_source: string
}

export interface XuanjiSingleResponse {
  code: string
  name: string
  market_state: string
  market_weights: Record<string, number>
  factor_names: Record<string, string>
  factor_scores: Record<string, XuanjiFactorScore>
  composite_score: number
  vol_factor: number
  rank_in_universe: number
  total_in_universe: number
  basic_info: Record<string, any>
  greeks: XuanjiGreeks
}

export interface XuanjiDeltaCandidate {
  code: string
  name: string
  stock_code: string
  industry: string
  iv: number
  hv: number
  iv_hv_diff: number
  premium_ratio: number
  price: number
  delta: number
  alpha_potential: string | null
  iv_source: string
  hv_source: string
}

export interface XuanjiDeltaResponse {
  total: number
  items: XuanjiDeltaCandidate[]
  params: Record<string, any>
}

export interface XuanjiGreeksSummary {
  total: number
  summary: {
    delta_mean: number
    gamma_mean: number
    vega_mean: number
    theta_mean: number
    iv_mean: number
  }
  distribution: {
    high_delta: number
    mid_delta: number
    low_delta: number
  }
}

export interface XuanjiMarketWeight {
  value: string
  label_cn: string
  weights: Record<string, number>
}

export interface XuanjiMarketWeightsResponse {
  states: XuanjiMarketWeight[]
  factor_names: Record<string, string>
}

export interface XuanjiAlphaSource {
  id: string
  name: string
  range: string
  category: string
  status: string
  implementation: string
}

export interface XuanjiAlphaResponse {
  sources: XuanjiAlphaSource[]
  total_alpha_potential: string
  return_path: Array<{ version: string; neutral: string; optimistic: string }> | string
}

export async function fetchXuanjiRanking(
  topN: number = 50,
  marketState: string = 'mild_bull',
  maxPremium: number = 50,
  minPrice: number = 90,
  maxPrice: number = 150,
  volAdjust: number = 0.85
): Promise<XuanjiRankingResponse> {
  const params = new URLSearchParams({
    top_n: String(topN),
    market_state: marketState,
    max_premium: String(maxPremium),
    min_price: String(minPrice),
    max_price: String(maxPrice),
    vol_adjust: String(volAdjust),
  })
  return fetchJSON<XuanjiRankingResponse>(`${getBase()}/xuanji/ranking?${params.toString()}`, `xuanji_ranking_${params.toString().slice(0, 40)}`, 3 * 60 * 1000)
}

export async function fetchXuanjiSingle(code: string, marketState: string = 'mild_bull', maxPremium: number = 80, minPrice: number = 80, maxPrice: number = 180, volAdjust: number = 0.85): Promise<XuanjiSingleResponse> {
  const params = new URLSearchParams({
    market_state: marketState,
    max_premium: String(maxPremium),
    min_price: String(minPrice),
    max_price: String(maxPrice),
    vol_adjust: String(volAdjust),
  })
  return fetchJSON<XuanjiSingleResponse>(`${getBase()}/xuanji/single/${code}?${params.toString()}`, `xuanji_single_${code}`, 3 * 60 * 1000)
}

export async function fetchXuanjiDeltaCandidates(
  minIvHv: number = 5.0,
  premiumLow: number = 20.0,
  premiumHigh: number = 80.0,
  topN: number = 30
): Promise<XuanjiDeltaResponse> {
  const params = new URLSearchParams({
    min_iv_hv: String(minIvHv),
    premium_low: String(premiumLow),
    premium_high: String(premiumHigh),
    top_n: String(topN),
  })
  return fetchJSON<XuanjiDeltaResponse>(`${getBase()}/xuanji/delta-candidates?${params.toString()}`, 'xuanji_delta_candidates', 3 * 60 * 1000)
}

export async function fetchXuanjiGreeks(): Promise<XuanjiGreeksSummary> {
  return fetchJSON<XuanjiGreeksSummary>(`${getBase()}/xuanji/greeks`, 'xuanji_greeks', 10 * 60 * 1000)
}

export async function fetchXuanjiMarketWeights(): Promise<XuanjiMarketWeightsResponse> {
  return fetchJSON<XuanjiMarketWeightsResponse>(`${getBase()}/xuanji/market-weights`, 'xuanji_market_weights', 10 * 60 * 1000)
}

export async function fetchXuanjiAlphaSources(): Promise<XuanjiAlphaResponse> {
  return fetchJSON<XuanjiAlphaResponse>(`${getBase()}/xuanji/alpha-sources`, 'xuanji_alpha_sources', 10 * 60 * 1000)
}

export interface XuanjiStressScenario {
  name: string
  description: string
  expected_return: number
  max_drawdown: number
  win_rate: number
  selected_count: number
}

export interface XuanjiStressResponse {
  market_state: string
  total_bonds: number
  total_unfiltered?: number
  scenarios: XuanjiStressScenario[]
  summary: {
    avg_return: number
    worst_case: number
    best_case: number
    expected_sharpe: number
  }
}

export async function fetchXuanjiStressTest(topN: number = 50, marketState: string = 'mild_bull'): Promise<XuanjiStressResponse> {
  return fetchJSON<XuanjiStressResponse>(`${getBase()}/xuanji/stress-test?top_n=${topN}&market_state=${marketState}`, `xuanji_stress_${marketState}`, 3 * 60 * 1000)
}

export interface XuanjiFactorContribution {
  factor: string
  name: string
  mean_score: number
  weight: number
  contribution: number
  contribution_pct: number
}

export interface XuanjiFactorContributionResponse {
  market_state: string
  top_n: number
  factors: XuanjiFactorContribution[]
  total_score: number
  total_unfiltered?: number
  selection: {
    count: number
    avg_price: number
    avg_premium: number
    avg_dual_low: number
    avg_hv: number
  }
}

export async function fetchXuanjiFactorContribution(topN: number = 20, marketState: string = 'mild_bull'): Promise<XuanjiFactorContributionResponse> {
  return fetchJSON<XuanjiFactorContributionResponse>(`${getBase()}/xuanji/factor-contribution?top_n=${topN}&market_state=${marketState}`, `xuanji_factor_contrib_${marketState}`, 3 * 60 * 1000)
}

export interface XuanjiFactorCorrelation {
  factor1: string
  factor2: string
  correlation: number
  abs_correlation: number
  redundancy: 'high' | 'medium' | 'low'
}

export interface XuanjiFactorCorrelationResponse {
  market_state: string
  top_n: number
  total_pairs: number
  high_redundancy_pairs: number
  total_unfiltered?: number
  correlations: XuanjiFactorCorrelation[]
}

export async function fetchXuanjiFactorCorrelation(topN: number = 50, marketState: string = 'mild_bull'): Promise<XuanjiFactorCorrelationResponse> {
  return fetchJSON<XuanjiFactorCorrelationResponse>(`${getBase()}/xuanji/factor-correlation?top_n=${topN}&market_state=${marketState}`, `xuanji_factor_corr_${marketState}`, 3 * 60 * 1000)
}

export interface XuanjiStrategyCompare {
  id: string
  name: string
  factors: number
  market_adaptive: boolean
  avg_score: number
  avg_price: number
  selected: number
  overlap_with_xuanji: number
  overlap_with_mf: number
  overlap_with_xb: number
}

export interface XuanjiComparisonResponse {
  top_n: number
  total_bonds: number
  total_unfiltered?: number
  strategies: XuanjiStrategyCompare[]
}

export async function fetchXuanjiComparison(topN: number = 50, marketState: string = 'mild_bull'): Promise<XuanjiComparisonResponse> {
  return fetchJSON<XuanjiComparisonResponse>(`${getBase()}/xuanji/comparison?top_n=${topN}&market_state=${marketState}`, `xuanji_comparison_${marketState}`, 3 * 60 * 1000)
}

export interface XuanjiSummary {
  strategy: any
  target_returns: any
  key_features: any
  endpoints: any
}

export async function fetchXuanjiSummary(): Promise<XuanjiSummary> {
  return fetchJSON<XuanjiSummary>(`${getBase()}/xuanji/summary`, 'xuanji_summary', 10 * 60 * 1000)
}

export async function fetchXuanjiHealth(): Promise<{ status: string; strategy: string; version: string }> {
  return fetchJSON(`${getBase()}/xuanji/health`)
}

export async function fetchXuanjiDataSourceHealth(): Promise<any> {
  return fetchJSON(`${getBase()}/xuanji/data-source-health`) // 数据源健康状态不缓存
}

export async function fetchXuanjiIcirHistory(): Promise<any> {
  return fetchJSON(`${getBase()}/xuanji/icir-history`, 'xuanji_icir', 5 * 60 * 1000)
}

export async function postXuanjiCustomRanking(params: {
  weights: Record<string, number>
  top_n?: number
  market_state?: string
  max_premium?: number
  min_price?: number
  max_price?: number
}): Promise<any> {
  return postJSON(`${getBase()}/xuanji/custom-ranking`, params)
}

// ── Industry / Sector rotation ─────────────────────────────────────

export interface IndustryAgg {
  industry: string
  bond_count: number
  avg_change_pct: number
  avg_stock_change_pct: number
  avg_premium_ratio: number
  avg_dual_low: number
  avg_ytm: number
  avg_roe: number
  avg_pe: number
  avg_pb: number
  avg_gpm: number
  avg_debt_ratio: number
  avg_turnover_rate: number
  avg_cagr: number
  avg_pledge_ratio: number
  avg_momentum_5d: number
  avg_momentum_10d: number
  avg_momentum_20d: number
  avg_momentum_60d: number
  momentum_dispersion: number
  net_capital_flow: number
  net_super_flow: number
  net_big_flow: number
  avg_iv: number
  total_volume: number
  up_count: number
  down_count: number
}

export interface IndustriesResponse {
  industries: IndustryAgg[]
  total_bonds: number
  total_industries: number
}

export async function fetchIndustries(): Promise<IndustriesResponse> {
  return fetchJSON<IndustriesResponse>(`${getBase()}/market/industries`, 'industries', 30000)
}

// ── Concept distribution ──────────────────────────────────────────

export interface ConceptAgg {
  concept: string
  bond_count: number
  avg_change_pct: number
  avg_stock_change_pct: number
  avg_premium_ratio: number
  avg_dual_low: number
  avg_ytm: number
  avg_roe: number
  avg_pe: number
  avg_pb: number
  avg_gpm: number
  avg_debt_ratio: number
  avg_turnover_rate: number
  avg_cagr: number
  avg_pledge_ratio: number
  avg_momentum_5d: number
  avg_momentum_10d: number
  avg_momentum_20d: number
  avg_momentum_60d: number
  momentum_dispersion: number
  net_capital_flow: number
  net_super_flow: number
  net_big_flow: number
  avg_iv: number
  total_volume: number
  up_count: number
  down_count: number
  top_bonds: { code: string; name: string; price: number; change_pct: number; premium_ratio: number; dual_low: number }[]
}

export interface ConceptsResponse {
  concepts: ConceptAgg[]
  total_bonds: number
  total_concepts: number
  sources: string[]
}

export async function fetchConcepts(): Promise<ConceptsResponse> {
  return fetchJSON<ConceptsResponse>(`${getBase()}/market/concepts`, 'concepts', 30000)
}

// ── ETF / Sector mapping ───────────────────────────────────────────

export interface SectorEtf {
  sw_code: string
  etf_code: string
  etf_name: string
  sector: string
}

export const SECTOR_ETF_MAP: SectorEtf[] = [
  { sw_code: '801010', etf_code: '159919', etf_name: '沪深300ETF', sector: '金融' },
  { sw_code: '801020', etf_code: '510500', etf_name: '中证500ETF', sector: '周期' },
  { sw_code: '801030', etf_code: '159915', etf_name: '创业板ETF', sector: '成长' },
  { sw_code: '801040', etf_code: '510880', etf_name: '红利ETF', sector: '红利' },
  { sw_code: '801050', etf_code: '515050', etf_name: '科技ETF', sector: '科技' },
  { sw_code: '801060', etf_code: '512880', etf_name: '证券ETF', sector: '金融' },
  { sw_code: '801070', etf_code: '512070', etf_name: '非银ETF', sector: '非银金融' },
  { sw_code: '801080', etf_code: '512690', etf_name: '酒ETF', sector: '消费' },
  { sw_code: '801090', etf_code: '512010', etf_name: '医药ETF', sector: '医药' },
  { sw_code: '801100', etf_code: '516160', etf_name: '新能源ETF', sector: '新能源' },
  { sw_code: '801110', etf_code: '515800', etf_name: '800ETF', sector: '宽基' },
  { sw_code: '801120', etf_code: '515220', etf_name: '煤炭ETF', sector: '能源' },
  { sw_code: '801130', etf_code: '512100', etf_name: '1000ETF', sector: '小盘' },
  { sw_code: '801140', etf_code: '516510', etf_name: '云计算ETF', sector: '云计算' },
  { sw_code: '801150', etf_code: '515030', etf_name: '新汽车ETF', sector: '汽车' },
  { sw_code: '801160', etf_code: '512660', etf_name: '军工ETF', sector: '军工' },
  { sw_code: '801170', etf_code: '515790', etf_name: '光伏ETF', sector: '光伏' },
  { sw_code: '801180', etf_code: '516110', etf_name: '汽车ETF', sector: '汽车' },
  { sw_code: '801190', etf_code: '512580', etf_name: '碳中和ETF', sector: '碳中和' },
  { sw_code: '801200', etf_code: '562800', etf_name: '稀有金属ETF', sector: '稀有金属' },
]

// ── Stock Industry Rotation ───────────────────────────────────────────

export interface StockIndustryItem {
  stock_code: string
  stock_name: string
  stock_price: number
  stock_change_pct: number
  pe: number
  pb: number
  roe: number
  gpm: number
  momentum_5d: number
  momentum_10d: number
  momentum_20d: number
  momentum_60d: number
  turnover_rate: number
  net_capital_flow: number
  debt_ratio: number
  iv: number
  pledge_ratio: number
  cagr: number
}

export interface StockIndustryAgg {
  industry: string
  stock_count: number
  avg_stock_change_pct: number
  avg_stock_price: number
  avg_momentum_5d: number
  avg_momentum_10d: number
  avg_momentum_20d: number
  avg_momentum_60d: number
  momentum_dispersion: number
  avg_roe: number
  avg_pe: number
  avg_pb: number
  avg_gpm: number
  avg_debt_ratio: number
  avg_turnover_rate: number
  net_capital_flow: number
  net_capital_flow_pct: number
  net_super_flow: number
  net_big_flow: number
  avg_iv: number
  avg_pledge_ratio: number
  avg_cagr: number
  total_volume: number
  up_count: number
  down_count: number
  stocks: StockIndustryItem[]
}

export interface StockIndustriesResponse {
  industries: StockIndustryAgg[]
  total_stocks: number
  total_industries: number
  recommendations?: IndustryRecommendations
}

// ── Industry Layout Recommendations (短期/中期/长期) ────────────────────

export interface IndustryRecommendation {
  industry: string
  score: number
  signal_strength: 'strong' | 'moderate'
  reasons: string[]
  metrics: {
    momentum_5d: number
    momentum_10d: number
    momentum_20d: number
    momentum_60d: number
    net_capital_flow_pct: number
    avg_roe: number
    avg_pe: number
    avg_gpm: number
    stock_count: number
  }
}

export interface IndustryRecommendations {
  short_term: IndustryRecommendation[]
  mid_term: IndustryRecommendation[]
  long_term: IndustryRecommendation[]
  generated_at?: string
}

export async function fetchStockIndustries(): Promise<StockIndustriesResponse> {
  // 资金流向数据实时性要求高, 加 _t 参数绕过浏览器 HTTP 缓存
  return fetchJSON<StockIndustriesResponse>(`${getBase()}/market/stock-industries?_t=${Date.now()}`, 'stock_industries', 30000)
}

// 按周期懒加载行业推荐 (可选, 主数据已内嵌 recommendations)
export async function fetchIndustryRecommendations(
  horizon: 'short' | 'mid' | 'long' | 'all' = 'all',
  topK = 5,
  weightsJson = ''
): Promise<{ horizon: string } & Partial<IndustryRecommendations>> {
  let url = `${getBase()}/market/industry-recommendations?horizon=${horizon}&top_k=${topK}`
  if (weightsJson) {
    url += `&weights_json=${encodeURIComponent(weightsJson)}`
  }
  // Custom weights should not be cached (bypass cache key)
  return weightsJson
    ? fetchJSON(url, `industry_recs_custom_${Date.now()}`, 0)
    : fetchJSON(url, `industry_recs_${horizon}`, 60000)
}

// AI 行业解读 (POST, 不缓存)
export async function fetchAIInsight(params: {
  type: string
  context: Record<string, unknown>
  question: string
  language: string
}): Promise<{ summary: string; insights: string[]; recommendations: string[] }> {
  if (!getBase()) throw new Error('API base URL not configured')
  return requestAPI('POST', `${getBase()}/ai/analyze`, params)
}

// 推荐历史 (GET, 缓存5分钟)
export interface RecHistoryEntry {
  date: string
  short_term: IndustryRecommendation[]
  mid_term: IndustryRecommendation[]
  long_term: IndustryRecommendation[]
  generated_at?: string
}

export interface RecHistoryResponse {
  history: RecHistoryEntry[]
  days: number
}

export async function fetchRecHistory(days = 30): Promise<RecHistoryResponse> {
  return fetchJSON<RecHistoryResponse>(`${getBase()}/market/industry-recommendations/history?days=${days}`, 'rec_history', 300000)
}

// Recommendation accuracy backtest
export interface AccuracyDetail {
  date: string
  industry: string
  score: number
  baseline: number
  current: number
  actual: number
  hit: boolean
}
export interface HorizonAccuracy {
  total: number
  hits: number
  hit_rate: number
  alpha: number
  details: AccuracyDetail[]
}
export interface RecAccuracyResponse {
  accuracy: Record<string, HorizonAccuracy>
  random_baseline: Record<string, number>
  daily_alpha: Record<string, Record<string, number>>
  days_analyzed: number
}
export async function fetchRecAccuracy(days = 30): Promise<RecAccuracyResponse> {
  return fetchJSON<RecAccuracyResponse>(`${getBase()}/market/industry-recommendations/accuracy?days=${days}`, 'rec_accuracy', 300000)
}

// ── Extended data sources (北向/融资融券/龙虎榜/大宗/股东/业绩/解禁) ────────

export interface NorthSummary {
  type: string
  change: number
  fund_flow: number
  super_flow: number
  big_flow: number
  _summary: boolean
}

export interface NorthStock {
  code: string
  name: string
  type: string
  change_pct: number
  hold_shares: number
  hold_market_cap: number
  hold_ratio: number
  add_shares: number
  add_market_cap: number
}

export interface NorthResponse {
  summary: NorthSummary[]
  stocks: NorthStock[]
  total: number
}

export async function fetchNorthCapital(): Promise<NorthResponse> {
  return fetchJSON<NorthResponse>(`${getBase()}/market/north-capital`, 'north', 60000)
}

export interface MarginStock {
  code: string
  name: string
  rzye: number
  rzmre: number
  rzrqye: number
  rqyl: number
}

export interface MarginResponse {
  stocks: MarginStock[]
  summary: any[]
  total: number
}

export async function fetchMarginStocks(): Promise<MarginResponse> {
  return fetchJSON<MarginResponse>(`${getBase()}/market/margin-stocks`, 'margin', 60000)
}

export interface LhbStock {
  code: string
  name: string
  times: number
  buy_amt: number
  sell_amt: number
  net_buy_amt: number
}

export interface LhbResponse {
  stocks: LhbStock[]
  total: number
}

export async function fetchLhb(): Promise<LhbResponse> {
  return fetchJSON<LhbResponse>(`${getBase()}/market/lhb`, 'lhb', 60000)
}

export interface BlockTradeStock {
  code: string
  name: string
  total_amt: number
  trade_count: number
  avg_discount: number
  max_price: number
  min_price: number
}

export interface BlockTradeResponse {
  stocks: BlockTradeStock[]
  total: number
}

export async function fetchBlockTrade(): Promise<BlockTradeResponse> {
  return fetchJSON<BlockTradeResponse>(`${getBase()}/market/block-trade`, 'block_trade', 60000)
}

export interface HolderNumStock {
  code: string
  name: string
  holder_num: number
  stat_date: string
  avg_hold_shares: number
  change_pct: number
}

export interface HolderNumResponse {
  stocks: HolderNumStock[]
  total: number
}

export async function fetchHolderNum(): Promise<HolderNumResponse> {
  return fetchJSON<HolderNumResponse>(`${getBase()}/market/holder-num`, 'holder_num', 60000)
}

export interface EarningsForecastStock {
  code: string
  name: string
  period: string
  forecast_type: string
  change_pct_min: number
  change_pct_max: number
  summary: string
  announce_date: string
}

export interface EarningsForecastResponse {
  stocks: EarningsForecastStock[]
  total: number
}

export async function fetchEarningsForecast(): Promise<EarningsForecastResponse> {
  return fetchJSON<EarningsForecastResponse>(`${getBase()}/market/earnings-forecast`, 'earnings_forecast', 60000)
}

export interface EarningsExpressStock {
  code: string
  name: string
  period: string
  revenue: number
  revenue_yoy: number
  net_profit: number
  net_profit_yoy: number
  eps: number
  roe: number
  announce_date: string
}

export interface EarningsExpressResponse {
  stocks: EarningsExpressStock[]
  total: number
}

export async function fetchEarningsExpress(): Promise<EarningsExpressResponse> {
  return fetchJSON<EarningsExpressResponse>(`${getBase()}/market/earnings-express`, 'earnings_express', 60000)
}

export interface RestrictedReleaseEvent {
  code: string
  name: string
  release_date: string
  release_shares: number
  release_market_cap: number
  release_ratio: number
  release_type: string
  shareholder_count: number
}

export interface RestrictedReleaseResponse {
  events: RestrictedReleaseEvent[]
  total: number
}

export async function fetchRestrictedRelease(): Promise<RestrictedReleaseResponse> {
  return fetchJSON<RestrictedReleaseResponse>(`${getBase()}/market/restricted-release`, 'restricted_release', 60000)
}

export interface DataSourceInfo {
  path: string
  exists: boolean
  size?: number
  entries?: number
  ts?: number
  age_seconds?: number
  error?: string
}

export interface DataSourcesResponse {
  sources: Record<string, DataSourceInfo>
  cache_dir?: string
}

export async function fetchDataSources(): Promise<DataSourcesResponse> {
  // 数据源状态实时性要求高, 加 _t 参数绕过浏览器 HTTP 缓存
  return fetchJSON<DataSourcesResponse>(`${getBase()}/market/data-sources?_t=${Date.now()}`, 'data_sources', 30000)
}

// ── Stock Concept Rotation (THS + EastMoney fine-grained concept boards) ──────

export interface StockConceptItem {
  stock_code: string
  stock_name: string
  stock_price: number
  stock_change_pct: number
  pe: number
  pb: number
  roe: number
  gpm: number
  momentum_5d: number
  momentum_10d: number
  momentum_20d: number
  momentum_60d: number
  turnover_rate: number
  net_capital_flow: number
  debt_ratio: number
  iv: number
  pledge_ratio: number
  cagr: number
}

export interface StockConceptAgg {
  concept: string
  stock_count: number
  sources: string[]   // subset of ["eastmoney", "ths"] — which source lists this concept
  avg_stock_change_pct: number
  avg_stock_price: number
  avg_momentum_5d: number
  avg_momentum_10d: number
  avg_momentum_20d: number
  avg_momentum_60d: number
  momentum_dispersion: number
  avg_roe: number
  avg_pe: number
  avg_pb: number
  avg_gpm: number
  avg_debt_ratio: number
  avg_turnover_rate: number
  avg_pledge_ratio: number
  avg_cagr: number
  net_capital_flow: number
  net_super_flow: number
  net_big_flow: number
  avg_iv: number
  total_volume: number
  up_count: number
  down_count: number
  top_stocks: StockConceptItem[]
}

export interface StockConceptsResponse {
  concepts: StockConceptAgg[]
  total_concepts: number
  total_stocks: number
  sources: string[]
  source_filter: string
  min_count: number
}

export type StockConceptSource = 'all' | 'em' | 'ths' | 'both' | 'em_only' | 'ths_only'

export async function fetchStockConcepts(opts?: {
  source?: StockConceptSource
  minCount?: number
  fields?: string[]
}): Promise<StockConceptsResponse> {
  const params = new URLSearchParams()
  params.set('source', opts?.source ?? 'all')
  params.set('min_count', String(opts?.minCount ?? 2))
  if (opts?.fields?.length) params.set('fields', opts.fields.join(','))
  return fetchJSON<StockConceptsResponse>(
    `${getBase()}/market/stock-concepts?${params.toString()}`,
    'stock-concepts',
    30000,
  )
}

// ── Fund Flow APIs (资金流向) ────────────────────────────────────────────────────

export interface IndividualFundFlow {
  code: string
  name: string
  price: number
  change_pct: number
  turnover_rate: number
  inflow: number  // 流入资金（亿）
  outflow: number  // 流出资金（亿）
  net_inflow: number  // 净流入（亿）
  amount: number  // 成交额（亿）
}

export interface IndustryFundFlow {
  rank: number
  industry: string
  industry_index: number
  change_pct: number
  inflow: number
  outflow: number
  net_inflow: number
  company_count: number
  leading_stock: string
  leading_change: number
  current_price: number
}

export interface MainFundFlow {
  code: string
  name: string
  price: number
  change_pct: number
  turnover_rate: number
  main_net_inflow: number  // 主力净流入
  super_large_net: number  // 超大单净流入
  large_net: number  // 大单净流入
  medium_net: number  // 中单净流入
  small_net: number  // 小单净流入
  is_estimated: boolean  // true=按比例估算, false=真实数据
}

export interface TurnoverRank {
  code: string
  name: string
  price: number
  change_pct: number
  turnover_rate: number
  volume: number
  amount: number
}

export interface HsgtFundFlow {
  date: string
  type: string
  plate: string
  direction: string
  status: number
  status_text: string  // 交易状态中文描述
  net_buy: number | null
  net_inflow: number | null
  balance: number | null
  up_count: number | null
  hold_count: number | null
  down_count: number | null
  index_name: string
  index_change: number | null
}

export interface IndividualFundFlowResponse {
  stocks: IndividualFundFlow[]
  total: number
}

export interface IndustryFundFlowResponse {
  industries: IndustryFundFlow[]
  total: number
}

export interface MainFundFlowResponse {
  stocks: MainFundFlow[]
  total: number
}

export interface TurnoverRankResponse {
  stocks: TurnoverRank[]
  total: number
}

export interface HsgtFundFlowResponse {
  flows: HsgtFundFlow[]
  total: number
}

/**
 * 个股资金流向排名
 * @param indicator 时间指标: 今日, 3日, 5日, 10日
 * @param limit 返回条数限制
 */
export async function fetchIndividualFundFlow(
  indicator: string = '今日',
  limit: number = 100
): Promise<IndividualFundFlowResponse> {
  const params = new URLSearchParams()
  params.set('indicator', indicator)
  params.set('limit', String(limit))
  const data = await fetchJSON<IndividualFundFlowResponse>(
    `${getBase()}/fund_flow/individual?${params.toString()}`,
    `individual_fund_flow_${indicator}`,
    60000,  // 1分钟缓存
  )
  if (!data || !Array.isArray(data.stocks)) {
    throw new Error(`Invalid individual fund flow response: expected {stocks: [...], total: number}, got ${typeof data}`)
  }
  return data
}

/**
 * 行业资金流向
 * @param indicator 时间指标: 今日, 3日, 5日, 10日
 */
export async function fetchIndustryFundFlow(
  indicator: string = '今日'
): Promise<IndustryFundFlowResponse> {
  const params = new URLSearchParams()
  params.set('indicator', indicator)
  const data = await fetchJSON<IndustryFundFlow[]>(
    `${getBase()}/fund_flow/industry?${params.toString()}`,
    `industry_fund_flow_${indicator}`,
    60000,
  )
  return { industries: data, total: data.length }
}

/**
 * 主力资金流向（超大单/大单/中单/小单拆分）
 * @param limit 返回条数限制
 */
export async function fetchMainFundFlow(
  limit: number = 100
): Promise<MainFundFlowResponse> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  const data = await fetchJSON<MainFundFlowResponse>(
    `${getBase()}/fund_flow/main?${params.toString()}`,
    'main_fund_flow',
    60000,
  )
  if (!data || !Array.isArray(data.stocks)) {
    throw new Error(`Invalid main fund flow response: expected {stocks: [...], total: number}, got ${typeof data}`)
  }
  return data
}

/**
 * 换手率排名
 * @param limit 返回条数限制
 */
export async function fetchTurnoverRank(
  limit: number = 100
): Promise<TurnoverRankResponse> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  const data = await fetchJSON<TurnoverRankResponse>(
    `${getBase()}/fund_flow/turnover_rank?${params.toString()}`,
    'turnover_rank',
    60000,
  )
  if (!data || !Array.isArray(data.stocks)) {
    throw new Error(`Invalid turnover rank response: expected {stocks: [...], total: number}, got ${typeof data}`)
  }
  return data
}

/**
 * 沪深港通资金流向
 */
export async function fetchHsgtFundFlow(): Promise<HsgtFundFlowResponse> {
  const data = await fetchJSON<HsgtFundFlow[]>(
    `${getBase()}/fund_flow/hsgt`,
    'hsgt_fund_flow',
    60000,
  )
  return { flows: data, total: data.length }
}


// ═══════════════════════════════════════════════════════════════════════════════
// 妙想MX金融数据
// ═══════════════════════════════════════════════════════════════════════════════

export interface MXQueryRequest {
  query: string
  data_type: 'financial' | 'news'
}

export interface MXQueryResponse {
  success: boolean
  data: any[]
  total_rows: number
  tables?: any[]
  message: string
  source: string
}

export async function queryMXData(req: MXQueryRequest): Promise<MXQueryResponse> {
  let token = ''
  try { token = localStorage.getItem('token') || '' } catch { /* localStorage unavailable */ }
  const res = await fetch(`${getBase()}/mx/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  return res.json()
}

export async function getMXStatus(): Promise<{
  configured: boolean
  api_key_prefix: string
  skills_installed: Record<string, boolean>
}> {
  return fetchJSON(`${getBase()}/mx/status`)  // 状态信息不缓存，确保实时
}

// ── 模拟盘 API ──

export async function fetchPaperAccounts(): Promise<{ accounts: any[]; refresh_fail_count?: number; refresh_total_fails?: number; refresh_total_fail_threshold?: number }> {
  return fetchJSON(`${getBase()}/paper-trade/accounts`, 'paper_accounts')
}

export async function createPaperAccount(req: { strategy_id: string; initial_cash?: number; params?: any }): Promise<any> {
  return postJSON(`${getBase()}/paper-trade/accounts`, req)
}

export async function startPaperAccount(accountId: string): Promise<any> {
  return postJSON(`${getBase()}/paper-trade/accounts/${accountId}/start`, {})
}

export async function stopPaperAccount(accountId: string): Promise<any> {
  return postJSON(`${getBase()}/paper-trade/accounts/${accountId}/stop`, {})
}

export async function resetPaperAccount(accountId: string): Promise<any> {
  return postJSON(`${getBase()}/paper-trade/accounts/${accountId}/reset`, {})
}

export async function fetchPaperPositions(accountId: string): Promise<{ positions: any[] }> {
  return fetchJSON(`${getBase()}/paper-trade/accounts/${accountId}/positions`)
}

export async function fetchPaperOrders(accountId: string): Promise<{ orders: any[] }> {
  return fetchJSON(`${getBase()}/paper-trade/accounts/${accountId}/orders`)
}

export async function fetchPaperEquityCurve(accountId: string, days: number = 30): Promise<{ points: any[] }> {
  return fetchJSON(`${getBase()}/paper-trade/accounts/${accountId}/equity-curve?days=${days}`)
}

export async function fetchPaperSignals(accountId: string, limit: number = 50): Promise<{ signals: any[] }> {
  return fetchJSON(`${getBase()}/paper-trade/accounts/${accountId}/signals?limit=${limit}`)
}

export async function updatePaperParams(accountId: string, params: Record<string, any>): Promise<any> {
  return putJSON(`${getBase()}/paper-trade/accounts/${accountId}/params`, { params })
}

export async function deletePaperAccount(accountId: string): Promise<any> {
  return deleteJSON(`${getBase()}/paper-trade/accounts/${accountId}`)
}

export async function forceRebalancePaperAccount(accountId: string): Promise<{ status: string; message?: string; signals?: any[]; positions?: any[] }> {
  return postJSON(`${getBase()}/paper-trade/accounts/${accountId}/force-rebalance`, {})
}

// -- Multi-source data source APIs (/data-sources-v2 and /extra)

export async function fetchStockValuations(stockCodes: string[], stockPrices?: Record<string, number>): Promise<Record<string, { pe?: number; pb?: number }>> {
  return postJSON(`${getBase()}/data-sources-v2/valuations`, { stock_codes: stockCodes, stock_prices: stockPrices || {} })
}

export async function fetchStockHistPrices(stockCode: string, startDate: string, endDate: string): Promise<{ date: string; close: number; open?: number; high?: number; low?: number; volume?: number }[]> {
  return postJSON(`${getBase()}/data-sources-v2/hist-prices`, { stock_code: stockCode, start_date: startDate, end_date: endDate })
}

export async function fetchCbDailyTushare(params?: { trade_date?: string; start_date?: string; end_date?: string }): Promise<any[]> {
  const qs = new URLSearchParams(params || {})
  return fetchJSON(`${getBase()}/data-sources-v2/cb-daily-tushare?${qs.toString()}`)
}

export async function fetchCbBasicTushare(): Promise<Record<string, any>> {
  return fetchJSON(`${getBase()}/data-sources-v2/cb-basic-tushare`)
}

export async function fetchValueAnalysis(bondCodes: string[], maxWorkers: number = 10): Promise<any[]> {
  return postJSON(`${getBase()}/extra/value-analysis`, { bond_codes: bondCodes, max_workers: maxWorkers })
}

export async function fetchBondDailyEM(bondCodes: string[], startDate: string, endDate: string, maxWorkers: number = 10): Promise<any[]> {
  return postJSON(`${getBase()}/extra/bond-daily-em`, { bond_codes: bondCodes, start_date: startDate, end_date: endDate, max_workers: maxWorkers })
}

export async function fetchIndustryBatch(stockCodes: string[], maxWorkers: number = 8): Promise<Record<string, string>> {
  return postJSON(`${getBase()}/extra/industry`, { stock_codes: stockCodes, max_workers: maxWorkers })
}

export async function fetchBondMiscData(): Promise<any> {
  return fetchJSON(`${getBase()}/extra/bond-misc`)
}

export async function fetchCSIIndex(startDate: string, endDate: string): Promise<any[]> {
  return postJSON(`${getBase()}/extra/csi-index`, { start_date: startDate, end_date: endDate })
}

export async function fetchFinancialTHS(stockCodes: string[], maxWorkers: number = 8): Promise<Record<string, any>> {
  return postJSON(`${getBase()}/extra/financial-ths`, { stock_codes: stockCodes, max_workers: maxWorkers })
}

export async function fetchBondKlineEM(bondCodes: string[], startDate: string, endDate: string, maxWorkers: number = 10): Promise<any[]> {
  return postJSON(`${getBase()}/extra/bond-kline-em`, { bond_codes: bondCodes, start_date: startDate, end_date: endDate, max_workers: maxWorkers })
}

// -- 后台任务 API (Task registry)
// 适用于 /data-sources-v2/* 与 /extra/* 中的长耗时批量接口

export interface TaskCreateResponse {
  task_id: string
  status: string
}

export interface TaskInfo {
  task_id: string
  name: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  created_at: number
  updated_at: number
  progress: Record<string, any>
  result?: any
  error?: string
}

export async function submitTask<T = any>(
  endpoint: 'valuations' | 'hist-prices' | 'cb-daily-tushare' | 'cb-basic-tushare' |
            'value-analysis' | 'bond-daily-em' | 'industry' | 'csi-index' | 'financial-ths' | 'bond-kline-em',
  payload?: Record<string, any>
): Promise<TaskCreateResponse> {
  const isExtra = ['value-analysis', 'bond-daily-em', 'industry', 'csi-index', 'financial-ths', 'bond-kline-em'].includes(endpoint)
  const prefix = isExtra ? `${getBase()}/extra` : `${getBase()}/data-sources-v2`
  const method = endpoint === 'cb-daily-tushare' || endpoint === 'cb-basic-tushare' ? 'GET' : 'POST'
  let url = `${prefix}/${endpoint}`
  if (method === 'GET' && payload) {
    const qs = new URLSearchParams(payload as Record<string, string>)
    url = `${url}?${qs.toString()}&async_task=true`
    return requestAPI<TaskCreateResponse>('GET', url)
  }
  return requestAPI<TaskCreateResponse>('POST', url, { ...(payload || {}), async_task: true })
}

export async function getTask(taskId: string, base: 'data-sources-v2' | 'extra' = 'data-sources-v2'): Promise<TaskInfo> {
  return requestAPI<TaskInfo>('GET', `${getBase()}/${base}/tasks/${taskId}`)
}

export async function listTasks(
  base: 'data-sources-v2' | 'extra' = 'data-sources-v2',
  opts?: { status?: string; limit?: number }
): Promise<Pick<TaskInfo, 'task_id' | 'name' | 'status' | 'created_at' | 'updated_at' | 'progress'>[]> {
  const qs = new URLSearchParams(opts as Record<string, string> || {})
  return requestAPI('GET', `${getBase()}/${base}/tasks?${qs.toString()}`)
}

/**
 * 轮询等待后台任务完成
 */
export async function pollTaskUntilDone<T = any>(
  taskId: string,
  base: 'data-sources-v2' | 'extra' = 'data-sources-v2',
  opts?: { interval?: number; timeout?: number; onProgress?: (info: TaskInfo) => void }
): Promise<TaskInfo & { result?: T }> {
  const interval = opts?.interval ?? 2000
  const timeout = opts?.timeout ?? 300000
  const start = Date.now()
  while (Date.now() - start < timeout) {
    const info = await getTask(taskId, base)
    opts?.onProgress?.(info)
    if (info.status === 'success' || info.status === 'failed' || info.status === 'cancelled') {
      return info as TaskInfo & { result?: T }
    }
    await new Promise(r => setTimeout(r, interval))
  }
  throw new Error(`Task ${taskId} polling timeout after ${timeout}ms`)
}
