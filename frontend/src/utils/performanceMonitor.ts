/**
 * 性能监控和告警服务
 * 监控API响应时间，超阈值时发送通知
 */

// 告警阈值配置
const DEFAULT_THRESHOLDS = {
  warning: 1000,  // 1秒警告
  critical: 3000, // 3秒严重
}

interface PerformanceRecord {
  api: string
  duration: number
  timestamp: number
  status: 'ok' | 'warning' | 'critical'
}

interface PerformanceConfig {
  warningThreshold: number
  criticalThreshold: number
  enableNotifications: boolean
  notifyOnWarning: boolean
  notifyOnCritical: boolean
}

const CONFIG_KEY = 'perf_config'
const RECORDS_KEY = 'perf_records'

let config: PerformanceConfig = loadConfig()
let records: PerformanceRecord[] = loadRecords()

function loadConfig(): PerformanceConfig {
  const saved = localStorage.getItem(CONFIG_KEY)
  if (saved) {
    try { return JSON.parse(saved) } catch { /* fall through */ }
  }
  return {
    warningThreshold: DEFAULT_THRESHOLDS.warning,
    criticalThreshold: DEFAULT_THRESHOLDS.critical,
    enableNotifications: true,
    notifyOnWarning: false,
    notifyOnCritical: true,
  }
}

function saveConfig(): void {
  localStorage.setItem(CONFIG_KEY, JSON.stringify(config))
}

function loadRecords(): PerformanceRecord[] {
  const saved = localStorage.getItem(RECORDS_KEY)
  if (saved) {
    try { return JSON.parse(saved) } catch { /* fall through */ }
  }
  return []
}

function saveRecords(): void {
  // 只保留最近100条记录
  records = records.slice(-100)
  localStorage.setItem(RECORDS_KEY, JSON.stringify(records))
}

export function getConfig(): PerformanceConfig {
  return { ...config }
}

export function updateConfig(newConfig: Partial<PerformanceConfig>): void {
  config = { ...config, ...newConfig }
  saveConfig()
}

export function getRecords(): PerformanceRecord[] {
  return [...records]
}

export function getStats(): {
  total: number
  avgDuration: number
  maxDuration: number
  warningCount: number
  criticalCount: number
} {
  if (records.length === 0) {
    return { total: 0, avgDuration: 0, maxDuration: 0, warningCount: 0, criticalCount: 0 }
  }

  const total = records.length
  const sum = records.reduce((acc, r) => acc + r.duration, 0)
  const max = Math.max(...records.map(r => r.duration))
  const warningCount = records.filter(r => r.status === 'warning').length
  const criticalCount = records.filter(r => r.status === 'critical').length

  return {
    total,
    avgDuration: Math.round(sum / total),
    maxDuration: max,
    warningCount,
    criticalCount,
  }
}

// 记录API性能
export function recordApiPerformance(api: string, duration: number): PerformanceRecord {
  let status: 'ok' | 'warning' | 'critical' = 'ok'

  if (duration >= config.criticalThreshold) {
    status = 'critical'
  } else if (duration >= config.warningThreshold) {
    status = 'warning'
  }

  const record: PerformanceRecord = {
    api,
    duration,
    timestamp: Date.now(),
    status,
  }

  records.push(record)
  saveRecords()

  // 发送通知
  if (config.enableNotifications) {
    if (status === 'critical' && config.notifyOnCritical) {
      sendNotification('⚠️ API响应严重超时', `${api} 响应时间 ${duration}ms，超过阈值 ${config.criticalThreshold}ms`)
    } else if (status === 'warning' && config.notifyOnWarning) {
      sendNotification('⚡ API响应较慢', `${api} 响应时间 ${duration}ms`)
    }
  }

  return record
}

// 包装API调用以自动记录性能
export async function withPerformanceTracking<T>(api: string, fn: () => Promise<T>): Promise<T> {
  const startTime = Date.now()
  try {
    const result = await fn()
    const duration = Date.now() - startTime
    recordApiPerformance(api, duration)
    return result
  } catch (error) {
    const duration = Date.now() - startTime
    recordApiPerformance(api, duration)
    throw error
  }
}

// 发送通知
async function sendNotification(title: string, body: string): Promise<void> {
  // 尝试使用Electron原生通知
  if (typeof window !== 'undefined' && window.electronAPI?.showNotification) {
    await window.electronAPI.showNotification(title, body)
    return
  }

  // 回退到浏览器通知
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, { body, icon: '/icon.png' })
  }
}

// 清除记录
export function clearRecords(): void {
  records = []
  localStorage.removeItem(RECORDS_KEY)
}

// 导出报告
export function exportReport(): string {
  const stats = getStats()
  const report = {
    generatedAt: new Date().toISOString(),
    config,
    stats,
    recentRecords: records.slice(-20),
  }
  return JSON.stringify(report, null, 2)
}

export default {
  getConfig,
  updateConfig,
  getRecords,
  getStats,
  recordApiPerformance,
  withPerformanceTracking,
  clearRecords,
  exportReport,
}
