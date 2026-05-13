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

export interface BacktestRequest {
  strategy: string
  params: Record<string, number>
  start_date: string
  end_date: string
}

export interface BacktestResult {
  strategy_name: string
  strategy_params: Record<string, number>
  start_date: string
  end_date: string
  metrics: {
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

export async function runBacktest(req: BacktestRequest): Promise<BacktestResult> {
  const resp = await fetch(BASE + '/backtest/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = await resp.json()
  return data.result
}
