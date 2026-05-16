/**
 * 内存泄漏检测工具
 * 在开发环境下检测常见的 React 内存泄漏模式
 */

import { useRef, useCallback, useEffect } from 'react'

interface LeakWarning {
  type: 'subscription' | 'timer' | 'event' | 'async' | 'closure'
  component: string
  message: string
  timestamp: number
  stack?: string
}

class MemoryLeakDetector {
  private warnings: LeakWarning[] = []
  private enabled: boolean = import.meta.env.DEV
  private subscriptions: Map<string, Set<string>> = new Map()
  private timers: Map<string, Set<number>> = new Map()
  private eventListeners: Map<string, Set<string>> = new Map()
  private asyncOperations: Map<string, Set<string>> = new Map()

  /**
   * 记录订阅
   */
  trackSubscription(componentId: string, subscriptionId: string): void {
    if (!this.enabled) return

    if (!this.subscriptions.has(componentId)) {
      this.subscriptions.set(componentId, new Set())
    }
    this.subscriptions.get(componentId)!.add(subscriptionId)
  }

  /**
   * 清理订阅记录
   */
  clearSubscription(componentId: string, subscriptionId: string): void {
    const subs = this.subscriptions.get(componentId)
    if (subs) {
      subs.delete(subscriptionId)
      if (subs.size === 0) {
        this.subscriptions.delete(componentId)
      }
    }
  }

  /**
   * 记录定时器
   */
  trackTimer(componentId: string, timerId: number): void {
    if (!this.enabled) return

    if (!this.timers.has(componentId)) {
      this.timers.set(componentId, new Set())
    }
    this.timers.get(componentId)!.add(timerId)
  }

  /**
   * 清理定时器记录
   */
  clearTimer(componentId: string, timerId: number): void {
    const timers = this.timers.get(componentId)
    if (timers) {
      timers.delete(timerId)
      if (timers.size === 0) {
        this.timers.delete(componentId)
      }
    }
  }

  /**
   * 记录事件监听器
   */
  trackEventListener(componentId: string, eventType: string): void {
    if (!this.enabled) return

    if (!this.eventListeners.has(componentId)) {
      this.eventListeners.set(componentId, new Set())
    }
    this.eventListeners.get(componentId)!.add(eventType)
  }

  /**
   * 清理事件监听器记录
   */
  clearEventListener(componentId: string, eventType: string): void {
    const listeners = this.eventListeners.get(componentId)
    if (listeners) {
      listeners.delete(eventType)
      if (listeners.size === 0) {
        this.eventListeners.delete(componentId)
      }
    }
  }

  /**
   * 记录异步操作
   */
  trackAsyncOperation(componentId: string, operationId: string): void {
    if (!this.enabled) return

    if (!this.asyncOperations.has(componentId)) {
      this.asyncOperations.set(componentId, new Set())
    }
    this.asyncOperations.get(componentId)!.add(operationId)
  }

  /**
   * 清理异步操作记录
   */
  clearAsyncOperation(componentId: string, operationId: string): void {
    const ops = this.asyncOperations.get(componentId)
    if (ops) {
      ops.delete(operationId)
      if (ops.size === 0) {
        this.asyncOperations.delete(componentId)
      }
    }
  }

  /**
   * 组件卸载时检查泄漏
   */
  checkOnUnmount(componentId: string): LeakWarning[] {
    if (!this.enabled) return []

    const warnings: LeakWarning[] = []

    // 检查未清理的订阅
    const subs = this.subscriptions.get(componentId)
    if (subs && subs.size > 0) {
      warnings.push({
        type: 'subscription',
        component: componentId,
        message: `发现 ${subs.size} 个未清理的订阅`,
        timestamp: Date.now(),
      })
    }

    // 检查未清理的定时器
    const timers = this.timers.get(componentId)
    if (timers && timers.size > 0) {
      warnings.push({
        type: 'timer',
        component: componentId,
        message: `发现 ${timers.size} 个未清理的定时器`,
        timestamp: Date.now(),
      })
    }

    // 检查未清理的事件监听器
    const listeners = this.eventListeners.get(componentId)
    if (listeners && listeners.size > 0) {
      warnings.push({
        type: 'event',
        component: componentId,
        message: `发现 ${listeners.size} 个未清理的事件监听器`,
        timestamp: Date.now(),
      })
    }

    // 检查未完成的异步操作
    const ops = this.asyncOperations.get(componentId)
    if (ops && ops.size > 0) {
      warnings.push({
        type: 'async',
        component: componentId,
        message: `发现 ${ops.size} 个未完成的异步操作`,
        timestamp: Date.now(),
      })
    }

    // 记录警告
    this.warnings.push(...warnings)

    // 清理记录
    this.subscriptions.delete(componentId)
    this.timers.delete(componentId)
    this.eventListeners.delete(componentId)
    this.asyncOperations.delete(componentId)

    return warnings
  }

  /**
   * 获取所有警告
   */
  getWarnings(): LeakWarning[] {
    return [...this.warnings]
  }

  /**
   * 清除警告
   */
  clearWarnings(): void {
    this.warnings = []
  }

  /**
   * 获取泄漏摘要
   */
  getSummary(): {
    totalWarnings: number
    byType: Record<string, number>
    byComponent: Record<string, number>
  } {
    const byType: Record<string, number> = {}
    const byComponent: Record<string, number> = {}

    for (const warning of this.warnings) {
      byType[warning.type] = (byType[warning.type] || 0) + 1
      byComponent[warning.component] = (byComponent[warning.component] || 0) + 1
    }

    return {
      totalWarnings: this.warnings.length,
      byType,
      byComponent,
    }
  }

  /**
   * 启用/禁用检测
   */
  setEnabled(enabled: boolean): void {
    this.enabled = enabled
  }
}

export const memoryLeakDetector = new MemoryLeakDetector()

/**
 * React Hook: 自动追踪组件的资源
 */
export function useLeakTracker(componentName: string) {
  const componentId = useRef<string>(`${componentName}_${Date.now()}`)
  const timersRef = useRef<Set<number>>(new Set())
  const subscriptionsRef = useRef<Set<string>>(new Set())

  // 追踪 setTimeout
  const trackedSetTimeout = useCallback((callback: () => void, delay: number): number => {
    const id = window.setTimeout(callback, delay)
    timersRef.current.add(id)
    memoryLeakDetector.trackTimer(componentId.current, id)
    return id
  }, [])

  // 追踪 setInterval
  const trackedSetInterval = useCallback((callback: () => void, delay: number): number => {
    const id = window.setInterval(callback, delay)
    timersRef.current.add(id)
    memoryLeakDetector.trackTimer(componentId.current, id)
    return id
  }, [])

  // 清理定时器
  const trackedClearTimeout = useCallback((id: number): void => {
    window.clearTimeout(id)
    timersRef.current.delete(id)
    memoryLeakDetector.clearTimer(componentId.current, id)
  }, [])

  const trackedClearInterval = useCallback((id: number): void => {
    window.clearInterval(id)
    timersRef.current.delete(id)
    memoryLeakDetector.clearTimer(componentId.current, id)
  }, [])

  // 追踪订阅
  const trackSubscription = useCallback((subId: string): void => {
    subscriptionsRef.current.add(subId)
    memoryLeakDetector.trackSubscription(componentId.current, subId)
  }, [])

  const clearSubscription = useCallback((subId: string): void => {
    subscriptionsRef.current.delete(subId)
    memoryLeakDetector.clearSubscription(componentId.current, subId)
  }, [])

  // 组件卸载时检查
  useEffect(() => {
    return () => {
      const warnings = memoryLeakDetector.checkOnUnmount(componentId.current)
      if (warnings.length > 0) {
        console.warn(`[MemoryLeak] ${componentName} 有潜在内存泄漏:`, warnings)
      }
    }
  }, [componentName])

  return {
    setTimeout: trackedSetTimeout,
    setInterval: trackedSetInterval,
    clearTimeout: trackedClearTimeout,
    clearInterval: trackedClearInterval,
    trackSubscription,
    clearSubscription,
  }
}

export default memoryLeakDetector
