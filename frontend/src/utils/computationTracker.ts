/**
 * WebAssembly/OffscreenCanvas 性能监控集成
 * 追踪计算耗时、渲染性能
 */

import { performanceTracker } from './performanceTracking'
import { wasmCalculator } from '../workers/computation.worker'
import { OffscreenRenderer } from './offscreenRenderer'

// 性能指标接口
interface ComputationMetrics {
  operation: string
  inputSize: number
  duration: number
  memoryBefore?: number
  memoryAfter?: number
  success: boolean
  error?: string
}

interface RenderMetrics {
  type: string
  width: number
  height: number
  duration: number
  success: boolean
}

// 性能统计
interface ComputationStats {
  totalOperations: number
  totalDuration: number
  averageDuration: number
  successRate: number
  operationsByType: Map<string, { count: number; totalDuration: number; avgDuration: number }>
  slowOperations: ComputationMetrics[]
}

/**
 * 计算性能追踪器
 */
export class ComputationTracker {
  private metrics: ComputationMetrics[] = []
  private renderMetrics: RenderMetrics[] = []
  private maxMetrics: number = 1000
  private slowThreshold: number = 100 // ms

  /**
   * 追踪 WASM 计算
   */
  async trackWasmOperation<T>(
    operation: string,
    inputSize: number,
    fn: () => Promise<T> | T
  ): Promise<T> {
    const startTime = performance.now()
    const memoryBefore = this.getMemoryUsage()

    try {
      performanceTracker.start(`wasm:${operation}`)
      const result = await fn()
      const duration = performance.now() - startTime
      const memoryAfter = this.getMemoryUsage()

      const metric: ComputationMetrics = {
        operation,
        inputSize,
        duration,
        memoryBefore,
        memoryAfter,
        success: true,
      }

      this.addMetric(metric)
      performanceTracker.end(`wasm:${operation}`, { inputSize, duration })

      if (duration > this.slowThreshold) {
        console.warn(`[ComputationTracker] Slow operation: ${operation} took ${duration.toFixed(2)}ms`)
      }

      return result
    } catch (error) {
      const duration = performance.now() - startTime

      const metric: ComputationMetrics = {
        operation,
        inputSize,
        duration,
        success: false,
        error: String(error),
      }

      this.addMetric(metric)
      performanceTracker.end(`wasm:${operation}`, { inputSize, duration, error: true })

      throw error
    }
  }

  /**
   * 追踪离屏渲染
   */
  trackRender(
    type: string,
    width: number,
    height: number,
    fn: () => void
  ): void {
    const startTime = performance.now()

    try {
      performanceTracker.start(`render:${type}`)
      fn()
      const duration = performance.now() - startTime

      const metric: RenderMetrics = {
        type,
        width,
        height,
        duration,
        success: true,
      }

      this.renderMetrics.push(metric)
      performanceTracker.end(`render:${type}`, { width, height, duration })
    } catch (error) {
      const duration = performance.now() - startTime

      this.renderMetrics.push({
        type,
        width,
        height,
        duration,
        success: false,
      })

      throw error
    }
  }

  /**
   * 追踪数据处理管道
   */
  async trackPipeline<T>(
    pipelineName: string,
    stages: Array<{ name: string; fn: () => Promise<unknown> | unknown }>
  ): Promise<{ result: T; stageMetrics: Array<{ name: string; duration: number }> }> {
    const stageMetrics: Array<{ name: string; duration: number }> = []
    let result: T | undefined

    for (const stage of stages) {
      const startTime = performance.now()
      performanceTracker.start(`pipeline:${pipelineName}:${stage.name}`)

      const stageResult = await stage.fn()
      const duration = performance.now() - startTime

      stageMetrics.push({ name: stage.name, duration })
      performanceTracker.end(`pipeline:${pipelineName}:${stage.name}`)

      result = stageResult as T
    }

    return { result: result!, stageMetrics }
  }

  /**
   * 添加指标
   */
  private addMetric(metric: ComputationMetrics): void {
    if (this.metrics.length >= this.maxMetrics) {
      this.metrics.shift()
    }
    this.metrics.push(metric)
  }

  /**
   * 获取内存使用
   */
  private getMemoryUsage(): number | undefined {
    if ('memory' in performance) {
      return (performance as any).memory.usedJSHeapSize
    }
    return undefined
  }

  /**
   * 获取统计信息
   */
  getStats(): ComputationStats {
    const operationsByType = new Map<string, { count: number; totalDuration: number; avgDuration: number }>()

    let totalDuration = 0
    let successCount = 0

    for (const metric of this.metrics) {
      totalDuration += metric.duration
      if (metric.success) successCount++

      const existing = operationsByType.get(metric.operation) || { count: 0, totalDuration: 0, avgDuration: 0 }
      existing.count++
      existing.totalDuration += metric.duration
      operationsByType.set(metric.operation, existing)
    }

    // 计算平均值
    for (const [key, stats] of operationsByType) {
      stats.avgDuration = stats.totalDuration / stats.count
    }

    // 慢操作
    const slowOperations = this.metrics
      .filter(m => m.duration > this.slowThreshold)
      .sort((a, b) => b.duration - a.duration)
      .slice(0, 20)

    return {
      totalOperations: this.metrics.length,
      totalDuration,
      averageDuration: this.metrics.length > 0 ? totalDuration / this.metrics.length : 0,
      successRate: this.metrics.length > 0 ? (successCount / this.metrics.length) * 100 : 0,
      operationsByType,
      slowOperations,
    }
  }

  /**
   * 获取渲染统计
   */
  getRenderStats(): {
    totalRenders: number
    averageDuration: number
    rendersByType: Map<string, { count: number; avgDuration: number }>
  } {
    const rendersByType = new Map<string, { count: number; totalDuration: number; avgDuration: number }>()

    let totalDuration = 0

    for (const metric of this.renderMetrics) {
      totalDuration += metric.duration

      const existing = rendersByType.get(metric.type) || { count: 0, totalDuration: 0, avgDuration: 0 }
      existing.count++
      existing.totalDuration += metric.duration
      rendersByType.set(metric.type, existing)
    }

    for (const [, stats] of rendersByType) {
      stats.avgDuration = stats.totalDuration / stats.count
    }

    return {
      totalRenders: this.renderMetrics.length,
      averageDuration: this.renderMetrics.length > 0 ? totalDuration / this.renderMetrics.length : 0,
      rendersByType,
    }
  }

  /**
   * 导出报告
   */
  exportReport(): {
    computation: ComputationMetrics[]
    render: RenderMetrics[]
    summary: {
      computation: ComputationStats
      render: ReturnType<ComputationTracker['getRenderStats']>
    }
  } {
    return {
      computation: this.metrics,
      render: this.renderMetrics,
      summary: {
        computation: this.getStats(),
        render: this.getRenderStats(),
      },
    }
  }

  /**
   * 清除
   */
  clear(): void {
    this.metrics = []
    this.renderMetrics = []
  }
}

/**
 * WASM 计算包装器（带性能追踪）
 */
export class TrackedWasmCalculator {
  private tracker: ComputationTracker

  constructor(tracker: ComputationTracker) {
    this.tracker = tracker
  }

  async init(): Promise<void> {
    await wasmCalculator.init()
  }

  async calculateSMA(data: number[], period: number): Promise<number[]> {
    return this.tracker.trackWasmOperation(
      'SMA',
      data.length,
      () => wasmCalculator.calculateSMA(data, period)
    )
  }

  async calculateEMA(data: number[], period: number): Promise<number[]> {
    return this.tracker.trackWasmOperation(
      'EMA',
      data.length,
      () => wasmCalculator.calculateEMA(data, period)
    )
  }

  async calculateRSI(data: number[], period: number): Promise<number[]> {
    return this.tracker.trackWasmOperation(
      'RSI',
      data.length,
      () => wasmCalculator.calculateRSI(data, period)
    )
  }

  calculateMACD(data: number[], fastPeriod?: number, slowPeriod?: number, signalPeriod?: number) {
    return this.tracker.trackWasmOperation(
      'MACD',
      data.length,
      () => wasmCalculator.calculateMACD(data, fastPeriod, slowPeriod, signalPeriod)
    )
  }

  calculateBollingerBands(data: number[], period?: number, stdDev?: number) {
    return this.tracker.trackWasmOperation(
      'BollingerBands',
      data.length,
      () => wasmCalculator.calculateBollingerBands(data, period, stdDev)
    )
  }

  calculateIndicators(data: number[], indicators: string[]) {
    return this.tracker.trackWasmOperation(
      'Indicators',
      data.length,
      () => wasmCalculator.calculateIndicators(data, indicators)
    )
  }
}

/**
 * 追踪离屏渲染器
 */
export class TrackedOffscreenRenderer extends OffscreenRenderer {
  private tracker: ComputationTracker

  constructor(config: ConstructorParameters<typeof OffscreenRenderer>[0], tracker: ComputationTracker) {
    super(config)
    this.tracker = tracker
  }

  renderLineChart(series: Parameters<OffscreenRenderer['renderLineChart']>[0], options?: Parameters<OffscreenRenderer['renderLineChart']>[1]) {
    let result: ReturnType<OffscreenRenderer['renderLineChart']>
    this.tracker.trackRender('lineChart', this.config.width, this.config.height, () => {
      result = super.renderLineChart(series, options)
    })
    return result!
  }

  renderCandleChart(candles: Parameters<OffscreenRenderer['renderCandleChart']>[0], options?: Parameters<OffscreenRenderer['renderCandleChart']>[1]) {
    let result: ReturnType<OffscreenRenderer['renderCandleChart']>
    this.tracker.trackRender('candleChart', this.config.width, this.config.height, () => {
      result = super.renderCandleChart(candles, options)
    })
    return result!
  }

  renderHeatmap(data: Parameters<OffscreenRenderer['renderHeatmap']>[0], options?: Parameters<OffscreenRenderer['renderHeatmap']>[1]) {
    let result: ReturnType<OffscreenRenderer['renderHeatmap']>
    this.tracker.trackRender('heatmap', this.config.width, this.config.height, () => {
      result = super.renderHeatmap(data, options)
    })
    return result!
  }
}

// 导出单例
export const computationTracker = new ComputationTracker()
export const trackedWasmCalculator = new TrackedWasmCalculator(computationTracker)

export default computationTracker
