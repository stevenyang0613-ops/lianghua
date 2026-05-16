/**
 * 性能分析埋点
 * 自动追踪关键操作耗时，生成性能报告
 */

import { useEffect } from 'react'

interface PerformanceMetric {
  name: string
  startTime: number
  endTime: number
  duration: number
  metadata?: Record<string, unknown>
}

interface PerformanceReport {
  metrics: PerformanceMetric[]
  summary: {
    totalOperations: number
    averageDuration: number
    slowestOperations: PerformanceMetric[]
    fastestOperations: PerformanceMetric[]
  }
  timestamp: number
}

class PerformanceTracker {
  private metrics: PerformanceMetric[] = []
  private activeTimers: Map<string, number> = new Map()
  private enabled: boolean = true
  private slowThreshold: number = 1000 // 慢操作阈值（毫秒）
  private maxMetrics: number = 1000

  /**
   * 开始计时
   */
  start(name: string): void {
    if (!this.enabled) return
    this.activeTimers.set(name, performance.now())
  }

  /**
   * 结束计时
   */
  end(name: string, metadata?: Record<string, unknown>): number | null {
    if (!this.enabled) return null

    const startTime = this.activeTimers.get(name)
    if (!startTime) {
      console.warn(`[Performance] No start time for: ${name}`)
      return null
    }

    this.activeTimers.delete(name)
    const endTime = performance.now()
    const duration = endTime - startTime

    const metric: PerformanceMetric = {
      name,
      startTime,
      endTime,
      duration,
      metadata,
    }

    this.addMetric(metric)

    // 慢操作警告
    if (duration > this.slowThreshold) {
      console.warn(`[Performance] Slow operation: ${name} took ${duration.toFixed(2)}ms`, metadata)
    }

    return duration
  }

  /**
   * 添加指标
   */
  private addMetric(metric: PerformanceMetric): void {
    if (this.metrics.length >= this.maxMetrics) {
      this.metrics.shift()
    }
    this.metrics.push(metric)
  }

  /**
   * 测量异步函数
   */
  async measure<T>(name: string, fn: () => Promise<T>, metadata?: Record<string, unknown>): Promise<T> {
    this.start(name)
    try {
      const result = await fn()
      this.end(name, metadata)
      return result
    } catch (error) {
      this.end(name, { ...metadata, error: String(error) })
      throw error
    }
  }

  /**
   * 测量同步函数
   */
  measureSync<T>(name: string, fn: () => T, metadata?: Record<string, unknown>): T {
    this.start(name)
    try {
      const result = fn()
      this.end(name, metadata)
      return result
    } catch (error) {
      this.end(name, { ...metadata, error: String(error) })
      throw error
    }
  }

  /**
   * 获取指标
   */
  getMetrics(filter?: (m: PerformanceMetric) => boolean): PerformanceMetric[] {
    if (filter) {
      return this.metrics.filter(filter)
    }
    return [...this.metrics]
  }

  /**
   * 获取按名称分组的统计
   */
  getStatsByName(): Map<string, {
    count: number
    totalDuration: number
    averageDuration: number
    minDuration: number
    maxDuration: number
  }> {
    const stats = new Map<string, {
      count: number
      totalDuration: number
      averageDuration: number
      minDuration: number
      maxDuration: number
    }>()

    for (const metric of this.metrics) {
      const existing = stats.get(metric.name) || {
        count: 0,
        totalDuration: 0,
        averageDuration: 0,
        minDuration: Infinity,
        maxDuration: 0,
      }

      existing.count++
      existing.totalDuration += metric.duration
      existing.minDuration = Math.min(existing.minDuration, metric.duration)
      existing.maxDuration = Math.max(existing.maxDuration, metric.duration)

      stats.set(metric.name, existing)
    }

    // 计算平均值
    for (const [name, stat] of stats) {
      stats.set(name, {
        ...stat,
        averageDuration: stat.totalDuration / stat.count,
      })
    }

    return stats
  }

  /**
   * 生成报告
   */
  generateReport(): PerformanceReport {
    const sortedByDuration = [...this.metrics].sort((a, b) => b.duration - a.duration)

    return {
      metrics: this.metrics,
      summary: {
        totalOperations: this.metrics.length,
        averageDuration: this.metrics.length > 0
          ? this.metrics.reduce((sum, m) => sum + m.duration, 0) / this.metrics.length
          : 0,
        slowestOperations: sortedByDuration.slice(0, 10),
        fastestOperations: sortedByDuration.slice(-10).reverse(),
      },
      timestamp: Date.now(),
    }
  }

  /**
   * 清除所有指标
   */
  clear(): void {
    this.metrics = []
    this.activeTimers.clear()
  }

  /**
   * 启用/禁用
   */
  setEnabled(enabled: boolean): void {
    this.enabled = enabled
  }

  /**
   * 设置慢操作阈值
   */
  setSlowThreshold(threshold: number): void {
    this.slowThreshold = threshold
  }
}

// 导出单例
export const performanceTracker = new PerformanceTracker()

/**
 * React Hook: 测量组件渲染性能
 */
export function usePerformanceTracking(componentName: string) {
  useEffect(() => {
    performanceTracker.start(`render:${componentName}`)

    return () => {
      performanceTracker.end(`render:${componentName}`)
    }
  }, [componentName])
}

/**
 * 装饰器：测量方法性能
 */
export function trackPerformance(name?: string) {
  return function (
    _target: unknown,
    propertyKey: string,
    descriptor: PropertyDescriptor
  ) {
    const originalMethod = descriptor.value
    const metricName = name || `${String(propertyKey)}`

    descriptor.value = function (...args: unknown[]) {
      const result = originalMethod.apply(this, args)

      if (result instanceof Promise) {
        return performanceTracker.measure(metricName, () => result)
      } else {
        return performanceTracker.measureSync(metricName, () => result)
      }
    }

    return descriptor
  }
}

/**
 * Fetch 包装：测量网络请求性能
 */
export function trackFetch(url: string, options?: RequestInit): Promise<Response> {
  const metricName = `fetch:${url.split('?')[0].split('/').pop() || url}`
  return performanceTracker.measure(metricName, () => fetch(url, options), {
    url,
    method: options?.method || 'GET',
  })
}

/**
 * 自动追踪页面加载性能
 */
export function trackPageLoad(pageName: string): void {
  // 使用 Performance API
  if (typeof performance !== 'undefined' && performance.timing) {
    const timing = performance.timing
    const loadTime = timing.loadEventEnd - timing.navigationStart
    const domReady = timing.domContentLoadedEventEnd - timing.navigationStart
    const firstPaint = timing.responseStart - timing.navigationStart

    performanceTracker.start(`pageLoad:${pageName}`)
    performanceTracker.end(`pageLoad:${pageName}`, {
      loadTime,
      domReady,
      firstPaint,
    })
  }
}

/**
 * 追踪首次内容绘制 (FCP)
 */
export function trackFCP(): void {
  if (typeof PerformanceObserver !== 'undefined') {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.name === 'first-contentful-paint') {
            performanceTracker.start('FCP')
            performanceTracker.end('FCP', { value: entry.startTime })
          }
        }
      })
      observer.observe({ type: 'paint', buffered: true })
    } catch (e) {
      // 不支持
    }
  }
}

/**
 * 追踪最大内容绘制 (LCP)
 */
export function trackLCP(): void {
  if (typeof PerformanceObserver !== 'undefined') {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          performanceTracker.start('LCP')
          performanceTracker.end('LCP', { value: entry.startTime })
        }
      })
      observer.observe({ type: 'largest-contentful-paint', buffered: true })
    } catch (e) {
      // 不支持
    }
  }
}

export default performanceTracker
