/**
 * WebSocket 共享实例
 * 基于 WSReconnect 统一管理 market 和 signals 连接
 * 在 Electron 环境中自动使用 IPC 代理
 *
 * Token 由 StartupLoading 从后端 health 接口获取后缓存到 localStorage，
 * WS 实例在此模块加载时从 localStorage 读取。
 *
 * 心跳策略：交易时间(9:00-15:30) 30s，非交易时间 120s
 */
import { WSReconnect } from './wsReconnect'
import { getWsBase } from './config'

const STALE_KEY = 'ws_stale_threshold_sec'
const DEFAULT_STALE_MS = 60000

function getToken(): string {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('ws_auth_token') || ''
  }
  return ''
}

function getStaleThresholdMs(): number {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem(STALE_KEY)
    if (saved) return parseInt(saved, 10) * 1000
  }
  return DEFAULT_STALE_MS
}

// 交易时间判断：周一至周五 9:00-15:30 使用短心跳
function getHeartbeatInterval(): number {
  const now = new Date()
  const day = now.getDay()
  const hours = now.getHours()
  const minutes = now.getMinutes()
  const isWeekday = day >= 1 && day <= 5
  const timeValue = hours * 60 + minutes
  const isTradingHours = timeValue >= 9 * 60 && timeValue <= 15 * 60 + 30
  return (isWeekday && isTradingHours) ? 30000 : 120000
}

const WS_BASE = getWsBase()

function buildUrl(path: string): string {
  const sep = path.includes('?') ? '&' : '?'
  const token = getToken()
  return `${path}${sep}token=${encodeURIComponent(token)}`
}

/**
 * 创建 WSReconnect 实例并包装 connect() 方法。
 * 每次连接前重新从 localStorage 读取 token，确保永远使用最新 token。
 */
function createWsReconnect(basePath: string, wsId: string): WSReconnect {
  const url = buildUrl(`${WS_BASE}${basePath}`)
  const ws = new WSReconnect(url, {
    initialDelay: 1000,
    maxDelay: 30000,
    heartbeatInterval: getHeartbeatInterval(),
    staleThresholdMs: getStaleThresholdMs(),
  }, wsId)

  const origConnect = ws.connect.bind(ws)
  ws.connect = function(_overrideUrl?: string) {
    const freshUrl = buildUrl(`${WS_BASE}${basePath}`)
    return origConnect(freshUrl)
  }

  return ws
}

export const marketWs = createWsReconnect('/api/v1/ws/market', 'market')
export const signalsWs = createWsReconnect('/api/v1/ws/signals', 'signals')

let _lastToken = ''
let _refreshing = false

/**
 * Token 更新后重置 WebSocket 连接。
 * 串行化 reset+connect：先断开 market，重连 market 成功后再断开/重连 signals，
 * 避免两个连接同时断开导致大量并发重连请求。
 * 使用 _refreshing 互斥锁防止并发调用导致双连接。
 */
export function refreshWsToken(): void {
  if (_refreshing) return
  _refreshing = true

  try {
    const newToken = getToken()
    if (newToken === _lastToken && marketWs.isConnected()) return
    _lastToken = newToken
    const marketUrl = buildUrl(`${WS_BASE}/api/v1/ws/market`)
    const signalsUrl = buildUrl(`${WS_BASE}/api/v1/ws/signals`)

    // 串行化：先 reset+connect market，等稳定后再处理 signals
    marketWs.reset(marketUrl)
    marketWs.connect()

    // 延迟 500ms 再 reset signals，避免两个 WS 同时断开/重连的冲击
    setTimeout(() => {
      try {
        signalsWs.reset(signalsUrl)
        signalsWs.connect()
      } finally {
        _refreshing = false
      }
    }, 500)
  } catch {
    _refreshing = false
  }
}
