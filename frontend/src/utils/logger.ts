/**
 * 日志工具类
 * 用于记录应用运行日志
 */

interface LogEntry {
  time: string
  level: 'INFO' | 'WARN' | 'ERROR'
  message: string
}

const MAX_LOGS = 500

function formatTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function getLogs(): LogEntry[] {
  try {
    const saved = localStorage.getItem('app_logs')
    return saved ? JSON.parse(saved) : []
  } catch {
    return []
  }
}

function saveLogs(logs: LogEntry[]): void {
  try {
    // 限制日志数量
    const trimmed = logs.slice(-MAX_LOGS)
    localStorage.setItem('app_logs', JSON.stringify(trimmed))
  } catch {
    // 存储满了，清除旧日志
    localStorage.removeItem('app_logs')
  }
}

function addLog(level: LogEntry['level'], message: string): void {
  const logs = getLogs()
  logs.push({
    time: formatTime(),
    level,
    message,
  })
  saveLogs(logs)
}

export const logger = {
  info: (message: string) => {
    console.log(`[INFO] ${message}`)
    addLog('INFO', message)
  },

  warn: (message: string) => {
    console.warn(`[WARN] ${message}`)
    addLog('WARN', message)
  },

  error: (message: string) => {
    console.error(`[ERROR] ${message}`)
    addLog('ERROR', message)
  },

  getLogs,
  clear: () => {
    localStorage.removeItem('app_logs')
  },

  export: (): string => {
    const logs = getLogs()
    return logs.map(l => `[${l.time}] [${l.level}] ${l.message}`).join('\n')
  },
}

export default logger
