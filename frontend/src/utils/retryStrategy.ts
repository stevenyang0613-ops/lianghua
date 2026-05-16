/**
 * API 请求重试策略
 * 支持指数退避和自定义重试规则
 */

export interface RetryConfig {
  maxRetries: number
  baseDelay: number
  maxDelay: number
  retryableErrors: string[]
  retryableStatusCodes: number[]
  onRetry?: (attempt: number, error: Error) => void
}

const defaultConfig: RetryConfig = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
  retryableErrors: ['ECONNRESET', 'ENOTFOUND', 'ETIMEDOUT', 'ECONNREFUSED'],
  retryableStatusCodes: [408, 429, 500, 502, 503, 504],
}

export class RetryStrategy {
  private config: RetryConfig

  constructor(config?: Partial<RetryConfig>) {
    this.config = { ...defaultConfig, ...config }
  }

  async execute<T>(
    fn: () => Promise<T>,
    isRetryable?: (error: Error) => boolean
  ): Promise<T> {
    let lastError: Error | null = null

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      try {
        return await fn()
      } catch (error) {
        lastError = error as Error

        if (attempt === this.config.maxRetries) {
          throw lastError
        }

        if (!this.shouldRetry(error as Error, isRetryable)) {
          throw error
        }

        const delay = this.calculateDelay(attempt)
        this.config.onRetry?.(attempt + 1, error as Error)

        await this.sleep(delay)
      }
    }

    throw lastError
  }

  private shouldRetry(error: Error, customCheck?: (error: Error) => boolean): boolean {
    // 自定义检查优先
    if (customCheck?.(error)) return true

    // 检查错误码
    const errorCode = (error as any).code
    if (this.config.retryableErrors.includes(errorCode)) {
      return true
    }

    // 检查 HTTP 状态码
    const statusCode = (error as any).status || (error as any).statusCode
    if (this.config.retryableStatusCodes.includes(statusCode)) {
      return true
    }

    // 网络错误
    if (error.message.includes('network') || error.message.includes('Network')) {
      return true
    }

    // 超时错误
    if (error.message.includes('timeout') || error.message.includes('Timeout')) {
      return true
    }

    return false
  }

  private calculateDelay(attempt: number): number {
    // 指数退避 + 随机抖动
    const exponentialDelay = this.config.baseDelay * Math.pow(2, attempt)
    const jitter = Math.random() * 1000
    const delay = Math.min(exponentialDelay + jitter, this.config.maxDelay)

    return delay
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms))
  }

  updateConfig(config: Partial<RetryConfig>): void {
    this.config = { ...this.config, ...config }
  }
}

// 默认重试策略实例
export const retryStrategy = new RetryStrategy()

// 快捷方法
export async function withRetry<T>(
  fn: () => Promise<T>,
  config?: Partial<RetryConfig>
): Promise<T> {
  const strategy = config ? new RetryStrategy(config) : retryStrategy
  return strategy.execute(fn)
}

// 带重试的 fetch 封装
export async function fetchWithRetry(
  url: string,
  options?: RequestInit,
  retryConfig?: Partial<RetryConfig>
): Promise<Response> {
  const strategy = retryConfig ? new RetryStrategy(retryConfig) : retryStrategy

  return strategy.execute(
    async () => {
      const response = await fetch(url, options)

      if (!response.ok && strategy['config'].retryableStatusCodes.includes(response.status)) {
        const error = new Error(`HTTP ${response.status}`) as any
        error.status = response.status
        throw error
      }

      return response
    },
    (error) => {
      const status = (error as any).status
      return strategy['config'].retryableStatusCodes.includes(status)
    }
  )
}

// 重试统计
interface RetryStats {
  totalAttempts: number
  successfulRetries: number
  failedRetries: number
  lastRetryTime: number | null
}

const RETRY_STATS_KEY = 'retry_stats'

export function getRetryStats(): RetryStats {
  const saved = localStorage.getItem(RETRY_STATS_KEY)
  return saved ? JSON.parse(saved) : {
    totalAttempts: 0,
    successfulRetries: 0,
    failedRetries: 0,
    lastRetryTime: null,
  }
}

export function recordRetryAttempt(success: boolean): void {
  const stats = getRetryStats()
  stats.totalAttempts++
  stats.lastRetryTime = Date.now()

  if (success) {
    stats.successfulRetries++
  } else {
    stats.failedRetries++
  }

  localStorage.setItem(RETRY_STATS_KEY, JSON.stringify(stats))
}

export default {
  RetryStrategy,
  retryStrategy,
  withRetry,
  fetchWithRetry,
  getRetryStats,
  recordRetryAttempt,
}
