/**
 * WebWorker 数据处理器
 * 在后台线程执行复杂计算
 */

// 消息类型定义
interface WorkerMessage {
  type: 'calculateMA' | 'calculateRSI' | 'calculateMACD' | 'calculateBollinger' | 'aggregateKline' | 'filterBonds'
  payload: unknown
  id: string
}

interface WorkerResponse {
  type: string
  id: string
  result?: unknown
  error?: string
}

// 计算移动平均线
function calculateMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []

  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else {
      let sum = 0
      for (let j = i - period + 1; j <= i; j++) {
        sum += data[j]
      }
      result.push(+(sum / period).toFixed(4))
    }
  }

  return result
}

// 计算 EMA（指数移动平均）
function calculateEMA(data: number[], period: number): number[] {
  const result: number[] = []
  const multiplier = 2 / (period + 1)

  // 第一个 EMA 值使用 SMA
  let sum = 0
  for (let i = 0; i < period; i++) {
    sum += data[i]
  }
  result.push(sum / period)

  // 后续使用 EMA 公式
  for (let i = period; i < data.length; i++) {
    const ema = (data[i] - result[result.length - 1]) * multiplier + result[result.length - 1]
    result.push(ema)
  }

  // 补齐前面的值
  const padding = new Array(period - 1).fill(null)
  return [...padding, ...result] as number[]
}

// 计算 RSI
function calculateRSI(data: number[], period: number = 14): (number | null)[] {
  const result: (number | null)[] = []
  const gains: number[] = []
  const losses: number[] = []

  // 计算价格变化
  for (let i = 1; i < data.length; i++) {
    const change = data[i] - data[i - 1]
    gains.push(change > 0 ? change : 0)
    losses.push(change < 0 ? Math.abs(change) : 0)
  }

  // 计算初始平均
  let avgGain = 0
  let avgLoss = 0
  for (let i = 0; i < period; i++) {
    avgGain += gains[i]
    avgLoss += losses[i]
  }
  avgGain /= period
  avgLoss /= period

  // 填充前面的 null
  for (let i = 0; i < period; i++) {
    result.push(null)
  }

  // 计算第一个 RSI
  if (avgLoss === 0) {
    result.push(100)
  } else {
    const rs = avgGain / avgLoss
    result.push(100 - 100 / (1 + rs))
  }

  // 计算后续 RSI
  for (let i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period

    if (avgLoss === 0) {
      result.push(100)
    } else {
      const rs = avgGain / avgLoss
      result.push(100 - 100 / (1 + rs))
    }
  }

  return result
}

// 计算 MACD
function calculateMACD(data: number[], fastPeriod = 12, slowPeriod = 26, signalPeriod = 9): {
  macd: (number | null)[]
  signal: (number | null)[]
  histogram: (number | null)[]
} {
  const fastEMA = calculateEMA(data, fastPeriod)
  const slowEMA = calculateEMA(data, slowPeriod)

  // MACD 线
  const macd: (number | null)[] = []
  for (let i = 0; i < data.length; i++) {
    if (fastEMA[i] === null || slowEMA[i] === null) {
      macd.push(null)
    } else {
      macd.push((fastEMA[i] as number) - (slowEMA[i] as number))
    }
  }

  // 信号线
  const validMacd = macd.filter(v => v !== null) as number[]
  const signalEMA = calculateEMA(validMacd, signalPeriod)

  const signal: (number | null)[] = []
  let validIndex = 0
  for (let i = 0; i < macd.length; i++) {
    if (macd[i] === null) {
      signal.push(null)
    } else {
      signal.push(signalEMA[validIndex] || null)
      validIndex++
    }
  }

  // 柱状图
  const histogram: (number | null)[] = []
  for (let i = 0; i < macd.length; i++) {
    if (macd[i] === null || signal[i] === null) {
      histogram.push(null)
    } else {
      histogram.push((macd[i] as number) - (signal[i] as number))
    }
  }

  return { macd, signal, histogram }
}

// 计算布林带
function calculateBollinger(data: number[], period = 20, stdDev = 2): {
  upper: (number | null)[]
  middle: (number | null)[]
  lower: (number | null)[]
} {
  const middle = calculateMA(data, period)
  const upper: (number | null)[] = []
  const lower: (number | null)[] = []

  for (let i = 0; i < data.length; i++) {
    if (middle[i] === null) {
      upper.push(null)
      lower.push(null)
    } else {
      // 计算标准差
      let sum = 0
      for (let j = i - period + 1; j <= i; j++) {
        sum += Math.pow(data[j] - (middle[i] as number), 2)
      }
      const std = Math.sqrt(sum / period)

      upper.push((middle[i] as number) + stdDev * std)
      lower.push((middle[i] as number) - stdDev * std)
    }
  }

  return { upper, middle, lower }
}

// K线数据聚合
function aggregateKline(
  data: Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }>,
  targetCount: number
): Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }> {
  if (data.length <= targetCount) return data

  const groupSize = Math.ceil(data.length / targetCount)
  const result: Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }> = []

  for (let i = 0; i < data.length; i += groupSize) {
    const group = data.slice(i, i + groupSize)
    if (group.length > 0) {
      result.push({
        date: group[0].date,
        open: group[0].open,
        close: group[group.length - 1].close,
        high: Math.max(...group.map(d => d.high)),
        low: Math.min(...group.map(d => d.low)),
        volume: group.reduce((sum, d) => sum + d.volume, 0),
      })
    }
  }

  return result
}

// 债券数据过滤和排序
function filterBonds(
  bonds: Array<Record<string, unknown>>,
  filters: {
    minPrice?: number
    maxPrice?: number
    minYtm?: number
    maxYtm?: number
    minVolume?: number
    sortBy?: string
    sortOrder?: 'asc' | 'desc'
  }
): Array<Record<string, unknown>> {
  let result = [...bonds]

  // 应用过滤器
  if (filters.minPrice !== undefined) {
    result = result.filter(b => (b.price as number) >= filters.minPrice!)
  }
  if (filters.maxPrice !== undefined) {
    result = result.filter(b => (b.price as number) <= filters.maxPrice!)
  }
  if (filters.minYtm !== undefined) {
    result = result.filter(b => (b.ytm as number) >= filters.minYtm!)
  }
  if (filters.maxYtm !== undefined) {
    result = result.filter(b => (b.ytm as number) <= filters.maxYtm!)
  }
  if (filters.minVolume !== undefined) {
    result = result.filter(b => (b.volume as number) >= filters.minVolume!)
  }

  // 排序
  if (filters.sortBy) {
    result.sort((a, b) => {
      const aVal = a[filters.sortBy!]
      const bVal = b[filters.sortBy!]
      const comparison = (aVal as number) - (bVal as number)
      return filters.sortOrder === 'desc' ? -comparison : comparison
    })
  }

  return result
}

// 消息处理
self.onmessage = (event: MessageEvent<WorkerMessage>) => {
  const { type, payload, id } = event.data

  try {
    let result: unknown

    switch (type) {
      case 'calculateMA': {
        const { data, period } = payload as { data: number[]; period: number }
        result = calculateMA(data, period)
        break
      }
      case 'calculateRSI': {
        const { data, period } = payload as { data: number[]; period: number }
        result = calculateRSI(data, period)
        break
      }
      case 'calculateMACD': {
        const { data, fastPeriod, slowPeriod, signalPeriod } = payload as {
          data: number[]
          fastPeriod?: number
          slowPeriod?: number
          signalPeriod?: number
        }
        result = calculateMACD(data, fastPeriod, slowPeriod, signalPeriod)
        break
      }
      case 'calculateBollinger': {
        const { data, period, stdDev } = payload as {
          data: number[]
          period?: number
          stdDev?: number
        }
        result = calculateBollinger(data, period, stdDev)
        break
      }
      case 'aggregateKline': {
        const { data, targetCount } = payload as {
          data: Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }>
          targetCount: number
        }
        result = aggregateKline(data, targetCount)
        break
      }
      case 'filterBonds': {
        const { bonds, filters } = payload as {
          bonds: Array<Record<string, unknown>>
          filters: Record<string, unknown>
        }
        result = filterBonds(bonds, filters)
        break
      }
      default:
        throw new Error(`Unknown message type: ${type}`)
    }

    const response: WorkerResponse = { type, id, result }
    self.postMessage(response)
  } catch (error) {
    const response: WorkerResponse = { type, id, error: String(error) }
    self.postMessage(response)
  }
}

export {}
