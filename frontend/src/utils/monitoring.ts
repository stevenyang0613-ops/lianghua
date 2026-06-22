/**
 * 监控与告警服务
 * 错误追踪、性能监控、用户行为分析
 */

interface ErrorReport {
  type: 'error' | 'warning' | 'info'
  message: string
  stack?: string
  componentStack?: string
  url: string
  userAgent: string
  timestamp: number
  context?: Record<string, unknown>
}

interface PerformanceReport {
  name: string
  duration: number
  timestamp: number
  metadata?: Record<string, unknown>
}

interface UserAction {
  type: string
  target: string
  timestamp: number
  metadata?: Record<string, unknown>
}

class MonitoringService {
  private endpoint: string | null = null
  private enabled: boolean = true
  private errorQueue: ErrorReport[] = []
  private performanceQueue: PerformanceReport[] = []
  private actionQueue: UserAction[] = []
  private flushInterval: ReturnType<typeof setInterval> | null = null
  private maxQueueSize = 50

  /**
   * 初始化监控
   */
  init(options: { endpoint?: string; enabled?: boolean } = {}): void {
    this.endpoint = options.endpoint || null
    this.enabled = options.enabled !== false

    if (!this.enabled) return

    // 启动定时刷新
    this.flushInterval = setInterval(() => {
      this.flush()
    }, 10000)

    // 监听页面关闭
    window.addEventListener('beforeunload', () => {
      this.flush()
    })
  }

  /**
   * 捕获错误
   */
  captureError(error: ErrorReport): void {
    if (!this.enabled) return

    this.errorQueue.push(error)

    if (this.errorQueue.length >= this.maxQueueSize) {
      this.flush()
    }

    // 开发环境输出
    if (import.meta.env.DEV) {
      console.error('[Monitoring]', error)
    }
  }

  /**
   * 捕获性能指标
   */
  capturePerformance(report: PerformanceReport): void {
    if (!this.enabled) return

    this.performanceQueue.push(report)

    if (this.performanceQueue.length >= this.maxQueueSize) {
      this.flush()
    }
  }

  /**
   * 捕获用户行为
   */
  captureAction(action: UserAction): void {
    if (!this.enabled) return

    this.actionQueue.push(action)

    if (this.actionQueue.length >= this.maxQueueSize) {
      this.flush()
    }
  }

  /**
   * 手动上报
   */
  capture(message: string, context?: Record<string, unknown>): void {
    this.captureError({
      type: 'info',
      message,
      url: window.location.href,
      userAgent: navigator.userAgent,
      timestamp: Date.now(),
      context,
    })
  }

  /**
   * 刷新队列
   */
  async flush(): Promise<void> {
    if (!this.endpoint) {
      // 清空队列但不发送
      this.errorQueue = []
      this.performanceQueue = []
      this.actionQueue = []
      return
    }

    const payload = {
      errors: [...this.errorQueue],
      performance: [...this.performanceQueue],
      actions: [...this.actionQueue],
    }

    // 清空队列
    this.errorQueue = []
    this.performanceQueue = []
    this.actionQueue = []

    // 发送数据
    if (payload.errors.length > 0 || payload.performance.length > 0 || payload.actions.length > 0) {
      try {
        await fetch(this.endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          keepalive: true,
        })
      } catch (error) {
        console.error('[Monitoring] Failed to flush:', error)
      }
    }
  }

  /**
   * 设置用户信息
   */
  setUser(userId: string, userInfo?: Record<string, unknown>): void {
    this.captureAction({
      type: 'set_user',
      target: userId,
      timestamp: Date.now(),
      metadata: userInfo,
    })
  }

  /**
   * 设置上下文
   */
  setContext(key: string, value: unknown): void {
    this.captureAction({
      type: 'set_context',
      target: key,
      timestamp: Date.now(),
      metadata: { value },
    })
  }

  /**
   * 获取统计
   */
  getStats(): {
    errorCount: number
    performanceCount: number
    actionCount: number
  } {
    return {
      errorCount: this.errorQueue.length,
      performanceCount: this.performanceQueue.length,
      actionCount: this.actionQueue.length,
    }
  }

  /**
   * 销毁
   */
  destroy(): void {
    if (this.flushInterval) {
      clearInterval(this.flushInterval)
      this.flushInterval = null
    }
    this.flush()
  }
}

// 导出单例
export const monitoring = new MonitoringService()

/**
 * React Hook: 自动追踪组件错误
 */
export function useErrorBoundary() {
  const captureException = (error: Error, errorInfo?: { componentStack?: string }) => {
    monitoring.captureError({
      type: 'error',
      message: error.message,
      stack: error.stack,
      componentStack: errorInfo?.componentStack,
      url: window.location.href,
      userAgent: navigator.userAgent,
      timestamp: Date.now(),
    })
  }

  return { captureException }
}

/**
 * 追踪 Web Vitals
 */
export function trackWebVitals(): void {
  if (typeof PerformanceObserver === 'undefined') return

  // LCP
  try {
    const lcpObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries()
      const lastEntry = entries[entries.length - 1]
      monitoring.capturePerformance({
        name: 'LCP',
        duration: lastEntry.startTime,
        timestamp: Date.now(),
      })
    })
    lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true })
  } catch (e) {
    // 不支持
  }

  // FID
  try {
    const fidObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries()
      entries.forEach((entry) => {
        const eventTiming = entry as unknown as { processingStart?: number }
        const start = eventTiming.processingStart ?? 0
        monitoring.capturePerformance({
          name: 'FID',
          duration: start - entry.startTime,
          timestamp: Date.now(),
        })
      })
    })
    fidObserver.observe({ type: 'first-input', buffered: true })
  } catch (e) {
    // 不支持
  }

  // CLS
  try {
    let clsValue = 0
    const clsObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const lsEntry = entry as unknown as { hadRecentInput?: boolean; value?: number }
        if (!lsEntry.hadRecentInput) {
          clsValue += lsEntry.value ?? 0
        }
      }
      monitoring.capturePerformance({
        name: 'CLS',
        duration: clsValue,
        timestamp: Date.now(),
      })
    })
    clsObserver.observe({ type: 'layout-shift', buffered: true })
  } catch (e) {
    // 不支持
  }
}

export default monitoring

/**
 * 销毁监控服务（清理定时器和监听器）
 */
export function destroyMonitoring(): void {
  monitoring.destroy()
}
