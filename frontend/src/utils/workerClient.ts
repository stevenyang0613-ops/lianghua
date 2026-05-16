/**
 * WebWorker 客户端封装
 * 提供友好的 API 来调用后台计算
 */

// Worker 单例
let workerInstance: Worker | null = null
const pendingRequests = new Map<string, {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timeout: ReturnType<typeof setTimeout>
}>()

// 生成唯一 ID
let requestId = 0
function generateId(): string {
  return `req_${++requestId}_${Date.now()}`
}

// 获取 Worker 实例
function getWorker(): Worker {
  if (!workerInstance) {
    workerInstance = new Worker(
      new URL('../workers/dataProcessor.worker.ts', import.meta.url),
      { type: 'module' }
    )
    workerInstance.onmessage = handleWorkerMessage
    workerInstance.onerror = handleWorkerError
  }
  return workerInstance
}

// 处理 Worker 消息
function handleWorkerMessage(event: MessageEvent): void {
  const { type: _type, id, result, error } = event.data
  
  const pending = pendingRequests.get(id)
  if (!pending) return
  
  pendingRequests.delete(id)
  clearTimeout(pending.timeout)
  
  if (error) {
    pending.reject(new Error(error))
  } else {
    pending.resolve(result)
  }
}

// 处理 Worker 错误
function handleWorkerError(error: ErrorEvent): void {
  console.error('[WorkerClient] Worker error:', error)
}

// 默认超时时间（30秒）
const DEFAULT_TIMEOUT = 30000

/**
 * 发送计算请求到 Worker
 */
function sendRequest<T>(
  type: string,
  payload: unknown,
  timeout = DEFAULT_TIMEOUT
): Promise<T> {
  return new Promise((resolve, reject) => {
    const id = generateId()
    const worker = getWorker()
    
    // 设置超时
    const timeoutId = setTimeout(() => {
      pendingRequests.delete(id)
      reject(new Error(`Worker request timeout: ${type}`))
    }, timeout)
    
    // 保存请求
    pendingRequests.set(id, {
      resolve: resolve as (value: unknown) => void,
      reject,
      timeout: timeoutId,
    })
    
    // 发送消息
    worker.postMessage({ type, payload, id })
  })
}

/**
 * 计算移动平均线
 */
export async function calculateMA(data: number[], period: number): Promise<(number | null)[]> {
  return sendRequest<(number | null)[]>('calculateMA', { data, period })
}

/**
 * 计算 RSI
 */
export async function calculateRSI(data: number[], period = 14): Promise<(number | null)[]> {
  return sendRequest<(number | null)[]>('calculateRSI', { data, period })
}

/**
 * 计算 MACD
 */
export async function calculateMACD(
  data: number[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9
): Promise<{
  macd: (number | null)[]
  signal: (number | null)[]
  histogram: (number | null)[]
}> {
  return sendRequest('calculateMACD', { data, fastPeriod, slowPeriod, signalPeriod })
}

/**
 * 计算布林带
 */
export async function calculateBollinger(
  data: number[],
  period = 20,
  stdDev = 2
): Promise<{
  upper: (number | null)[]
  middle: (number | null)[]
  lower: (number | null)[]
}> {
  return sendRequest('calculateBollinger', { data, period, stdDev })
}

/**
 * K线数据聚合
 */
export async function aggregateKline(
  data: Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }>,
  targetCount: number
): Promise<Array<{ date: string; open: number; close: number; high: number; low: number; volume: number }>> {
  return sendRequest('aggregateKline', { data, targetCount })
}

/**
 * 债券数据过滤
 */
export async function filterBonds(
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
): Promise<Array<Record<string, unknown>>> {
  return sendRequest('filterBonds', { bonds, filters })
}

/**
 * 批量计算技术指标
 */
export async function calculateIndicators(
  data: number[],
  indicators: {
    ma?: number[]
    ema?: number[]
    rsi?: number
    macd?: { fast: number; slow: number; signal: number }
    bollinger?: { period: number; stdDev: number }
  }
): Promise<{
  ma: Map<number, (number | null)[]>
  ema: Map<number, number[]>
  rsi: (number | null)[] | null
  macd: { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] } | null
  bollinger: { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } | null
}> {
  const result = {
    ma: new Map<number, (number | null)[]>(),
    ema: new Map<number, number[]>(),
    rsi: null as (number | null)[] | null,
    macd: null as { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] } | null,
    bollinger: null as { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } | null,
  }
  
  // 并行计算所有指标
  const promises: Promise<void>[] = []
  
  if (indicators.ma) {
    for (const period of indicators.ma) {
      promises.push(
        calculateMA(data, period).then(values => {
          result.ma.set(period, values)
        })
      )
    }
  }
  
  if (indicators.rsi) {
    promises.push(
      calculateRSI(data, indicators.rsi).then(values => {
        result.rsi = values
      })
    )
  }
  
  if (indicators.macd) {
    promises.push(
      calculateMACD(data, indicators.macd.fast, indicators.macd.slow, indicators.macd.signal).then(values => {
        result.macd = values
      })
    )
  }
  
  if (indicators.bollinger) {
    promises.push(
      calculateBollinger(data, indicators.bollinger.period, indicators.bollinger.stdDev).then(values => {
        result.bollinger = values
      })
    )
  }
  
  await Promise.all(promises)
  return result
}

/**
 * 销毁 Worker
 */
export function terminateWorker(): void {
  if (workerInstance) {
    workerInstance.terminate()
    workerInstance = null
  }
  pendingRequests.clear()
}

/**
 * 获取 Worker 状态
 */
export function getWorkerStatus(): {
  ready: boolean
  pendingCount: number
} {
  return {
    ready: workerInstance !== null,
    pendingCount: pendingRequests.size,
  }
}

export default {
  calculateMA,
  calculateRSI,
  calculateMACD,
  calculateBollinger,
  aggregateKline,
  filterBonds,
  calculateIndicators,
  terminateWorker,
  getWorkerStatus,
}
