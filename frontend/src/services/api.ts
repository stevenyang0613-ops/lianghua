import type { ConvertibleQuote } from '../types'

const BASE = '/api/v1'

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) {
    const text = await resp.text()
    try {
      const json = JSON.parse(text)
      throw new ApiError(resp.status, json.detail || `HTTP ${resp.status}`)
    } catch {
      throw new ApiError(resp.status, text || `HTTP ${resp.status}`)
    }
  }
  return resp.json()
}

export async function fetchAllQuotes(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  return fetchJSON(`${BASE}/market/quotes`)
}

export async function fetchQuote(code: string): Promise<ConvertibleQuote> {
  return fetchJSON(`${BASE}/market/quotes/${code}`)
}

export async function healthCheck(): Promise<{ status: string; app: string; market_running: boolean }> {
  return fetchJSON('/health')
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
  const resp = await fetch(BASE + '/backtest/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function runOptimization(req: BacktestRequest): Promise<{ success: boolean; result: OptimizationResult }> {
  const resp = await fetch(BASE + '/backtest/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
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
  const resp = await fetch(`${BASE}/trade/order`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text || `HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function cancelOrder(orderId: string): Promise<{ status: string }> {
  return fetchJSON(`${BASE}/trade/order/${orderId}/cancel`)
}

export async function resetAccount(): Promise<{ status: string }> {
  const resp = await fetch(`${BASE}/trade/reset`, { method: 'POST' })
  return resp.json()
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
