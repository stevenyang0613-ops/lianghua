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

// 模拟生成回放数据
export function generateMockReplayData(config: ReplayConfig): ReplayStep[] {
  const steps: ReplayStep[] = []
  let cash = config.initialCash
  let position = 0
  let shares = 0

  const startDate = new Date(config.startDate)
  const endDate = new Date(config.endDate)
  const currentDate = new Date(startDate)

  let step = 0

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
      reason: action === 'buy' ? 'MACD金叉，买入信号' : action === 'sell' ? '止盈卖出' : '',
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
