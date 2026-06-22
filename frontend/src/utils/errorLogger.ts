/**
 * 错误日志记录服务
 * 支持本地存储和远程上报
 */

import { safeJsonParse } from './safeJson'

export interface ErrorLog {
  type: 'javascript' | 'react' | 'api' | 'network' | 'unknown'
  message: string
  stack?: string
  componentStack?: string
  timestamp: number
  url: string
  userAgent: string
  metadata?: Record<string, unknown>
}

const ERROR_LOG_KEY = 'error_logs'
const MAX_LOGS = 200

// In-memory buffer + debounced flush to avoid localStorage hammering
let _pendingLogs: ErrorLog[] = []
let _flushTimer: ReturnType<typeof setTimeout> | null = null
const FLUSH_DELAY = 500

function _flushLogs(): void {
  if (_flushTimer) {
    clearTimeout(_flushTimer)
    _flushTimer = null
  }
  if (_pendingLogs.length === 0) return
  const stored = getErrorLogs()
  const merged = stored.concat(_pendingLogs)
  if (merged.length > MAX_LOGS) {
    merged.splice(0, merged.length - MAX_LOGS)
  }
  try {
    localStorage.setItem(ERROR_LOG_KEY, JSON.stringify(merged))
  } catch (e) {
    // QuotaExceeded or other localStorage error — best-effort
    console.warn('[ErrorLogger] localStorage write failed:', e)
  }
  _pendingLogs = []
}

function _scheduleFlush(): void {
  if (_flushTimer) return
  _flushTimer = setTimeout(_flushLogs, FLUSH_DELAY)
}

// Ensure logs are flushed on page unload
window.addEventListener('beforeunload', _flushLogs)

// 记录错误
export function logError(error: Partial<ErrorLog>): void {
  const fullError: ErrorLog = {
    type: error.type || 'unknown',
    message: error.message || 'Unknown error',
    stack: error.stack,
    componentStack: error.componentStack,
    timestamp: error.timestamp || Date.now(),
    url: error.url || window.location.href,
    userAgent: error.userAgent || navigator.userAgent,
    metadata: error.metadata,
  }

  _pendingLogs.push(fullError)

  // 限制内存缓冲区数量
  if (_pendingLogs.length > MAX_LOGS) {
    _pendingLogs.splice(0, _pendingLogs.length - MAX_LOGS)
  }

  _scheduleFlush()

  // 同时输出到控制台
  console.error('[ErrorLogger]', fullError)
}

// 获取错误日志
export function getErrorLogs(): ErrorLog[] {
  const saved = localStorage.getItem(ERROR_LOG_KEY)
  return safeJsonParse<ErrorLog[]>(saved, [])
}

// 清除错误日志
export function clearErrorLogs(): void {
  localStorage.removeItem(ERROR_LOG_KEY)
}

// 导出错误日志
export function exportErrorLogs(): string {
  const logs = getErrorLogs()
  return JSON.stringify(logs, null, 2)
}

// 获取错误统计
export function getErrorStats(): {
  total: number
  byType: Record<string, number>
  recentCount: number
  lastErrorTime: number | null
} {
  const logs = getErrorLogs()
  const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000

  const byType: Record<string, number> = {}
  let lastErrorTime: number | null = null

  logs.forEach(log => {
    byType[log.type] = (byType[log.type] || 0) + 1
    if (!lastErrorTime || log.timestamp > lastErrorTime) {
      lastErrorTime = log.timestamp
    }
  })

  return {
    total: logs.length,
    byType,
    recentCount: logs.filter(l => l.timestamp > oneDayAgo).length,
    lastErrorTime,
  }
}

// 全局错误监听
export function setupGlobalErrorHandler(): void {
  // JavaScript 错误
  window.addEventListener('error', (event) => {
    logError({
      type: 'javascript',
      message: event.message,
      stack: event.error?.stack,
      timestamp: Date.now(),
      metadata: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      },
    })
    // 阻止错误继续传播，避免触发全局页面崩溃
    event.preventDefault()
  })

  // Promise 未捕获错误
  window.addEventListener('unhandledrejection', (event) => {
    const error = event.reason
    logError({
      type: 'javascript',
      message: error?.message || String(error),
      stack: error?.stack,
      timestamp: Date.now(),
      metadata: {
        type: 'unhandledrejection',
      },
    })
    // 阻止未处理的 Promise rejection 继续传播，避免连锁崩溃
    event.preventDefault()
  })

  // 资源加载错误
  window.addEventListener('error', (event) => {
    if (event.target !== window) {
      const target = event.target as HTMLElement
      logError({
        type: 'network',
        message: `Resource load failed: ${target.tagName}`,
        timestamp: Date.now(),
        metadata: {
          src: (target as HTMLImageElement).src || (target as HTMLScriptElement).src,
          tagName: target.tagName,
        },
      })
    }
  }, true)
}

// API 错误记录
export function logApiError(
  api: string,
  error: Error,
  request?: Record<string, unknown>
): void {
  logError({
    type: 'api',
    message: `API Error [${api}]: ${error.message}`,
    stack: error.stack,
    timestamp: Date.now(),
    metadata: {
      api,
      request,
    },
  })
}

// 网络错误记录
export function logNetworkError(
  url: string,
  error: Error
): void {
  logError({
    type: 'network',
    message: `Network Error: ${url} - ${error.message}`,
    stack: error.stack,
    timestamp: Date.now(),
    metadata: {
      url,
      online: navigator.onLine,
    },
  })
}

export default {
  logError,
  getErrorLogs,
  clearErrorLogs,
  exportErrorLogs,
  getErrorStats,
  setupGlobalErrorHandler,
  logApiError,
  logNetworkError,
}
