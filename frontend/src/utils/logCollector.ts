/**
 * 日志收集服务
 * 支持多级别日志、日志聚合、远程上报、本地存储
 */

// 日志级别
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'fatal'

// 日志条目
export interface LogEntry {
  id: string
  level: LogLevel
  message: string
  timestamp: number
  category: string
  userId?: string
  sessionId: string
  context?: Record<string, unknown>
  stack?: string
  duration?: number
  tags?: string[]
}

// 日志配置
export interface LogCollectorConfig {
  minLevel: LogLevel
  bufferSize: number
  flushInterval: number
  remoteEndpoint?: string
  enableConsole: boolean
  enableStorage: boolean
  enableRemote: boolean
  storageKey: string
  maxStorageSize: number
  sampleRate: number  // 采样率 0-1
}

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
  fatal: 4,
}

/**
 * 日志收集器
 */
export class LogCollector {
  private config: LogCollectorConfig = {
    minLevel: 'info',
    bufferSize: 100,
    flushInterval: 30000,  // 30秒
    enableConsole: true,
    enableStorage: true,
    enableRemote: false,
    storageKey: 'lianghua_logs',
    maxStorageSize: 1000,
    sampleRate: 1,
  }

  private buffer: LogEntry[] = []
  private sessionId: string
  private userId: string | null = null
  private flushTimer: ReturnType<typeof setInterval> | null = null
  private categories: Map<string, { count: number; lastLog: number }> = new Map()
  private _beforeunloadHandler: (() => void) | null = null

  constructor() {
    this.sessionId = this.generateSessionId()
    this.startFlushTimer()
    this.setupGlobalHandlers()
  }

  /**
   * 配置
   */
  configure(config: Partial<LogCollectorConfig>): void {
    this.config = { ...this.config, ...config }

    if (config.flushInterval) {
      this.stopFlushTimer()
      this.startFlushTimer()
    }
  }

  /**
   * 设置用户ID
   */
  setUserId(userId: string | null): void {
    this.userId = userId
  }

  /**
   * 记录日志
   */
  log(level: LogLevel, category: string, message: string, context?: Record<string, unknown>): LogEntry {
    // 检查级别
    if (LOG_LEVELS[level] < LOG_LEVELS[this.config.minLevel]) {
      return null as unknown as LogEntry
    }

    // 采样检查
    if (Math.random() > this.config.sampleRate) {
      return null as unknown as LogEntry
    }

    const entry: LogEntry = {
      id: this.generateId(),
      level,
      message,
      timestamp: Date.now(),
      category,
      userId: this.userId || undefined,
      sessionId: this.sessionId,
      context,
      tags: this.extractTags(message, context),
    }

    // 添加堆栈（错误级别以上）
    if (level === 'error' || level === 'fatal') {
      entry.stack = new Error().stack
    }

    // 写入缓冲
    this.buffer.push(entry)

    // 更新分类统计
    const catStats = this.categories.get(category) || { count: 0, lastLog: 0 }
    catStats.count++
    catStats.lastLog = entry.timestamp
    this.categories.set(category, catStats)

    // 控制台输出
    if (this.config.enableConsole) {
      this.logToConsole(entry)
    }

    // 检查缓冲区大小，满了就刷新
    if (this.buffer.length >= this.config.bufferSize) {
      this.flush()
    }

    return entry
  }

  /**
   * 快捷方法
   */
  debug(category: string, message: string, context?: Record<string, unknown>): LogEntry {
    return this.log('debug', category, message, context)
  }

  info(category: string, message: string, context?: Record<string, unknown>): LogEntry {
    return this.log('info', category, message, context)
  }

  warn(category: string, message: string, context?: Record<string, unknown>): LogEntry {
    return this.log('warn', category, message, context)
  }

  error(category: string, message: string, context?: Record<string, unknown>): LogEntry {
    return this.log('error', category, message, context)
  }

  fatal(category: string, message: string, context?: Record<string, unknown>): LogEntry {
    return this.log('fatal', category, message, context)
  }

  /**
   * 记录操作耗时
   */
  time<T>(category: string, operation: string, fn: () => Promise<T>): Promise<T>
  time<T>(category: string, operation: string, fn: () => T): T
  async time<T>(category: string, operation: string, fn: () => Promise<T> | T): Promise<T> {
    const startTime = performance.now()

    try {
      const result = await fn()
      const duration = performance.now() - startTime

      this.log('info', category, `${operation} completed`, { duration })

      return result
    } catch (error) {
      const duration = performance.now() - startTime

      this.log('error', category, `${operation} failed`, {
        duration,
        error: String(error),
      })

      throw error
    }
  }

  /**
   * 刷新日志到存储/远程
   */
  async flush(): Promise<void> {
    if (this.buffer.length === 0) return

    const logs = [...this.buffer]
    this.buffer = []

    // 存储到本地
    if (this.config.enableStorage) {
      this.saveToStorage(logs)
    }

    // 上报到远程
    if (this.config.enableRemote && this.config.remoteEndpoint) {
      await this.sendToRemote(logs)
    }
  }

  /**
   * 获取日志
   */
  getLogs(filter?: {
    level?: LogLevel
    category?: string
    startTime?: number
    endTime?: number
    limit?: number
  }): LogEntry[] {
    let logs: LogEntry[]

    // 从存储中获取
    if (this.config.enableStorage) {
      const stored = this.loadFromStorage()
      logs = [...stored, ...this.buffer]
    } else {
      logs = [...this.buffer]
    }

    // 排序
    logs.sort((a, b) => b.timestamp - a.timestamp)

    // 筛选
    if (filter) {
      if (filter.level) {
        logs = logs.filter(l => LOG_LEVELS[l.level] >= LOG_LEVELS[filter.level!])
      }
      if (filter.category) {
        logs = logs.filter(l => l.category === filter.category)
      }
      if (filter.startTime) {
        logs = logs.filter(l => l.timestamp >= filter.startTime!)
      }
      if (filter.endTime) {
        logs = logs.filter(l => l.timestamp <= filter.endTime!)
      }
      if (filter.limit) {
        logs = logs.slice(0, filter.limit)
      }
    }

    return logs
  }

  /**
   * 获取分类统计
   */
  getCategoryStats(): Array<{ category: string; count: number; lastLog: number }> {
    return Array.from(this.categories.entries()).map(([category, stats]) => ({
      category,
      ...stats,
    }))
  }

  /**
   * 清除日志
   */
  clear(): void {
    this.buffer = []
    this.categories.clear()

    if (this.config.enableStorage) {
      try { localStorage.removeItem(this.config.storageKey) } catch { /* silent fail */ }
    }
  }

  /**
   * 导出日志
   */
  export(format: 'json' | 'csv' = 'json'): string {
    const logs = this.getLogs()

    if (format === 'json') {
      return JSON.stringify(logs, null, 2)
    }

    // CSV 格式
    const headers = ['timestamp', 'level', 'category', 'message', 'userId', 'sessionId']
    const rows = logs.map(l => [
      new Date(l.timestamp).toISOString(),
      l.level,
      l.category,
      `"${l.message.replace(/"/g, '""')}"`,
      l.userId || '',
      l.sessionId,
    ])

    return [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
  }

  // 私有方法

  private generateId(): string {
    return `log_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  private generateSessionId(): string {
    let sessionId = sessionStorage.getItem('logSessionId')
    if (!sessionId) {
      sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
      sessionStorage.setItem('logSessionId', sessionId)
    }
    return sessionId
  }

  private extractTags(message: string, context?: Record<string, unknown>): string[] {
    const tags: string[] = []

    // 从消息中提取标签（如 [API]、[Network] 等）
    const tagMatches = message.match(/\[([^\]]+)\]/g)
    if (tagMatches) {
      tags.push(...tagMatches.map(t => t.slice(1, -1)))
    }

    // 从 context 中提取
    if (context?.tags && Array.isArray(context.tags)) {
      tags.push(...context.tags)
    }

    return tags
  }

  private logToConsole(entry: LogEntry): void {
    const prefix = `[${entry.category}] [${entry.level.toUpperCase()}]`
    const time = new Date(entry.timestamp).toLocaleTimeString()

    const style = this.getConsoleStyle(entry.level)

    switch (entry.level) {
      case 'debug':
        console.debug(`%c${time} ${prefix}`, style, entry.message, entry.context || '')
        break
      case 'info':
        console.info(`%c${time} ${prefix}`, style, entry.message, entry.context || '')
        break
      case 'warn':
        console.warn(`%c${time} ${prefix}`, style, entry.message, entry.context || '')
        break
      case 'error':
      case 'fatal':
        console.error(`%c${time} ${prefix}`, style, entry.message, entry.context || '', entry.stack || '')
        break
    }
  }

  private getConsoleStyle(level: LogLevel): string {
    switch (level) {
      case 'debug':
        return 'color: gray'
      case 'info':
        return 'color: blue'
      case 'warn':
        return 'color: orange'
      case 'error':
        return 'color: red'
      case 'fatal':
        return 'color: white; background: red'
      default:
        return ''
    }
  }

  private saveToStorage(logs: LogEntry[]): void {
    try {
      const existing = this.loadFromStorage()
      const merged = [...logs, ...existing].slice(0, this.config.maxStorageSize)
      localStorage.setItem(this.config.storageKey, JSON.stringify(merged))
    } catch (error) {
      // 存储空间不足 — 保留最新的 maxStorageSize/2 条，而非丢弃全部日志
      console.warn('[LogCollector] Storage full, keeping latest half of logs')
      const existing = this.loadFromStorage()
      const merged = [...logs, ...existing]
      // 按时间戳降序排序，取最新的
      merged.sort((a, b) => b.timestamp - a.timestamp)
      const reduced = merged.slice(0, Math.floor(this.config.maxStorageSize / 2))
      try { localStorage.setItem(this.config.storageKey, JSON.stringify(reduced)) } catch { /* silent fail */ }
    }
  }

  private loadFromStorage(): LogEntry[] {
    try {
      const data = localStorage.getItem(this.config.storageKey)
      return data ? JSON.parse(data) : []
    } catch {
      return []
    }
  }

  private async sendToRemote(logs: LogEntry[]): Promise<void> {
    try {
      await fetch(this.config.remoteEndpoint!, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          logs,
          metadata: {
            sessionId: this.sessionId,
            userId: this.userId,
            userAgent: navigator.userAgent,
            url: window.location.href,
            timestamp: Date.now(),
          },
        }),
      })
    } catch (error) {
      // 远程发送失败，存回缓冲
      console.error('[LogCollector] Failed to send logs to remote:', error)
      this.buffer.unshift(...logs)
    }
  }

  private startFlushTimer(): void {
    this.flushTimer = setInterval(() => this.flush(), this.config.flushInterval)
  }

  private stopFlushTimer(): void {
    if (this.flushTimer) {
      clearInterval(this.flushTimer)
      this.flushTimer = null
    }
  }

  private setupGlobalHandlers(): void {
    // Note: global error/unhandledrejection listeners are managed by errorLogger.ts
    // to avoid duplicate registration. We only handle beforeunload here.
    this._beforeunloadHandler = () => { this.flush() }
    window.addEventListener('beforeunload', this._beforeunloadHandler)
  }

  destroy(): void {
    this.stopFlushTimer()
    if (this._beforeunloadHandler) {
      window.removeEventListener('beforeunload', this._beforeunloadHandler)
      this._beforeunloadHandler = null
    }
  }
}

// 导出单例
export const logCollector = new LogCollector()

// 便捷方法
export const logger = {
  debug: (category: string, message: string, context?: Record<string, unknown>) =>
    logCollector.debug(category, message, context),
  info: (category: string, message: string, context?: Record<string, unknown>) =>
    logCollector.info(category, message, context),
  warn: (category: string, message: string, context?: Record<string, unknown>) =>
    logCollector.warn(category, message, context),
  error: (category: string, message: string, context?: Record<string, unknown>) =>
    logCollector.error(category, message, context),
  fatal: (category: string, message: string, context?: Record<string, unknown>) =>
    logCollector.fatal(category, message, context),
  time: <T>(category: string, operation: string, fn: () => Promise<T> | T) =>
    logCollector.time(category, operation, fn as () => Promise<T>),
  getLogs: (filter?: Parameters<LogCollector['getLogs']>[0]) => logCollector.getLogs(filter),
  clear: () => logCollector.clear(),
  export: (format?: 'json' | 'csv') => logCollector.export(format),
}

export default logCollector
