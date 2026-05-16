/**
 * 交易日志服务
 * 记录所有交易操作便于审计和分析
 */

export interface TradeLog {
  id: string
  timestamp: number
  action: 'buy' | 'sell' | 'cancel' | 'modify' | 'signal' | 'view'
  code: string
  name: string
  price?: number
  quantity?: number
  amount?: number
  status: 'pending' | 'success' | 'failed' | 'cancelled'
  strategy?: string
  signalId?: string
  notes?: string
  metadata?: Record<string, unknown>
}

const TRADE_LOG_KEY = 'trade_logs'
const MAX_LOGS = 1000

// 生成唯一ID
function generateId(): string {
  return `trade_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

// 记录交易
export function logTrade(log: Omit<TradeLog, 'id' | 'timestamp'>): TradeLog {
  const logs = getTradeLogs()

  const fullLog: TradeLog = {
    id: generateId(),
    timestamp: Date.now(),
    ...log,
  }

  logs.push(fullLog)

  // 限制数量
  if (logs.length > MAX_LOGS) {
    logs.splice(0, logs.length - MAX_LOGS)
  }

  localStorage.setItem(TRADE_LOG_KEY, JSON.stringify(logs))

  return fullLog
}

// 获取交易日志
export function getTradeLogs(options?: {
  code?: string
  action?: TradeLog['action']
  status?: TradeLog['status']
  startDate?: number
  endDate?: number
  limit?: number
}): TradeLog[] {
  const saved = localStorage.getItem(TRADE_LOG_KEY)
  let logs: TradeLog[] = saved ? JSON.parse(saved) : []

  if (options) {
    if (options.code) {
      logs = logs.filter(l => l.code === options.code)
    }
    if (options.action) {
      logs = logs.filter(l => l.action === options.action)
    }
    if (options.status) {
      logs = logs.filter(l => l.status === options.status)
    }
    if (options.startDate) {
      logs = logs.filter(l => l.timestamp >= options.startDate!)
    }
    if (options.endDate) {
      logs = logs.filter(l => l.timestamp <= options.endDate!)
    }
    if (options.limit) {
      logs = logs.slice(-options.limit)
    }
  }

  return logs.sort((a, b) => b.timestamp - a.timestamp)
}

// 获取单个日志
export function getTradeLog(id: string): TradeLog | null {
  const logs = getTradeLogs()
  return logs.find(l => l.id === id) || null
}

// 更新日志状态
export function updateTradeLogStatus(id: string, status: TradeLog['status'], notes?: string): TradeLog | null {
  const logs = getTradeLogs()
  const index = logs.findIndex(l => l.id === id)

  if (index === -1) return null

  logs[index].status = status
  if (notes) logs[index].notes = notes

  // 重新排序保存
  const allLogs = [...logs].sort((a, b) => a.timestamp - b.timestamp)
  localStorage.setItem(TRADE_LOG_KEY, JSON.stringify(allLogs))

  return logs[index]
}

// 删除日志
export function deleteTradeLog(id: string): boolean {
  const logs = getTradeLogs()
  const filtered = logs.filter(l => l.id !== id)

  if (filtered.length === logs.length) return false

  localStorage.setItem(TRADE_LOG_KEY, JSON.stringify(filtered.sort((a, b) => a.timestamp - b.timestamp)))
  return true
}

// 清除所有日志
export function clearTradeLogs(): void {
  localStorage.removeItem(TRADE_LOG_KEY)
}

// 导出日志
export function exportTradeLogs(format: 'json' | 'csv' = 'json'): string {
  const logs = getTradeLogs()

  if (format === 'json') {
    return JSON.stringify(logs, null, 2)
  }

  // CSV 格式
  const headers = ['ID', '时间', '操作', '代码', '名称', '价格', '数量', '金额', '状态', '策略', '备注']
  const rows = logs.map(l => [
    l.id,
    new Date(l.timestamp).toLocaleString('zh-CN'),
    l.action,
    l.code,
    l.name,
    l.price?.toFixed(2) || '',
    l.quantity || '',
    l.amount?.toFixed(2) || '',
    l.status,
    l.strategy || '',
    l.notes || '',
  ])

  return [headers, ...rows].map(row => row.join(',')).join('\n')
}

// 获取统计
export function getTradeStats(options?: { startDate?: number; endDate?: number }): {
  total: number
  byAction: Record<string, number>
  byStatus: Record<string, number>
  totalAmount: number
  successRate: number
} {
  const logs = getTradeLogs(options)

  const byAction: Record<string, number> = {}
  const byStatus: Record<string, number> = {}
  let totalAmount = 0
  let successCount = 0

  logs.forEach(l => {
    byAction[l.action] = (byAction[l.action] || 0) + 1
    byStatus[l.status] = (byStatus[l.status] || 0) + 1

    if (l.amount) totalAmount += l.amount
    if (l.status === 'success') successCount++
  })

  return {
    total: logs.length,
    byAction,
    byStatus,
    totalAmount,
    successRate: logs.length > 0 ? successCount / logs.length : 0,
  }
}

// 获取最近交易
export function getRecentTrades(limit = 10): TradeLog[] {
  return getTradeLogs({ limit })
}

// 按代码分组统计
export function getTradeStatsByCode(): Map<string, { count: number; totalAmount: number }> {
  const logs = getTradeLogs()
  const stats = new Map<string, { count: number; totalAmount: number }>()

  logs.forEach(l => {
    const current = stats.get(l.code) || { count: 0, totalAmount: 0 }
    current.count++
    if (l.amount) current.totalAmount += l.amount
    stats.set(l.code, current)
  })

  return stats
}

// 按日期分组统计
export function getTradeStatsByDate(days = 30): Map<string, number> {
  const startDate = Date.now() - days * 24 * 60 * 60 * 1000
  const logs = getTradeLogs({ startDate })
  const stats = new Map<string, number>()

  logs.forEach(l => {
    const date = new Date(l.timestamp).toISOString().slice(0, 10)
    stats.set(date, (stats.get(date) || 0) + 1)
  })

  return stats
}

export default {
  logTrade,
  getTradeLogs,
  getTradeLog,
  updateTradeLogStatus,
  deleteTradeLog,
  clearTradeLogs,
  exportTradeLogs,
  getTradeStats,
  getRecentTrades,
  getTradeStatsByCode,
  getTradeStatsByDate,
}
