/**
 * 策略回放引擎
 * 可视化历史策略执行过程
 */

export interface ReplayStep {
  step: number
  date: string
  action: 'buy' | 'sell' | 'hold'
  code: string
  name: string
  price: number
  shares: number
  cash: number
  position: number
  totalValue: number
  profit: number
  profitPct: number
  reason: string
  indicators: Record<string, number>
}

export interface ReplayConfig {
  code: string      // 要回放的转债代码
  strategy: string
  startDate: string
  endDate: string
  initialCash: number
  speed: 'slow' | 'normal' | 'fast'
  showIndicators: boolean
}

export interface ReplayState {
  isPlaying: boolean
  isPaused: boolean
  currentStep: number
  totalSteps: number
  speed: number
}

class StrategyReplayEngine {
  private steps: ReplayStep[] = []
  private currentIndex = 0
  private playInterval: number | null = null
  private listeners: Set<(step: ReplayStep, state: ReplayState) => void> = new Set()
  private stateListeners: Set<(state: ReplayState) => void> = new Set()

  loadSteps(steps: ReplayStep[]): void {
    this.stop() // 先停止播放，避免旧 interval 继续运行
    this.steps = steps
    this.currentIndex = 0
    this.notifyStateListeners()
  }

  play(speed: 'slow' | 'normal' | 'fast' = 'normal'): void {
    if (this.playInterval) return

    const delays = { slow: 2000, normal: 1000, fast: 200 }
    const delay = delays[speed]

    this.playInterval = window.setInterval(() => {
      if (this.currentIndex < this.steps.length - 1) {
        this.currentIndex++
        this.notifyListeners()
        this.notifyStateListeners()
      } else {
        this.stop()
      }
    }, delay)

    this.notifyStateListeners()
  }

  pause(): void {
    if (this.playInterval) {
      clearInterval(this.playInterval)
      this.playInterval = null
    }
    this.notifyStateListeners()
  }

  stop(): void {
    if (this.playInterval) {
      clearInterval(this.playInterval)
      this.playInterval = null
    }
    this.currentIndex = 0
    this.notifyListeners()
    this.notifyStateListeners()
  }

  goToStep(index: number): void {
    if (index >= 0 && index < this.steps.length) {
      this.currentIndex = index
      this.notifyListeners()
      this.notifyStateListeners()
    }
  }

  nextStep(): void {
    if (this.currentIndex < this.steps.length - 1) {
      this.currentIndex++
      this.notifyListeners()
      this.notifyStateListeners()
    }
  }

  prevStep(): void {
    if (this.currentIndex > 0) {
      this.currentIndex--
      this.notifyListeners()
      this.notifyStateListeners()
    }
  }

  getCurrentStep(): ReplayStep | null {
    return this.steps[this.currentIndex] || null
  }

  getState(): ReplayState {
    return {
      isPlaying: this.playInterval !== null,
      isPaused: this.playInterval === null && this.currentIndex > 0,
      currentStep: this.currentIndex,
      totalSteps: this.steps.length,
      speed: 1000,
    }
  }

  getAllSteps(): ReplayStep[] {
    return this.steps
  }

  onStep(listener: (step: ReplayStep, state: ReplayState) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  onStateChange(listener: (state: ReplayState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  private notifyListeners(): void {
    const step = this.getCurrentStep()
    const state = this.getState()
    if (step) {
      this.listeners.forEach(l => l(step, state))
    }
  }

  private notifyStateListeners(): void {
    const state = this.getState()
    this.stateListeners.forEach(l => l(state))
  }

  destroy(): void {
    this.stop()
    this.listeners.clear()
    this.stateListeners.clear()
    this.steps = []
    this.currentIndex = 0
  }

  // 导出回放记录
  exportReplay(): string {
    return JSON.stringify({
      steps: this.steps,
      exportedAt: new Date().toISOString(),
    }, null, 2)
  }

  // 获取回放统计
  getStats(): {
    totalTrades: number
    buyCount: number
    sellCount: number
    winRate: number
    totalReturn: number
    maxDrawdown: number
  } {
    const trades = this.steps.filter(s => s.action !== 'hold')
    const buys = trades.filter(s => s.action === 'buy')
    const sells = trades.filter(s => s.action === 'sell')

    const lastStep = this.steps[this.steps.length - 1]
    const firstStep = this.steps[0]

    let maxDrawdown = 0
    let maxValue = firstStep?.totalValue || 0

    this.steps.forEach(s => {
      if (s.totalValue > maxValue) maxValue = s.totalValue
      const drawdown = maxValue > 0 ? (maxValue - s.totalValue) / maxValue : 0
      if (drawdown > maxDrawdown) maxDrawdown = drawdown
    })

    const profitableTrades = this.steps.filter(s => s.action === 'sell' && s.profit > 0).length

    return {
      totalTrades: trades.length,
      buyCount: buys.length,
      sellCount: sells.length,
      winRate: sells.length > 0 ? profitableTrades / sells.length : 0,
      totalReturn: lastStep?.profitPct || 0,
      maxDrawdown: maxDrawdown * 100,
    }
  }
}

export const replayEngine = new StrategyReplayEngine()

/**
 * 从后端 /api/v1/history/daily/{code} 拉取真实历史 K 线，
 * 并按 config.strategy 计算真实技术指标（MA/MACD/RSI/Bollinger），
 * 模拟回放 buy/sell 信号。
 *
 * 失败或数据不足时返回空数组（由调用方决定是否回退到 mock）。
 */
export async function fetchRealReplaySteps(config: ReplayConfig): Promise<ReplayStep[]> {
  if (!config.code) return []
  try {
    const base = (typeof window !== 'undefined' && (window as any).__LH_API_BASE__) || ''
    const days = 365
    const url = `${base}/api/v1/history/daily/${encodeURIComponent(config.code)}?days=${days}`
    const resp = await fetch(url, { headers: { 'Accept': 'application/json' } })
    if (!resp.ok) return []
    const json: any = await resp.json()
    const records: any[] = Array.isArray(json?.history) ? json.history : []
    if (records.length < 30) return []

    // 解析并按日期排序
    const bars = records
      .map((r) => ({
        date: String(r.snapshot_date ?? r.date ?? '').slice(0, 10),
        code: String(r.code ?? config.code),
        name: String(r.name ?? ''),
        open: Number(r.open_price ?? r.price ?? 0),
        high: Number(r.high_price ?? r.price ?? 0),
        low: Number(r.low_price ?? r.price ?? 0),
        close: Number(r.close_price ?? r.price ?? 0),
        volume: Number(r.volume ?? 0),
      }))
      .filter((b) => b.date && b.close > 0)
      .sort((a, b) => a.date.localeCompare(b.date))
    if (bars.length < 30) return []

    // 计算技术指标
    const closes = bars.map((b) => b.close)
    const indicatorsList = bars.map((_, i) => calcIndicators(closes, i, config.strategy))

    // 简单回放逻辑：根据 strategy 信号 buy/sell
    let cash = config.initialCash
    let shares = 0
    let position = 0
    const steps: ReplayStep[] = []
    const buyReasons: Record<string, string> = {
      macd_cross: 'MACD金叉，买入信号',
      ma_cross: '均线多头排列，买入信号',
      rsi_reversal: 'RSI超卖反转，买入信号',
      bollinger: '触及布林下轨，买入信号',
    }
    const sellReasons: Record<string, string> = {
      macd_cross: 'MACD死叉，止盈卖出',
      ma_cross: '均线死叉，止盈卖出',
      rsi_reversal: 'RSI超买卖出',
      bollinger: '触及布林上轨，止盈卖出',
    }

    bars.forEach((bar, i) => {
      const ind = indicatorsList[i]
      let action: 'buy' | 'sell' | 'hold' = 'hold'
      let reason = ''
      const sig = ind.signal
      if (sig === 'buy' && shares === 0 && cash > bar.close) {
        const buyShares = Math.floor((cash * 0.95) / bar.close / 100) * 100
        if (buyShares > 0) {
          shares = buyShares
          cash -= shares * bar.close
          position = shares * bar.close
          action = 'buy'
          reason = buyReasons[config.strategy] || '买入信号'
        }
      } else if (sig === 'sell' && shares > 0) {
        const sellShares = Math.floor(shares * 0.5)
        cash += sellShares * bar.close
        shares -= sellShares
        position = shares * bar.close
        action = 'sell'
        reason = sellReasons[config.strategy] || '卖出信号'
      }
      const totalValue = cash + position
      const profit = totalValue - config.initialCash
      const profitPct = (profit / config.initialCash) * 100
      steps.push({
        step: i,
        date: bar.date,
        action,
        code: bar.code,
        name: bar.name || config.code,
        price: bar.close,
        shares,
        cash: Math.round(cash * 100) / 100,
        position: Math.round(position * 100) / 100,
        totalValue: Math.round(totalValue * 100) / 100,
        profit: Math.round(profit * 100) / 100,
        profitPct: Math.round(profitPct * 100) / 100,
        reason,
        indicators: {
          MA5: ind.MA5,
          MA10: ind.MA10,
          MACD: ind.MACD,
          RSI: ind.RSI,
        },
      })
    })
    return steps
  } catch {
    return []
  }
}

function calcIndicators(closes: number[], idx: number, strategy: string): {
  signal: 'buy' | 'sell' | 'hold'
  MA5: number; MA10: number; MACD: number; RSI: number
} {
  const last = idx
  const ma = (n: number) => {
    if (last < n - 1) return 0
    let s = 0
    for (let i = last - n + 1; i <= last; i++) s += closes[i]
    return s / n
  }
  const MA5 = ma(5)
  const MA10 = ma(10)

  // MACD = EMA12 - EMA26（近似）
  let ema12 = 0, ema26 = 0
  if (last >= 25) {
    ema12 = closes[0]
    ema26 = closes[0]
    for (let i = 1; i <= last; i++) {
      ema12 = closes[i] * (2 / 13) + ema12 * (11 / 13)
      ema26 = closes[i] * (2 / 27) + ema26 * (25 / 27)
    }
  }
  const MACD = ema12 - ema26

  // RSI 14
  let rsi = 50
  if (last >= 14) {
    let gain = 0, loss = 0
    for (let i = last - 13; i <= last; i++) {
      const diff = closes[i] - closes[i - 1]
      if (diff > 0) gain += diff
      else loss -= diff
    }
    const avgGain = gain / 14
    const avgLoss = loss / 14
    rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }

  // 信号判定
  let signal: 'buy' | 'sell' | 'hold' = 'hold'
  if (strategy === 'ma_cross') {
    if (MA5 > 0 && MA10 > 0 && MA5 > MA10) signal = 'buy'
    else if (MA5 > 0 && MA10 > 0 && MA5 < MA10) signal = 'sell'
  } else if (strategy === 'macd_cross') {
    if (MACD > 0) signal = 'buy'
    else if (MACD < 0) signal = 'sell'
  } else if (strategy === 'rsi_reversal') {
    if (rsi < 30) signal = 'buy'
    else if (rsi > 70) signal = 'sell'
  } else if (strategy === 'bollinger') {
    if (closes[last] < MA10 * 0.98) signal = 'buy'
    else if (closes[last] > MA10 * 1.02) signal = 'sell'
  }
  return { signal, MA5, MA10, MACD, RSI: rsi }
}

// 模拟生成回放数据（仅作 API 失败时的兜底）
export function generateMockReplayData(config: ReplayConfig): ReplayStep[] {
  const steps: ReplayStep[] = []
  let cash = config.initialCash
  let position = 0
  let shares = 0

  const startDate = new Date(config.startDate)
  const endDate = new Date(config.endDate)
  const currentDate = new Date(startDate)

  let step = 0

  // 策略信号理由映射
  const strategySignals: Record<string, { buy: string[]; sell: string[] }> = {
    macd_cross: {
      buy: ['MACD金叉，买入信号'],
      sell: ['MACD死叉，止盈卖出'],
    },
    ma_cross: {
      buy: ['均线多头排列，买入信号'],
      sell: ['均线死叉，止盈卖出'],
    },
    rsi_reversal: {
      buy: ['RSI超卖反转，买入信号'],
      sell: ['RSI超买反转，止盈卖出'],
    },
    bollinger: {
      buy: ['触及布林带下轨，买入信号'],
      sell: ['触及布林带上轨，止盈卖出'],
    },
    xuanji_twelve_factor: {
      buy: [
        '十二因子综合评分进入前20，买入',
        'ICIR动态加权得分排名前20，买入',
        '行业中性分层后评分提升，买入',
        '波动率管理信号触发，买入',
      ],
      sell: [
        '十二因子评分跌出前40，止盈卖出',
        '追踪止损触发(-5%)，卖出',
        '一票否决制触发，风险卖出',
        '缓冲带观察期满，轮换卖出',
      ],
    },
    xibu_seven_dimension: {
      buy: [
        '七维打分进入前15，买入',
        '正股维度评分提升，买入',
        '转债自身评分进入前20，买入',
        '市场环境牛市，动态加仓',
      ],
      sell: [
        '七维打分跌出前30，止盈卖出',
        '一票否决触发(信用不达标)，卖出',
        '缓冲带机制轮换，卖出',
        '市场环境转熊，动态减仓',
      ],
    },
    fusion_strategy: {
      buy: [
        '璇玑×西部共识最强，交集买入',
        '双策略同时入选前20，买入',
        '西部风控通过+璇玑高分，买入',
        '共识增强信号，加仓',
      ],
      sell: [
        '共识减弱，跌出交集，卖出',
        '璇玑或西部任一策略退出，卖出',
        '追踪止损触发，融合卖出',
        '缓冲带轮换期满，卖出',
      ],
    },
  }

  const signals = strategySignals[config.strategy] || strategySignals.macd_cross

  while (currentDate <= endDate) {
    const price = 100 + Math.random() * 50
    const action: 'buy' | 'sell' | 'hold' = Math.random() > 0.8 ? (Math.random() > 0.5 ? 'buy' : 'sell') : 'hold'

    if (action === 'buy' && cash >= price * 10) {
      const buyShares = Math.floor(cash * 0.3 / price)
      shares += buyShares
      cash -= buyShares * price
      position = shares * price
      // buyPrice tracked locally
    } else if (action === 'sell' && shares > 0) {
      const sellShares = Math.floor(shares * 0.5)
      cash += sellShares * price
      shares -= sellShares
      position = shares * price
    }

    const totalValue = cash + position
    const profit = totalValue - config.initialCash
    const profitPct = (profit / config.initialCash) * 100

    const buyReason = signals.buy[Math.floor(Math.random() * signals.buy.length)]
    const sellReason = signals.sell[Math.floor(Math.random() * signals.sell.length)]

    steps.push({
      step: step++,
      date: currentDate.toISOString().slice(0, 10),
      action,
      code: '110001',
      name: '示例转债',
      price,
      shares,
      cash: Math.round(cash * 100) / 100,
      position: Math.round(position * 100) / 100,
      totalValue: Math.round(totalValue * 100) / 100,
      profit: Math.round(profit * 100) / 100,
      profitPct: Math.round(profitPct * 100) / 100,
      reason: action === 'buy' ? buyReason : action === 'sell' ? sellReason : '',
      indicators: {
        MA5: price * (0.98 + Math.random() * 0.04),
        MA10: price * (0.95 + Math.random() * 0.1),
        MACD: Math.random() * 2 - 1,
        RSI: Math.random() * 100,
      },
    })

    currentDate.setDate(currentDate.getDate() + 1)
  }

  return steps
}

export default replayEngine
